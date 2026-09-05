"""
Django admin — **this IS the backend configuration area** (SPEC §4 A2-A7, ADR-001).

Registering the models is the deliberate design, not a shortcut: it gives products, price
lists, discount tiers, category ceilings, approval chains, warehouses, stock and
subscription plans as working CRUD with search, filters and validation, without
hand-writing seven screens. The rep workspace, approval screen, fulfilment screen and
customer portal are hand-built, because leaning on the admin for those would read as
unfinished.

Three groups of models, with deliberately different permissions:

* **Configuration** — tiers, ceilings, chain rules, categories, products, variants, price
  lists, pairs, warehouses, stock, subscription plans, customers. Fully editable. Changing
  a ceiling or a chain rule here changes routing on the next quotation with no code change,
  which is BACKLOG T-06's acceptance test for CLAUDE.md's no-hardcoding rule.

* **Transactional** — quotations, lines, approval steps, invoices. Visible and editable,
  but every field a service owns is read-only: totals, margin, risk score and invoice
  status. Those are computed, and letting someone type over them in the admin would make
  the number on screen stop meaning anything.

* **Append-only or service-owned** — audit log, portal messages, payments, fulfilment
  allocations. Viewable, not editable. An audit trail you can edit is not an audit trail
  (BR-3), a negotiation history you can edit is not a history (B8), and invariant 11 says
  `billing.record_payment()` is the only thing allowed to write a payment.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

# Django >= 5.1: the admin's add form is AdminUserCreationForm — it carries the
# `usable_password` field that add_fieldsets below refers to. UserCreationForm does not.
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from core.models import (
    ApprovalChainRule,
    ApprovalStep,
    AuditLog,
    BillingScheduleEntry,
    Category,
    CategoryDiscountCeiling,
    Customer,
    CustomerTier,
    FulfilmentAllocation,
    Invoice,
    Payment,
    PortalMessage,
    PriceListEntry,
    Product,
    ProductPair,
    ProductVariant,
    Quotation,
    QuotationLine,
    Stock,
    SubscriptionPlan,
    User,
    Warehouse,
)

class ReadOnlyAdmin(admin.ModelAdmin):
    """Viewable, never writable through the admin.

    Used for rows a service owns or that are append-only by design. The restriction is
    on this UI only — the services that legitimately write these rows are unaffected.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --------------------------------------------------------------------- people


class DealFlowUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email", "name", "role")


class DealFlowUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = DealFlowUserCreationForm
    form = DealFlowUserChangeForm
    model = User

    list_display = ("email", "name", "role", "is_active", "is_staff", "created_at")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "name")
    ordering = ("email",)
    readonly_fields = ("created_at", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identity", {"fields": ("name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "role", "usable_password", "password1", "password2"),
            },
        ),
    )


class CategoryCeilingInline(admin.TabularInline):
    """Per-category ceilings, edited on the tier they belong to.

    Having these inline is the point: an admin opens Gold and sees, in one place, that
    Services are capped at 10% even though the tier allows 15%. That pair is the mechanism
    behind the PDF's worked example.
    """

    model = CategoryDiscountCeiling
    extra = 0
    autocomplete_fields = ("category",)


@admin.register(CustomerTier)
class CustomerTierAdmin(admin.ModelAdmin):
    list_display = ("name", "max_discount_pct", "category_ceiling_count", "customer_count")
    search_fields = ("name",)
    ordering = ("max_discount_pct",)
    inlines = (CategoryCeilingInline,)

    @admin.display(description="Category ceilings")
    def category_ceiling_count(self, obj):
        return obj.category_ceilings.count()

    @admin.display(description="Customers")
    def customer_count(self, obj):
        return obj.customers.count()


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "tier", "tier_ceiling", "quotation_count")
    list_filter = ("tier",)
    search_fields = ("name", "email")
    list_select_related = ("tier",)
    autocomplete_fields = ("tier",)

    @admin.display(description="Tier ceiling", ordering="tier__max_discount_pct")
    def tier_ceiling(self, obj):
        return f"{obj.tier.max_discount_pct}%"

    @admin.display(description="Quotations")
    def quotation_count(self, obj):
        return obj.quotations.count()


# --------------------------------------------------------------------- catalogue


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "product_count")
    search_fields = ("name",)

    @admin.display(description="Products")
    def product_count(self, obj):
        return obj.products.count()


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


class PriceListEntryInline(admin.TabularInline):
    model = PriceListEntry
    extra = 0
    autocomplete_fields = ("tier",)


class StockInline(admin.TabularInline):
    """Stock for one product across warehouses, with availability shown."""

    model = Stock
    extra = 0
    autocomplete_fields = ("warehouse",)
    readonly_fields = ("qty_available_display",)

    @admin.display(description="Available")
    def qty_available_display(self, obj):
        return obj.qty_available if obj.pk else "—"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name", "category", "list_price", "cost", "margin_pct_display",
        "unit", "subscription_plan", "is_promoted", "active",
    )
    list_filter = ("category", "is_promoted", "active", "subscription_plan")
    search_fields = ("name", "description")
    list_select_related = ("category", "subscription_plan")
    autocomplete_fields = ("category", "subscription_plan")
    inlines = (ProductVariantInline, PriceListEntryInline, StockInline)

    fieldsets = (
        (None, {"fields": ("name", "category", "description", "active")}),
        ("Money", {
            "fields": ("list_price", "cost", "unit", "tax_pct"),
            "description": (
                "<b>cost</b> is required — the live margin indicator cannot exist without it. "
                "<b>tax_pct</b> is stored but participates in no total and no margin: "
                "ADR-009 item 1 is still an open decision, so rather than invent a tax "
                "treatment the field holds the number the problem statement asks for and the "
                "arithmetic ignores it."
            ),
        }),
        ("Selling", {"fields": ("is_promoted", "subscription_plan")}),
    )

    @admin.display(description="Margin %")
    def margin_pct_display(self, obj):
        """List-price margin, for browsing only. Quotation margin comes from pricing.py."""
        if not obj.list_price:
            return "—"
        return f"{((obj.list_price - obj.cost) / obj.list_price * 100):.1f}%"


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "attribute", "value", "extra_price")
    list_filter = ("attribute", "product__category")
    search_fields = ("product__name", "attribute", "value")
    list_select_related = ("product",)
    autocomplete_fields = ("product",)


@admin.register(PriceListEntry)
class PriceListEntryAdmin(admin.ModelAdmin):
    list_display = ("product", "tier", "price", "currency")
    list_filter = ("tier", "currency", "product__category")
    search_fields = ("product__name", "tier__name")
    list_select_related = ("product", "tier")
    autocomplete_fields = ("product", "tier")


@admin.register(ProductPair)
class ProductPairAdmin(admin.ModelAdmin):
    """Co-purchase history behind the ranked upsell suggestions (A6, B5)."""

    list_display = ("product_a", "product_b", "co_purchase_count")
    list_filter = ("product_a__category", "product_b__category")
    search_fields = ("product_a__name", "product_b__name")
    list_select_related = ("product_a", "product_b")
    autocomplete_fields = ("product_a", "product_b")
    ordering = ("-co_purchase_count",)


# --------------------------------------------------------------------- governance config


@admin.register(CategoryDiscountCeiling)
class CategoryDiscountCeilingAdmin(admin.ModelAdmin):
    """The per-line ceiling in BR-1.

    Effective ceiling for a line is `min(tier ceiling, this)` — the stricter wins
    (invariant 14). Editing a row here changes the risk score of the next quotation, with
    no code change. That is the acceptance test for the no-hardcoding rule.
    """

    list_display = ("tier", "category", "max_discount_pct", "effective_note")
    list_filter = ("tier", "category")
    search_fields = ("tier__name", "category__name")
    list_select_related = ("tier", "category")
    autocomplete_fields = ("tier", "category")

    @admin.display(description="Effective ceiling (stricter of the two)")
    def effective_note(self, obj):
        effective = min(obj.tier.max_discount_pct, obj.max_discount_pct)
        return f"{effective}%  (tier {obj.tier.max_discount_pct}% / category {obj.max_discount_pct}%)"


@admin.register(ApprovalChainRule)
class ApprovalChainRuleAdmin(admin.ModelAdmin):
    """Score band to required approver levels (FR-07). Configuration, not code.

    ADR-005 seeds three rows. Bands are inclusive at both ends and must tile the whole
    space with no gap and no overlap — a score matching no rule is a configuration error
    and `approval.py` fails loudly rather than skipping governance.
    """

    list_display = ("__str__", "score_min", "score_max", "requires_manager", "requires_finance")
    list_filter = ("requires_manager", "requires_finance")
    ordering = ("score_min",)


# --------------------------------------------------------------------- quotations


class QuotationLineInline(admin.TabularInline):
    model = QuotationLine
    extra = 0
    autocomplete_fields = ("product", "variant", "subscription_plan")
    # line_total and line_cost are computed by pricing.py.
    readonly_fields = ("line_total", "line_cost")


class ApprovalStepInline(admin.TabularInline):
    """Steps are generated by the system from ApprovalChainRule, never by a Rep
    (invariant 3), so this inline adds nothing — it is here to be read."""

    model = ApprovalStep
    extra = 0
    can_delete = False
    readonly_fields = ("sequence", "level", "status", "actor", "reason", "acted_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = (
        "number", "customer", "tier_display", "stage", "total",
        "margin_pct", "risk_score", "line_count", "rep", "last_activity_at",
    )
    list_filter = ("stage", "customer__tier", "rep")
    search_fields = ("number", "customer__name", "rep__email", "rep__name")
    list_select_related = ("customer", "customer__tier", "rep")
    autocomplete_fields = ("customer", "rep")
    date_hierarchy = "created_at"
    inlines = (QuotationLineInline, ApprovalStepInline)

    # Every one of these is owned by a service. Typing over them in the admin would make
    # the number on screen stop matching the number the system computed.
    readonly_fields = (
        "subtotal", "total", "margin_amount", "margin_pct",
        "risk_score", "portal_token", "created_at",
    )

    fieldsets = (
        (None, {"fields": ("number", "customer", "rep", "stage")}),
        ("Discount", {"fields": ("order_discount_pct",)}),
        ("Computed by the services layer", {
            "fields": ("subtotal", "total", "margin_amount", "margin_pct", "risk_score"),
            "description": (
                "Read-only. Totals and margin come from <code>core/services/pricing.py</code>; "
                "<b>risk_score</b> is snapshotted by <code>core/services/approval.py</code> at "
                "submit time, so the approval screen shows the score the approver actually "
                "acted on rather than one recomputed later."
            ),
        }),
        ("Portal and activity", {
            "fields": ("portal_token", "created_at", "last_activity_at"),
            "description": (
                "The portal token is a signed, quotation-scoped value (ADR-004) — one token, "
                "one quotation. <b>last_activity_at</b> drives the stalled-deal detector and is "
                "updated by every state-changing action."
            ),
        }),
    )

    @admin.display(description="Tier", ordering="customer__tier__name")
    def tier_display(self, obj):
        return obj.customer.tier.name

    @admin.display(description="Lines")
    def line_count(self, obj):
        return obj.lines.count()


@admin.register(QuotationLine)
class QuotationLineAdmin(admin.ModelAdmin):
    list_display = (
        "quotation", "product", "qty", "unit_price", "discount_pct",
        "line_total", "line_type", "subscription_plan", "added_via_upsell",
    )
    list_filter = ("line_type", "added_via_upsell", "product__category", "quotation__stage")
    search_fields = ("quotation__number", "product__name")
    list_select_related = ("quotation", "product", "subscription_plan")
    autocomplete_fields = ("quotation", "product", "variant", "subscription_plan")
    readonly_fields = ("line_total", "line_cost")


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = ("quotation", "sequence", "level", "status", "actor", "acted_at")
    list_filter = ("level", "status")
    search_fields = ("quotation__number", "actor__email", "reason")
    list_select_related = ("quotation", "actor")
    ordering = ("quotation_id", "sequence")


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    """BR-3. Append-only — an audit trail you can edit is not an audit trail.

    `actor` is empty for portal actions: a customer has no user account (ADR-004), and
    those rows are attributed through the quotation's customer instead.
    """

    list_display = ("created_at", "quotation", "action", "actor", "short_reason")
    list_filter = ("action", "actor")
    search_fields = ("quotation__number", "action", "reason")
    list_select_related = ("quotation", "actor")
    date_hierarchy = "created_at"

    @admin.display(description="Reason")
    def short_reason(self, obj):
        return (obj.reason[:80] + "…") if len(obj.reason) > 80 else obj.reason


@admin.register(PortalMessage)
class PortalMessageAdmin(ReadOnlyAdmin):
    """The negotiation thread (B8). Append-only, for the same reason as the audit log."""

    list_display = ("created_at", "quotation", "author", "quotation_line", "counter_discount_pct", "short_body")
    list_filter = ("author",)
    search_fields = ("quotation__number", "body")
    list_select_related = ("quotation", "quotation_line")
    date_hierarchy = "created_at"

    @admin.display(description="Message")
    def short_body(self, obj):
        return (obj.body[:60] + "…") if len(obj.body) > 60 else obj.body


# --------------------------------------------------------------------- inventory


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    """`shipping_cost_weight` is what ADR-006's split ranks on — lower ships first.

    Changing it here changes the suggested split on the next fulfilment, with no code
    change. Replenishment rules (A4) are not modelled: ADR-009 item 3 is still open and
    the problem statement never defines what a replenishment rule does.
    """

    list_display = ("name", "shipping_cost_weight", "stock_line_count", "units_on_hand")
    search_fields = ("name",)
    ordering = ("shipping_cost_weight",)

    @admin.display(description="Products stocked")
    def stock_line_count(self, obj):
        return obj.stock_rows.count()

    @admin.display(description="Units on hand")
    def units_on_hand(self, obj):
        return sum(row.qty_on_hand for row in obj.stock_rows.all())


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("product", "warehouse", "qty_on_hand", "qty_reserved", "qty_available_display")
    list_filter = ("warehouse", "product__category")
    search_fields = ("product__name", "warehouse__name")
    list_select_related = ("product", "warehouse")
    autocomplete_fields = ("product", "warehouse")

    @admin.display(description="Available", ordering="qty_on_hand")
    def qty_available_display(self, obj):
        return obj.qty_available


@admin.register(FulfilmentAllocation)
class FulfilmentAllocationAdmin(ReadOnlyAdmin):
    """Written by `core/services/fulfilment.py`, which reserves stock in the same
    transaction. Editing a row here would move an allocation without moving the
    reservation behind it."""

    list_display = ("quotation", "quotation_line", "warehouse", "qty", "is_backorder", "is_manual_override", "created_at")
    list_filter = ("warehouse", "is_backorder", "is_manual_override")
    search_fields = ("quotation__number", "quotation_line__product__name")
    list_select_related = ("quotation", "quotation_line", "warehouse")


# --------------------------------------------------------------------- billing


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    """A5 recurring plan. P0 because AC-1 requires a subscription plan to persist.

    `proration_method` and `cancellation_policy` read UNDECIDED on purpose: ADR-008 is
    still an open decision, and a made-up value here would read as a decision nobody took.
    """

    list_display = ("name", "interval", "product_count", "proration_method", "cancellation_policy")
    list_filter = ("interval",)
    search_fields = ("name",)

    @admin.display(description="Products on this plan")
    def product_count(self, obj):
        return obj.products.count()


@admin.register(BillingScheduleEntry)
class BillingScheduleEntryAdmin(admin.ModelAdmin):
    """Recurring lines bill through these rows, never through the one-time invoice
    (invariant 10). Generated by `core/services/billing.py` at T-20."""

    list_display = ("quotation", "quotation_line", "due_date", "amount", "status", "is_proration_adjustment")
    list_filter = ("status", "is_proration_adjustment")
    search_fields = ("quotation__number",)
    list_select_related = ("quotation", "quotation_line")
    date_hierarchy = "due_date"


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """One-time lines only (invariant 10).

    **`status` is read-only.** Invariant 11 says it is derived from the sum of payments and
    never set by hand; `billing.record_payment()` is the only thing allowed to move it.
    SQLite cannot enforce that as a CHECK constraint, so this is where the rule is visible.
    """

    list_display = ("number", "quotation", "amount", "status", "amount_paid", "issue_date", "due_date", "is_credit_note")
    list_filter = ("status", "is_credit_note")
    search_fields = ("number", "quotation__number")
    list_select_related = ("quotation",)
    date_hierarchy = "issue_date"
    readonly_fields = ("status",)
    inlines = ()

    @admin.display(description="Paid so far")
    def amount_paid(self, obj):
        # Summed in Python, never through a SQLite aggregate over a money column (ADR-002).
        total = sum((p.amount for p in obj.payments.all()), start=type(obj.amount)("0"))
        return total


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    """Read-only by design.

    Invariant 11 — the sum of payments never exceeds the invoice amount — cannot be a
    SQLite CHECK constraint, so `billing.record_payment()` enforces it and is the only
    permitted writer. Adding a payment through the admin would route around that check.
    """

    list_display = ("invoice", "amount", "method", "paid_at")
    list_filter = ("method",)
    search_fields = ("invoice__number", "invoice__quotation__number")
    list_select_related = ("invoice",)
    date_hierarchy = "paid_at"
