"""
What a customer currently owns — ADR-013.

Every mature quote-to-cash platform has this entity, and it is the hinge the whole
right-hand side of the lifecycle turns on. Renewals, amendments, cancellations, churn and
MRR are all questions about *what is owned right now*, and none of them can be answered
from quotations alone: a quotation records what was agreed on a day, an asset records what
is true today.

Without it the system can say "Acme signed a quote in March". With it the system can say
"Acme owns three Care Plans, worth ₹1,440 a month, expiring on 14 October" — which is the
question a renewals conversation actually starts from.

**Assets are created by the system, never by hand.** `assets.create_from_confirmation()`
runs when an order is confirmed, from the same hook that builds the billing schedule, so
an asset cannot exist for something nobody bought.
"""

from django.db import models


class Asset(models.Model):
    """One product a customer owns, as of now.

    A recurring line becomes an asset with a term and an MRR contribution; a one-time line
    becomes an asset with no end date, because owning a laptop does not expire. Both are
    kept: "what does this customer own" is not a subscription-only question.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RENEWED = "RENEWED", "Renewed"
        CANCELLED = "CANCELLED", "Cancelled"
        EXPIRED = "EXPIRED", "Expired"

    customer = models.ForeignKey(
        "core.Customer", on_delete=models.PROTECT, related_name="assets"
    )
    product = models.ForeignKey(
        "core.Product", on_delete=models.PROTECT, related_name="assets"
    )
    # Where it came from. PROTECT, because an asset without its origin cannot be audited.
    source_line = models.ForeignKey(
        "core.QuotationLine", on_delete=models.PROTECT, related_name="assets"
    )
    quotation = models.ForeignKey(
        "core.Quotation", on_delete=models.PROTECT, related_name="assets"
    )

    qty = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    start_date = models.DateField()
    # Null for a one-time purchase: owning hardware does not expire. Set for a recurring
    # line, and it is what `due_for_renewal()` reads.
    end_date = models.DateField(null=True, blank=True)

    # Monthly recurring revenue this asset contributes, normalised to a month whatever the
    # plan's interval, so quarterly and annual plans are comparable without a conversion
    # at every call site. Zero for a one-time asset.
    mrr = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Set when a renewal quotation is raised from this asset, so the same asset cannot be
    # renewed twice and the chain is traceable.
    renewed_into = models.ForeignKey(
        "core.Quotation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="renewed_assets",
    )
    cancelled_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["customer__name", "product__name", "-start_date"]
        indexes = [
            # "What does this customer own" — the question the detail screen asks.
            models.Index(fields=["customer", "status"], name="asset_customer_status_idx"),
            # The renewals queue: active assets expiring inside a window.
            models.Index(fields=["status", "end_date"], name="asset_status_end_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(qty__gte=1), name="asset_qty_at_least_one"
            ),
            models.CheckConstraint(
                condition=models.Q(mrr__gte=0), name="asset_mrr_non_negative"
            ),
            # One asset per quotation line: a line is bought once.
            models.UniqueConstraint(fields=["source_line"], name="unique_asset_per_line"),
        ]

    def __str__(self):
        return f"{self.customer.name}: {self.qty} x {self.product.name}"

    @property
    def is_recurring(self):
        return self.end_date is not None
