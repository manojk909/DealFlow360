"""
Quotations and governance.

Owns the quotation, its lines, the discount ceilings and approval chain configuration,
the approval steps, the audit trail and the portal negotiation thread.

**Nothing in this module decides anything.** Ceilings and chain rules are configuration
rows; the score that reads them lives in `core/services/risk.py` and the routing that acts
on them in `core/services/approval.py`. A threshold written into a model default would be
exactly the hardcoding CLAUDE.md forbids.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

PERCENT = {"max_digits": 5, "decimal_places": 2}
MONEY = {"max_digits": 12, "decimal_places": 2}


class CategoryDiscountCeiling(models.Model):
    """
    Per-category ceiling for one tier (FR-06).

    The effective ceiling for a quotation line is `min(tier.max_discount_pct, this)` —
    the stricter always wins (invariant 14). This is the mechanism behind the PDF's Gold
    worked example: Gold allows 15%, but Services are capped at 10%, so an 18% service
    line is 8 points over.

    A tier with no row for a category falls back to the tier ceiling alone.
    """

    tier = models.ForeignKey(
        "core.CustomerTier", on_delete=models.CASCADE, related_name="category_ceilings"
    )
    category = models.ForeignKey(
        "core.Category", on_delete=models.CASCADE, related_name="tier_ceilings"
    )
    max_discount_pct = models.DecimalField(
        **PERCENT, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    class Meta:
        ordering = ["tier__name", "category__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tier", "category"], name="unique_ceiling_per_tier_category"
            ),
            models.CheckConstraint(
                condition=models.Q(max_discount_pct__gte=0)
                & models.Q(max_discount_pct__lte=100),
                name="category_ceiling_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.tier.name} / {self.category.name}: max {self.max_discount_pct}%"


class ApprovalChainRule(models.Model):
    """
    Score band to required approver levels (FR-07). **Configuration, not code.**

    ADR-005 seeds three rows: 0.00 no approval, 0.01-7.99 Manager only,
    8.00+ Manager then Finance. Bands are inclusive at both ends and must tile the whole
    space with no gap and no overlap; a score matching no rule is a configuration error
    and `core/services/approval.py` fails loudly rather than skipping governance.

    Changing a row here changes routing on the next quotation with no code change. That is
    the acceptance test for CLAUDE.md's no-hardcoding rule (BACKLOG T-06).
    """

    score_min = models.DecimalField(max_digits=8, decimal_places=2)
    score_max = models.DecimalField(max_digits=8, decimal_places=2)
    requires_manager = models.BooleanField(default=False)
    requires_finance = models.BooleanField(default=False)

    class Meta:
        ordering = ["score_min"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(score_max__gte=models.F("score_min")),
                name="chain_rule_band_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(score_min__gte=0), name="chain_rule_min_non_negative"
            ),
        ]

    def __str__(self):
        levels = []
        if self.requires_manager:
            levels.append("Manager")
        if self.requires_finance:
            levels.append("Finance")
        return f"{self.score_min}-{self.score_max}: {' then '.join(levels) or 'no approval'}"


class Quotation(models.Model):
    """
    The deal. Stage machine is ADR-010 — one field, ten stages, no second portal-status
    field. What the customer sees in the portal is a display mapping over `stage`.
    """

    class Stage(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
        REJECTED = "REJECTED", "Rejected"
        APPROVED = "APPROVED", "Approved"
        SENT = "SENT", "Sent"
        UNDER_NEGOTIATION = "UNDER_NEGOTIATION", "Under negotiation"
        CONFIRMED = "CONFIRMED", "Confirmed"
        FULFILLED = "FULFILLED", "Fulfilled"
        INVOICED = "INVOICED", "Invoiced"
        PAID = "PAID", "Paid"

    number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey(
        "core.Customer", on_delete=models.PROTECT, related_name="quotations"
    )
    rep = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="quotations")
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.DRAFT)

    order_discount_pct = models.DecimalField(
        **PERCENT, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    # Totals are computed by core/services/pricing.py and stored so the screen shows the
    # number that is in the database. Never summed through a SQLite aggregate (ADR-002).
    subtotal = models.DecimalField(**MONEY, default=0)
    total = models.DecimalField(**MONEY, default=0)
    margin_amount = models.DecimalField(**MONEY, default=0)
    margin_pct = models.DecimalField(**PERCENT, default=0)

    # Snapshotted at submit so the approval screen shows the score the approver acted on,
    # not one recomputed later (DATA_MODEL.md audit requirements, ADR-005).
    risk_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    # Signed TimestampSigner value over the quotation id (ADR-004). Blank until sent.
    portal_token = models.CharField(max_length=255, blank=True, default="", db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    # Drives the stalled-deal detector (BR-8). Updated on every state-changing action —
    # deliberately NOT auto_now, because the dashboard is meaningless if an unrelated
    # write silently refreshes it.
    last_activity_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(order_discount_pct__gte=0)
                & models.Q(order_discount_pct__lte=100),
                name="quotation_order_discount_in_range",
            ),
            models.CheckConstraint(
                condition=models.Q(risk_score__gte=0),
                name="quotation_risk_score_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.number} — {self.customer.name} ({self.get_stage_display()})"


class QuotationLine(models.Model):
    """
    One line. `line_type` is what lets a single order mix one-time and recurring lines
    (BR-5, B7), and invariant 9 is enforced as a database CHECK below: a RECURRING line
    must carry a plan and a ONE_TIME line must not.
    """

    class LineType(models.TextChoices):
        ONE_TIME = "ONE_TIME", "One-time"
        RECURRING = "RECURRING", "Recurring"

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "core.Product", on_delete=models.PROTECT, related_name="quotation_lines"
    )
    variant = models.ForeignKey(
        "core.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_lines",
    )
    qty = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(**MONEY)
    discount_pct = models.DecimalField(
        **PERCENT, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    # Computed by core/services/pricing.py.
    line_total = models.DecimalField(**MONEY, default=0)
    line_cost = models.DecimalField(**MONEY, default=0)

    line_type = models.CharField(
        max_length=16, choices=LineType.choices, default=LineType.ONE_TIME
    )
    subscription_plan = models.ForeignKey(
        "core.SubscriptionPlan",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_lines",
    )
    added_via_upsell = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount_pct__gte=0) & models.Q(discount_pct__lte=100),
                name="quotation_line_discount_in_range",
            ),
            models.CheckConstraint(
                condition=models.Q(qty__gt=0), name="quotation_line_qty_positive"
            ),
            # DATA_MODEL.md invariant 9.
            models.CheckConstraint(
                condition=(
                    models.Q(line_type="RECURRING", subscription_plan__isnull=False)
                    | models.Q(line_type="ONE_TIME", subscription_plan__isnull=True)
                ),
                name="recurring_line_has_plan_one_time_does_not",
            ),
        ]

    def __str__(self):
        return f"{self.qty} x {self.product.name} at -{self.discount_pct}%"


class ApprovalStep(models.Model):
    """
    One reviewer's step. Rows are generated **by the system** from ApprovalChainRule and
    never by a Rep (invariant 3). Finance rows exist only when the chain requires them —
    PDF B4: Finance is "only shown when required".

    `RETURNED` is return-for-revision, a different outcome from `REJECTED`: it sends the
    quotation back to DRAFT, where reject is terminal (ADR-010).
    """

    class Level(models.TextChoices):
        MANAGER = "MANAGER", "Sales Manager"
        FINANCE = "FINANCE", "Finance"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        RETURNED = "RETURNED", "Returned for revision"

    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="approval_steps"
    )
    sequence = models.PositiveSmallIntegerField()
    level = models.CharField(max_length=16, choices=Level.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    actor = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_actions",
    )
    reason = models.TextField(blank=True, default="")
    acted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["quotation_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["quotation", "sequence"], name="unique_step_sequence_per_quotation"
            )
        ]

    def __str__(self):
        return f"{self.quotation.number} step {self.sequence} — {self.level} ({self.status})"


class AuditLog(models.Model):
    """
    BR-3: every approval, rejection and edit logged with user, timestamp and reason.

    `actor` is nullable because portal actions have no User row — a customer is
    authenticated by a token, not an account (ADR-004). Those rows are attributed to the
    quotation's Customer instead.

    Append-only by convention. Nothing in the application updates or deletes a row here.
    """

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="audit_log")
    actor = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=60)
    reason = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.quotation.number}: {self.action}"


class PortalMessage(models.Model):
    """
    The negotiation thread (B8). Covers both the line-level comment tool and the
    counter-discount field, which is why `counter_discount_pct` is nullable: most
    messages are just comments.

    `quotation_line` is nullable because order-level messages exist.

    Append-only: a negotiation history that can be edited is not a negotiation history.
    """

    class Author(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        REP = "REP", "Sales Rep"

    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="portal_messages"
    )
    quotation_line = models.ForeignKey(
        QuotationLine,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="portal_messages",
    )
    author = models.CharField(max_length=16, choices=Author.choices)
    body = models.TextField(blank=True, default="")
    counter_discount_pct = models.DecimalField(
        **PERCENT,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(counter_discount_pct__isnull=True)
                | (
                    models.Q(counter_discount_pct__gte=0)
                    & models.Q(counter_discount_pct__lte=100)
                ),
                name="portal_counter_discount_in_range",
            )
        ]

    def __str__(self):
        return f"{self.quotation.number} <{self.author}>"
