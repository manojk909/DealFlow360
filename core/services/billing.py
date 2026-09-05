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

from decimal import Decimal


class OverpaymentError(Exception):
    """A payment would push total payments above the invoice amount (invariant 11).

    Refused rather than clamped. Silently accepting an overpayment and capping it would
    make the invoice status a lie.
    """


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
        is correct rather than an error.

    Raises:
        ValueError: if the quotation is in a stage that cannot be invoiced.
    """
    raise NotImplementedError("T-17 — order confirmation, invoice and payment")


def record_payment(invoice, amount, method, paid_at=None):
    """Record a payment and re-derive the invoice status. One transaction.

    Status is derived from the payment sum, every time, and never assigned directly:
    zero paid is UNPAID, part paid is PARTIAL, fully paid is PAID (invariant 11). When
    the invoice becomes PAID the quotation moves to PAID as well, and an audit row is
    written.

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
    raise NotImplementedError("T-17 — order confirmation, invoice and payment")


def derive_invoice_status(invoice):
    """The status an invoice's payments imply. Pure — reads, decides, returns.

    Exposed separately so a screen can show the derived status without writing, and so
    the derivation is testable on its own.

    Returns:
        One of `Invoice.Status`.
    """
    raise NotImplementedError("T-17 — order confirmation, invoice and payment")


def build_billing_schedule(quotation, periods=12):
    """Create `BillingScheduleEntry` rows for the quotation's RECURRING lines.

    One entry per period per recurring line, spaced by the line's plan interval
    (`SubscriptionPlan.MONTHS_PER_INTERVAL`). Recurring lines never appear on the
    one-time invoice — invariant 10.

    Args:
        quotation: a `core.models.Quotation`.
        periods: how many future periods to schedule.

    Returns:
        list of created `core.models.BillingScheduleEntry` rows; empty when the quotation
        has no recurring lines.
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

    Returns:
        The `BillingScheduleEntry` created with `is_proration_adjustment=True`.
    """
    raise NotImplementedError("T-20 — blocked by ADR-008 (proration basis undecided)")
