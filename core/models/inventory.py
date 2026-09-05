"""
Inventory — warehouses, stock and fulfilment allocations.

Owns stock reality. Must not touch quotation pricing (ARCHITECTURE.md domain table).

The split rule that reads these rows is ADR-006 and lives in
`core/services/fulfilment.py`. Nothing here decides where anything ships from.
"""

from django.core.validators import MinValueValidator
from django.db import models


class Warehouse(models.Model):
    """
    PDF examples: "Main Warehouse", "East Depot".

    `shipping_cost_weight` is the number ADR-006's heuristic ranks on — lower is cheaper.
    It is configuration: changing it in the admin changes the suggested split on the next
    fulfilment with no code change.

    Replenishment rules (A4) are **not modelled**. ADR-009 item 3 is still open and the
    PDF never defines what a replenishment rule does. T-31 owns it. Recorded as absent
    rather than half-built.
    """

    name = models.CharField(max_length=120, unique=True)
    shipping_cost_weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1,
        validators=[MinValueValidator(0)],
        help_text="Relative cost of shipping one unit from here. Lower ships first (ADR-006).",
    )

    class Meta:
        ordering = ["shipping_cost_weight", "name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(shipping_cost_weight__gte=0),
                name="warehouse_shipping_weight_non_negative",
            )
        ]

    def __str__(self):
        return f"{self.name} (weight {self.shipping_cost_weight})"


class Stock(models.Model):
    """
    One product in one warehouse. Available = `qty_on_hand - qty_reserved`.

    Two invariants are enforced here at database level rather than in a form:
    unique on (product, warehouse), and invariant 8 — reserved never exceeds on-hand.
    """

    product = models.ForeignKey("core.Product", on_delete=models.CASCADE, related_name="stock_rows")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stock_rows")
    qty_on_hand = models.PositiveIntegerField(default=0)
    qty_reserved = models.PositiveIntegerField(default=0)
    # ADR-009 item 3. PDF A4 says "replenishment rules per warehouse" without saying what
    # a rule does, so it is a reorder point: available below this flags the row for
    # restock. Display-only — nothing auto-orders, which would need a supplier model.
    reorder_point = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "stock"
        ordering = ["warehouse__name", "product__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse"], name="unique_stock_per_product_warehouse"
            ),
            # DATA_MODEL.md invariant 8.
            models.CheckConstraint(
                condition=models.Q(qty_reserved__lte=models.F("qty_on_hand")),
                name="stock_reserved_not_over_on_hand",
            ),
        ]

    @property
    def qty_available(self):
        """Read-only convenience for the admin and templates. The split reads it too."""
        return self.qty_on_hand - self.qty_reserved

    def __str__(self):
        return f"{self.product.name} @ {self.warehouse.name}: {self.qty_available} available"


class FulfilmentAllocation(models.Model):
    """
    One decision about where part of a line ships from.

    Shipment count for a quotation = distinct warehouses across its non-backorder
    allocations (BR-4, ADR-006). A shortfall exists as a row with `is_backorder = True`
    rather than as a silently missing quantity (invariant 6).
    """

    quotation = models.ForeignKey(
        "core.Quotation", on_delete=models.CASCADE, related_name="allocations"
    )
    quotation_line = models.ForeignKey(
        "core.QuotationLine", on_delete=models.CASCADE, related_name="allocations"
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="allocations"
    )
    qty = models.PositiveIntegerField()
    is_backorder = models.BooleanField(default=False)
    is_manual_override = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["quotation_line_id", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(qty__gt=0), name="fulfilment_allocation_qty_positive"
            )
        ]

    def __str__(self):
        suffix = " [backorder]" if self.is_backorder else ""
        return f"{self.qty} from {self.warehouse.name}{suffix}"
