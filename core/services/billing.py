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
        issue_date = timezone.now().date()
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


def build_billing_schedule(quotation, periods=12):
    """Create `BillingScheduleEntry` rows for the quotation's RECURRING lines.

    One entry per period per recurring line, spaced by the line's plan interval
    (`SubscriptionPlan.MONTHS_PER_INTERVAL`). Recurring lines never appear on the
    one-time invoice — invariant 10.
    """
    raise NotImplementedError("T-20 — subscription lines and hybrid billing")


def upcoming_schedule(quotation, as_of=None):
    """The quotation's SCHEDULED entries from `as_of` forward, in due-date order.

    What the subscription and billing screen renders (B7). Reads only.
    """
    raise NotImplementedError("T-20 — subscription lines and hybrid billing")


def prorate_quantity_change(line, new_qty, effective_date):
    """Adjust a recurring line mid-cycle and write the proration entry. FR-31.

    **Blocked by ADR-008 — do not implement until it is closed.** The proration basis is
    genuinely unspecified in the problem statement, and `SubscriptionPlan.proration_method`
    holds `"UNDECIDED"` for exactly that reason. Whatever basis is chosen must be recorded
    in ADR-008 and reflected on the plan row before this function exists.
    """
    raise NotImplementedError("T-20 — blocked by ADR-008 (proration basis undecided)")
