"""
Catalogue — what we sell.

Owns products, categories, variants and price lists (ARCHITECTURE.md domain table).
It must not touch quotation state.
"""

from django.core.validators import MinValueValidator
from django.db import models


class Category(models.Model):
    """Hardware / Services / Subscriptions, per PDF B3."""

    name = models.CharField(max_length=80, unique=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    DATA_MODEL.md: name, category, list_price, cost, unit, tax_pct, description,
    is_promoted, active.

    `cost` is not in the PDF's field list for A2 but is required: the live margin
    indicator (B3, AC-4) cannot exist without it.

    `tax_pct` is stored and configurable but participates in **nothing** — no total, no
    margin. ADR-009 item 1 is still open, so rather than invent a tax treatment the field
    holds the number the PDF asks for and the arithmetic ignores it. Said plainly here so
    nobody assumes otherwise.
    """

    name = models.CharField(max_length=160, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    list_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    unit = models.CharField(max_length=24, default="unit")
    tax_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    description = models.TextField(blank=True, default="")

    # Ranks higher in upsell suggestions (PDF A6 / B5).
    is_promoted = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    # A product sold on a recurring plan. Nullable: most products are one-time.
    subscription_plan = models.ForeignKey(
        "core.SubscriptionPlan",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="products",
    )

    class Meta:
        ordering = ["category__name", "name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(list_price__gte=0), name="product_list_price_non_negative"),
            models.CheckConstraint(condition=models.Q(cost__gte=0), name="product_cost_non_negative"),
            models.CheckConstraint(
                condition=models.Q(tax_pct__gte=0) & models.Q(tax_pct__lte=100),
                name="product_tax_pct_in_range",
            ),
        ]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    """SHOULD (FR-26 / T-25). Attribute, value and an extra price on top of the product."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    attribute = models.CharField(max_length=60)
    value = models.CharField(max_length=60)
    extra_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["product__name", "attribute", "value"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "attribute", "value"], name="unique_variant_per_product"
            )
        ]

    def __str__(self):
        return f"{self.product.name} — {self.attribute}: {self.value}"


class PriceListEntry(models.Model):
    """Customer-tier-based pricing (A2 / FR-04). Currency is single-valued for now."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="price_entries")
    tier = models.ForeignKey("core.CustomerTier", on_delete=models.CASCADE, related_name="price_entries")
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default="EUR")

    class Meta:
        verbose_name_plural = "price list entries"
        ordering = ["product__name", "tier__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "tier", "currency"], name="unique_price_per_product_tier_currency"
            ),
            models.CheckConstraint(condition=models.Q(price__gte=0), name="price_list_price_non_negative"),
        ]

    def __str__(self):
        return f"{self.product.name} @ {self.tier.name}: {self.price} {self.currency}"


class ProductPair(models.Model):
    """
    SHOULD (T-19). Co-purchase history behind the ranked upsell suggestions (A6 / B5).

    Stored one-directionally: seed and update both directions if a pairing should suggest
    in both. Kept dumb on purpose — the ranking rule lives in `core/services/upsell.py`.
    """

    product_a = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="pairs_as_a")
    product_b = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="pairs_as_b")
    co_purchase_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-co_purchase_count"]
        constraints = [
            models.UniqueConstraint(fields=["product_a", "product_b"], name="unique_product_pair"),
            models.CheckConstraint(
                condition=~models.Q(product_a=models.F("product_b")), name="product_pair_not_self"
            ),
        ]

    def __str__(self):
        return f"{self.product_a.name} + {self.product_b.name} ({self.co_purchase_count})"
