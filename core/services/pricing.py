"""
Pricing — line totals, order totals, margin and price-list resolution.

Implements FR-10 (arithmetic) and FR-11 (live margin). Owned by **T-08**.

Domain boundary: pricing owns money on a quotation. It does not know about stock,
approvals or billing schedules. Governance asks pricing for numbers; it never recomputes
them itself.

**The server is the single source of truth for totals.** The number rendered on screen is
the number stored on the row, so a template never recomputes a total that a service also
computes. This is what stops the margin indicator and the database disagreeing on stage.

Every function here is `Decimal` in, `Decimal` out, quantised to two places at the point
a value is stored. Do not introduce a float anywhere in this module.

When this lands, delete `_totals()` from `core/management/commands/seed_demo.py` and call
`recompute_quotation()` there instead — the seed carries a provisional copy of this
arithmetic and two implementations of one formula is debt.
"""

from dataclasses import dataclass
from decimal import Decimal

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class QuotationTotals:
    """What a quotation's money looks like after a recompute.

    `margin_pct` is margin as a percentage of `total`, and is `Decimal("0.00")` when
    `total` is zero — an empty draft has no margin rather than an undefined one.
    """

    subtotal: Decimal
    total: Decimal
    margin_amount: Decimal
    margin_pct: Decimal


def resolve_unit_price(product, customer, variant=None):
    """Price for one unit of `product` sold to `customer`, before any discount.

    Resolution order (FR-04): the `PriceListEntry` for the customer's tier if one exists,
    otherwise `product.list_price`. A variant's `extra_price` is added on top of whichever
    was chosen — a variant surcharge is not tier-specific.

    Args:
        product: a `core.models.Product`.
        customer: a `core.models.Customer`; its `tier` selects the price list row.
        variant: optional `core.models.ProductVariant` belonging to `product`.

    Returns:
        Decimal quantised to two places.

    Raises:
        ValueError: if `variant` is given and does not belong to `product`.
    """
    raise NotImplementedError("T-08 — pricing and live margin engine")


def line_total(qty, unit_price, discount_pct):
    """`qty * unit_price * (1 - discount_pct/100)`, quantised to two places.

    The single definition of a line's money. DATA_MODEL.md's calculated-fields table
    points here, and nothing else in the codebase may restate this formula.

    Args:
        qty: positive int.
        unit_price: Decimal.
        discount_pct: Decimal between 0 and 100 inclusive.

    Returns:
        Decimal.

    Raises:
        ValueError: if `discount_pct` is outside 0-100 or `qty` is not positive. The
            database also refuses both (see the CHECK constraints on QuotationLine); this
            check exists so a caller gets a useful error before it reaches SQLite.
    """
    raise NotImplementedError("T-08 — pricing and live margin engine")


def recompute_line(line):
    """Recompute `line.line_total` and `line.line_cost` in place. Does **not** save.

    `line_cost` is `qty * product.cost` and is what makes the margin indicator possible.

    Args:
        line: a `core.models.QuotationLine`.

    Returns:
        The same instance, mutated, so callers can `bulk_update` a batch.
    """
    raise NotImplementedError("T-08 — pricing and live margin engine")


def recompute_quotation(quotation, save=True):
    """Recompute every line, then the quotation's totals and margin.

    Order-level discount applies to the **sum of already-discounted line totals**, not to
    the gross — line discounts first, then the order discount (FR-10).

    Called on every edit in the builder, which is what makes the margin indicator live
    (AC-4). Runs inside `transaction.atomic()` when `save` is True, because the lines and
    the header must not disagree even briefly.

    Args:
        quotation: a `core.models.Quotation`.
        save: when True, persist the lines and the quotation header.

    Returns:
        QuotationTotals.
    """
    raise NotImplementedError("T-08 — pricing and live margin engine")


def margin_after_adding(quotation, product, qty=1, discount_pct=Decimal("0")):
    """Margin percentage the quotation *would* have if this line were added.

    Used by `upsell.py` to show a margin delta on each suggestion (B5) without writing
    anything. Must not mutate `quotation` or touch the database.

    Returns:
        Decimal — the hypothetical `margin_pct`.
    """
    raise NotImplementedError("T-08 — pricing and live margin engine")
