"""
Billing — subscription plans, billing schedules, invoices and payments.

Owns money out. Must not touch stock (ARCHITECTURE.md domain table).

BR-5: one order can mix one-time and recurring lines, and they bill through **separate**
artefacts — an Invoice for one-time lines, BillingScheduleEntry rows for recurring ones
(DATA_MODEL.md invariant 10).
"""

from django.core.validators import MinValueValidator
from django.db import models


class SubscriptionPlan(models.Model):
    """
    A5 recurring plan. **P0**, not SHOULD: AC-1 requires a subscription plan to be created
    and to persist, so the plan record and its admin CRUD are MUST. See the A5 split in
    DECISIONS.md. The proration and cancellation *rules* it carries are only exercised by
    T-20, and ADR-008 (proration basis) is still open — hence the free-text fields.
    """

    class Interval(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        QUARTERLY = "QUARTERLY", "Quarterly"
        YEARLY = "YEARLY", "Yearly"

    name = models.CharField(max_length=80, unique=True)
    interval = models.CharField(max_length=16, choices=Interval.choices, default=Interval.MONTHLY)
    proration_method = models.CharField(
        max_length=40,
        default="UNDECIDED",
        help_text="ADR-008 is still open. Stored, not yet acted on — T-20 owns this.",
    )
    cancellation_policy = models.CharField(
        max_length=40,
        default="UNDECIDED",
        help_text="ADR-008 is still open. Stored, not yet acted on — T-30 owns this.",
    )

    # How many months one billing period spans. Used to build the schedule in T-20.
    MONTHS_PER_INTERVAL = {Interval.MONTHLY: 1, Interval.QUARTERLY: 3, Interval.YEARLY: 12}

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_interval_display()})"


class BillingScheduleEntry(models.Model):
    """
    SHOULD (T-20). One future billing event for one recurring line.

    Recurring lines never appear on the one-time Invoice — that separation is
    DATA_MODEL.md invariant 10 and the whole point of BR-5.
    """

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        BILLED = "BILLED", "Billed"
        CANCELLED = "CANCELLED", "Cancelled"

    quotation = models.ForeignKey(
        "core.Quotation", on_delete=models.CASCADE, related_name="billing_schedule"
    )
    quotation_line = models.ForeignKey(
        "core.QuotationLine", on_delete=models.CASCADE, related_name="billing_schedule"
    )
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SCHEDULED)
    is_proration_adjustment = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "billing schedule entries"
        ordering = ["due_date", "id"]

    def __str__(self):
        return f"{self.quotation.number} — {self.due_date}: {self.amount}"


class Invoice(models.Model):
    """
    One-time lines only (invariant 10).

    **Status is derived, never set by hand** (invariant 11). SQLite cannot express
    "sum of payments <= amount" as a CHECK constraint — it would need a subquery — so
    that invariant is enforced in `core/services/billing.py`, which is the only place
    allowed to record a payment or move this status. Stated here so the absence of a
    database constraint is a documented decision rather than an oversight.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partially paid"
        PAID = "PAID", "Paid"

    quotation = models.ForeignKey("core.Quotation", on_delete=models.PROTECT, related_name="invoices")
    number = models.CharField(max_length=40, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField()
    due_date = models.DateField()
    is_credit_note = models.BooleanField(default=False)

    class Meta:
        ordering = ["-issue_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gte=0), name="invoice_amount_non_negative")
        ]

    def __str__(self):
        return f"{self.number} ({self.status})"


class Payment(models.Model):
    """A payment against one invoice. Overpayment is refused by the billing service."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=40, default="BANK_TRANSFER")
    paid_at = models.DateTimeField()

    class Meta:
        ordering = ["paid_at", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive")
        ]

    def __str__(self):
        return f"{self.amount} against {self.invoice.number}"
