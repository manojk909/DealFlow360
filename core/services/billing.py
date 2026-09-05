"""
Billing — invoices, payments, recurring schedules and proration. BR-5.

Implements FR-20 (T-17) and FR-29/30/31 (T-20). Owned by **T-17** and **T-20**.

The rule that makes hybrid billing hybrid, and DATA_MODEL.md invariant 10:

> One-time lines bill through an **Invoice**. Recurring lines bill through
> **BillingScheduleEntry** rows. Never the same artefact, even on the same order.

Two invariants are enforced here because SQLite cannot express them:

* 11 — the sum of payments on an invoice never exceeds its amount, and the invoice's
  status is **derived** from that sum, never set by hand. `record_payment()` is the only
  function permitted to write a Payment row or move an Invoice status.
* 9 — already a database CHECK, but `build_billing_schedule()` relies on it: a RECURRING
  line always has a plan to schedule against.

**ADR-008 is still open.** The proration basis — daily pro-rata versus whole-period — is
undecided, and `SubscriptionPlan.proration_method` currently holds `"UNDECIDED"`.
`prorate_quantity_change()` must not be implemented until ADR-008 is closed; guessing a
basis here and writing it into code is precisely the thing the ADR exists to prevent.
"""

from datetime import timedelta
import calendar
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

CENTS = Decimal("0.01")
HUNDRED = Decimal("100")

# Payment terms are not specified anywhere in the problem statement. Fourteen days is a
# default, not a rule — if terms ever matter they become a field on Customer, not a
# constant here.
DEFAULT_PAYMENT_TERM_DAYS = 14


class OverpaymentError(Exception):
    """A payment would push total payments above the invoice amount (invariant 11).

    Refused rather than clamped. Silently accepting an overpayment and capping it would
    make the invoice status a lie.
    """


def _money(value):
    return Decimal(value).quantize(CENTS)


def _amount_paid(invoice):
    """Sum of payments, in Python. Never a SQLite aggregate over a money column (ADR-002)."""
    total = Decimal("0")
    for amount in invoice.payments.values_list("amount", flat=True):
        total += amount
    return _money(total)


def generate_invoice(quotation):
    """Create the one-time invoice for a quotation. One transaction.

    **One-time lines only.** Recurring lines are excluded and go to
    `build_billing_schedule()` instead — that separation is invariant 10 and is what AC-6
    checks.

    Amount is the sum of `line_total` for ONE_TIME lines with the order-level discount
    applied, computed in Python with `Decimal`, never through a SQLite aggregate.

    Status starts at UNPAID (not DRAFT) because the order is already confirmed by the
    time this runs.

    Args:
        quotation: a `core.models.Quotation` in CONFIRMED or FULFILLED.

    Returns:
        The created `core.models.Invoice`, or `None` when the quotation has no one-time
        lines at all — a pure-subscription order has a schedule and no invoice, and that
        is correct rather than an error. An existing invoice is returned unchanged rather
        than duplicated.

    Raises:
        ValueError: if the quotation is in a stage that cannot be invoiced.
    """
    from core.models import Invoice, Quotation, QuotationLine
    from core.services import approval

    existing = quotation.invoices.first()
    if existing is not None:
        return existing

    invoiceable = {Quotation.Stage.CONFIRMED, Quotation.Stage.FULFILLED}
    if quotation.stage not in invoiceable:
        raise ValueError(
            f"A quotation in {quotation.stage} cannot be invoiced; expected one of "
            f"{sorted(invoiceable)}."
        )

    one_time = quotation.lines.filter(line_type=QuotationLine.LineType.ONE_TIME)
    if not one_time.exists():
        return None  # Pure subscription order: a schedule, no invoice. Invariant 10.

    subtotal = Decimal("0")
    for line_total in one_time.values_list("line_total", flat=True):
        subtotal += line_total
    amount = _money(
        _money(subtotal) * (Decimal("1") - quotation.order_discount_pct / HUNDRED)
    )

    with transaction.atomic():
        issue_date = timezone.localdate()
        invoice = Invoice.objects.create(
            quotation=quotation,
            number=f"INV-{issue_date.year}-{Invoice.objects.count() + 1:04d}",
            amount=amount,
            status=Invoice.Status.UNPAID,
            issue_date=issue_date,
            due_date=issue_date + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS),
        )
        quotation.stage = Quotation.Stage.INVOICED
        quotation.last_activity_at = timezone.now()
        quotation.save(update_fields=["stage", "last_activity_at"])

        recurring_count = quotation.lines.exclude(
            line_type=QuotationLine.LineType.ONE_TIME
        ).count()
        approval.record(
            quotation,
            action="INVOICE_GENERATED",
            reason=(
                f"{invoice.number} for {one_time.count()} one-time line(s), {amount}. "
                + (
                    f"{recurring_count} recurring line(s) excluded — they bill on a "
                    f"schedule, not on this invoice (invariant 10)."
                    if recurring_count
                    else "No recurring lines on this order."
                )
            ),
            payload={"invoice": invoice.number, "amount": str(amount)},
        )
    return invoice


def derive_invoice_status(invoice):
    """The status an invoice's payments imply. Pure — reads, decides, returns.

    Exposed separately so a screen can show the derived status without writing, and so
    the derivation is testable on its own.

    Returns:
        One of `Invoice.Status`.
    """
    from core.models import Invoice

    paid = _amount_paid(invoice)
    if paid <= 0:
        return Invoice.Status.UNPAID
    if paid < invoice.amount:
        return Invoice.Status.PARTIAL
    return Invoice.Status.PAID


def record_payment(invoice, amount, method="BANK_TRANSFER", paid_at=None):
    """Record a payment and re-derive the invoice status. One transaction.

    Status is derived from the payment sum, every time, and never assigned directly:
    zero paid is UNPAID, part paid is PARTIAL, fully paid is PAID (invariant 11). When
    the invoice becomes PAID the quotation moves to PAID as well, and an audit row is
    written.

    This is the **only** function in the codebase permitted to write a Payment row or
    move an Invoice status. SQLite cannot express invariant 11 as a CHECK constraint
    (it needs a subquery), so this function is where the rule actually lives — which is
    also why the Django admin registers Payment read-only.

    Args:
        invoice: a `core.models.Invoice`.
        amount: positive Decimal.
        method: short string, e.g. `"BANK_TRANSFER"`.
        paid_at: timezone-aware datetime; defaults to now.

    Returns:
        The created `core.models.Payment`.

    Raises:
        OverpaymentError: if this payment would exceed the invoice amount.
        ValueError: if `amount` is not positive.
    """
    from core.models import Invoice, Payment, Quotation
    from core.services import approval

    amount = _money(amount)
    if amount <= 0:
        raise ValueError(f"A payment must be positive, got {amount}.")

    already = _amount_paid(invoice)
    if already + amount > invoice.amount:
        raise OverpaymentError(
            f"{invoice.number} is {invoice.amount} and {already} is already paid; "
            f"a further {amount} would overpay by "
            f"{_money(already + amount - invoice.amount)}."
        )

    with transaction.atomic():
        payment = Payment.objects.create(
            invoice=invoice,
            amount=amount,
            method=method,
            paid_at=paid_at or timezone.now(),
        )

        invoice.status = derive_invoice_status(invoice)
        invoice.save(update_fields=["status"])

        quotation = invoice.quotation
        if invoice.status == Invoice.Status.PAID:
            quotation.stage = Quotation.Stage.PAID
            quotation.last_activity_at = timezone.now()
            quotation.save(update_fields=["stage", "last_activity_at"])

        approval.record(
            quotation,
            action="PAYMENT_RECORDED",
            reason=(
                f"{amount} against {invoice.number} by {method}. "
                f"Invoice status derived as {invoice.status}."
            ),
            payload={
                "invoice": invoice.number,
                "amount": str(amount),
                "paid_total": str(_amount_paid(invoice)),
                "status": invoice.status,
            },
        )
    return payment


def _period_months(line):
    """How many months one billing period of this line spans."""
    from core.models import SubscriptionPlan

    plan = line.subscription_plan
    return SubscriptionPlan.MONTHS_PER_INTERVAL[plan.interval] if plan else 1


def _add_months(date, months):
    """`date` shifted forward by whole months, clamped to the end of the target month.

    stdlib only — `calendar.monthrange` already knows how long February is, so 31 Jan
    plus one month is 28 Feb rather than a crash or a silent roll into March.
    """
    month_index = date.month - 1 + months
    year = date.year + month_index // 12
    month = month_index % 12 + 1
    return date.replace(
        year=year, month=month, day=min(date.day, calendar.monthrange(year, month)[1])
    )


def build_billing_schedule(quotation, periods=12):
    """Create `BillingScheduleEntry` rows for the quotation's RECURRING lines.

    One entry per period per recurring line, spaced by the line's plan interval
    (`SubscriptionPlan.MONTHS_PER_INTERVAL`). Recurring lines never appear on the
    one-time Invoice — invariant 10.

    Idempotent: a quotation that already has a schedule keeps it, so confirming twice
    cannot double-bill a subscriber.
    """
    from core.models import BillingScheduleEntry, QuotationLine

    if quotation.billing_schedule.exists():
        return list(quotation.billing_schedule.all())

    recurring = quotation.lines.exclude(
        line_type=QuotationLine.LineType.ONE_TIME
    ).select_related("subscription_plan")
    if not recurring:
        return []

    start = timezone.localdate()
    entries = []
    with transaction.atomic():
        for line in recurring:
            months = _period_months(line)
            for period in range(periods):
                entries.append(
                    BillingScheduleEntry(
                        quotation=quotation,
                        quotation_line=line,
                        due_date=_add_months(start, months * period),
                        amount=_money(line.line_total),
                    )
                )
        BillingScheduleEntry.objects.bulk_create(entries)
    return entries


def on_order_confirmed(quotation, periods=12):
    """Everything confirmation implies for billing and the delivery promise.

    Two paths reach CONFIRMED — the rep accepting a warehouse split, and the customer
    confirming in the portal — so this lives in one function they both call rather than
    being duplicated into each. Idempotent on both halves.

    * Recurring lines get their billing schedule (invariant 10 keeps them off the invoice).
    * The order gets a promised delivery date, `delivery_promise_days` out, which is the
      only thing `health.delivery_slippage()` has to measure against (ADR-007).
    """
    from core.models import SalesSetting

    from core.services import assets

    from core.models import Quotation

    # ADR-015. An amendment changes something the customer already owns: it must not build
    # a second schedule or a second asset, so it branches before either of those runs.
    if quotation.kind == Quotation.Kind.AMENDMENT:
        assets.apply_amendment(quotation)
        return []

    schedule = build_billing_schedule(quotation, periods=periods)
    # ADR-013. What the customer now owns, from the same hook, so an asset cannot exist
    # for an order nobody confirmed.
    assets.create_from_confirmation(quotation)
    if quotation.promised_delivery_date is None:
        quotation.promised_delivery_date = timezone.localdate() + timedelta(
            days=SalesSetting.load().delivery_promise_days
        )
        quotation.save(update_fields=["promised_delivery_date"])
    return schedule


def upcoming_schedule(quotation, as_of=None):
    """The quotation's SCHEDULED entries from `as_of` forward, in due-date order."""
    from core.models import BillingScheduleEntry

    as_of = as_of or timezone.localdate()
    return list(
        quotation.billing_schedule.filter(
            status=BillingScheduleEntry.Status.SCHEDULED, due_date__gte=as_of
        ).select_related("quotation_line", "quotation_line__product")
    )


def prorate_quantity_change(line, new_qty, effective_date=None):
    """Adjust a recurring line mid-cycle and write the proration entry. FR-31.

    **ADR-008: daily pro-rata on the current period.** The customer is charged (or
    credited) for the changed quantity only for the days left in the period they are
    already in, and every future period bills at the new quantity in full.

        adjustment = (new_qty - old_qty) x unit period price x days_remaining / days_in_period

    Chosen because it is the rule a customer can check on a calendar. Whole-period billing
    would overcharge someone who upgrades on the last day of a month; not prorating at all
    would give away most of a period on every upgrade.

    Returns:
        The `BillingScheduleEntry` carrying the adjustment, or `None` when the quantity
        did not change or nothing of the period remains to prorate.

    Raises:
        ValueError: if the line is not recurring, or `new_qty` is below 1.
    """
    from core.models import BillingScheduleEntry, QuotationLine

    if line.line_type == QuotationLine.LineType.ONE_TIME:
        raise ValueError("Only a recurring line can be prorated.")
    if new_qty < 1:
        raise ValueError("Quantity must be at least 1.")

    effective_date = effective_date or timezone.localdate()
    old_qty = line.qty
    if new_qty == old_qty:
        return None

    period_start, period_end = current_period(line, effective_date)
    days_in_period = (period_end - period_start).days
    days_remaining = max(0, (period_end - effective_date).days)
    unit_period_price = _money(line.line_total / old_qty)
    adjustment = (
        _money(
            unit_period_price
            * Decimal(new_qty - old_qty)
            * Decimal(days_remaining)
            / Decimal(days_in_period)
        )
        if days_in_period > 0 and days_remaining > 0
        else Decimal("0.00")
    )

    with transaction.atomic():
        line.qty = new_qty
        line.line_total = _money(unit_period_price * new_qty)
        line.save(update_fields=["qty", "line_total"])

        # Every not-yet-due period bills at the new quantity in full.
        for entry in line.billing_schedule.filter(
            status=BillingScheduleEntry.Status.SCHEDULED,
            due_date__gt=effective_date,
            is_proration_adjustment=False,
        ):
            entry.amount = _money(line.line_total)
            entry.save(update_fields=["amount"])

        if adjustment == Decimal("0.00"):
            return None  # Changed on the last day of a period: nothing left to prorate.
        return BillingScheduleEntry.objects.create(
            quotation=line.quotation,
            quotation_line=line,
            due_date=effective_date,
            amount=adjustment,
            is_proration_adjustment=True,
        )


def current_period(line, on_date):
    """The billing period `on_date` falls in, as (start, end).

    Periods run from the line's first scheduled entry. A line with no schedule yet is
    treated as starting today, so proration on an unconfirmed order still has a basis.
    """
    from core.models import BillingScheduleEntry

    months = _period_months(line)
    first = (
        line.billing_schedule.filter(is_proration_adjustment=False)
        .order_by("due_date")
        .values_list("due_date", flat=True)
        .first()
    ) or on_date

    start = first
    while _add_months(start, months) <= on_date:
        start = _add_months(start, months)
    return start, _add_months(start, months)


def cancel_subscription_line(line, effective_date=None, reason=""):
    """Cancel a recurring line and credit the unused part of the current period. FR-32.

    **ADR-008, same basis as proration.** Unused days of the period already paid come back
    as a credit note; every future scheduled entry is cancelled so it never bills.

    Returns:
        The credit-note `Invoice`, or `None` when no part of the period remains.
    """
    from core.models import BillingScheduleEntry, Invoice, QuotationLine
    from core.services import approval

    if line.line_type == QuotationLine.LineType.ONE_TIME:
        raise ValueError("Only a recurring line can be cancelled.")

    effective_date = effective_date or timezone.localdate()
    period_start, period_end = current_period(line, effective_date)
    days_in_period = (period_end - period_start).days
    days_remaining = max(0, (period_end - effective_date).days)
    credit = (
        _money(line.line_total * Decimal(days_remaining) / Decimal(days_in_period))
        if days_in_period > 0
        else Decimal("0.00")
    )

    with transaction.atomic():
        cancelled = line.billing_schedule.filter(
            status=BillingScheduleEntry.Status.SCHEDULED, due_date__gte=effective_date
        ).update(status=BillingScheduleEntry.Status.CANCELLED)

        note = None
        if credit > 0:
            note = Invoice.objects.create(
                quotation=line.quotation,
                number=f"CN-{effective_date.year}-{Invoice.objects.count() + 1:04d}",
                amount=credit,
                status=Invoice.Status.UNPAID,
                issue_date=effective_date,
                due_date=effective_date,
                is_credit_note=True,
            )
        approval.record(
            line.quotation,
            action="SUBSCRIPTION_CANCELLED",
            reason=(
                f"{line.product.name} cancelled from {effective_date}. "
                f"{cancelled} scheduled entr{'y' if cancelled == 1 else 'ies'} cancelled. "
                + (f"Credit note {note.number} for {credit} ({days_remaining} of "
                   f"{days_in_period} days unused)." if note else "No unused days to credit.")
                + (f" Reason: {reason}" if reason else "")
            ),
        )
    return note
