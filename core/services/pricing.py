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
a value is stored. There is no float anywhere in this module, and no `Sum()` over a money
column — SQLite can return a float from one and drift (ADR-002).
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

CENTS = Decimal("0.01")
ONE = Decimal("1")
HUNDRED = Decimal("100")


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


def _money(value):
    """Quantise to two places. The only place rounding happens."""
    return Decimal(value).quantize(CENTS)


def _discount_multiplier(pct):
    """`1 - pct/100`, as a Decimal. A 100% discount gives exactly zero."""
    return ONE - (Decimal(pct) / HUNDRED)


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
    if variant is not None and variant.product_id != product.pk:
        raise ValueError(
            f"Variant {variant.pk} belongs to product {variant.product_id}, not {product.pk}."
        )

    entry = product.price_entries.filter(tier=customer.tier).first()
    price = entry.price if entry is not None else product.list_price

    if variant is not None:
        price = price + variant.extra_price

    return _money(price)


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
    qty = int(qty)
    if qty <= 0:
        raise ValueError(f"Quantity must be positive, got {qty}.")

    discount_pct = Decimal(discount_pct)
    if discount_pct < 0 or discount_pct > HUNDRED:
        raise ValueError(f"Discount must be between 0 and 100, got {discount_pct}.")

    gross = Decimal(qty) * Decimal(unit_price)
    return _money(gross * _discount_multiplier(discount_pct))


def recompute_line(line):
    """Recompute `line.line_total` and `line.line_cost` in place. Does **not** save.

    `line_cost` is `qty * product.cost` and is what makes the margin indicator possible.

    Args:
        line: a `core.models.QuotationLine`.

    Returns:
        The same instance, mutated, so callers can `bulk_update` a batch.
    """
    line.line_total = line_total(line.qty, line.unit_price, line.discount_pct)
    line.line_cost = _money(Decimal(line.qty) * line.product.cost)
    return line


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
    lines = list(quotation.lines.select_related("product").all())

    subtotal = Decimal("0")
    cost = Decimal("0")
    for line in lines:
        recompute_line(line)
        subtotal += line.line_total
        cost += line.line_cost

    subtotal = _money(subtotal)
    total = _money(subtotal * _discount_multiplier(quotation.order_discount_pct))
    margin_amount = _money(total - cost)
    margin_pct = _money(margin_amount / total * HUNDRED) if total > 0 else Decimal("0.00")

    totals = QuotationTotals(
        subtotal=subtotal,
        total=total,
        margin_amount=margin_amount,
        margin_pct=margin_pct,
    )

    if save:
        with transaction.atomic():
            if lines:
                type(lines[0]).objects.bulk_update(lines, ["line_total", "line_cost"])
            quotation.subtotal = totals.subtotal
            quotation.total = totals.total
            quotation.margin_amount = totals.margin_amount
            quotation.margin_pct = totals.margin_pct
            quotation.save(
                update_fields=["subtotal", "total", "margin_amount", "margin_pct"]
            )

    return totals


def margin_after_adding(quotation, product, qty=1, discount_pct=Decimal("0")):
    """Margin percentage the quotation *would* have if this line were added.

    Used by `upsell.py` to show a margin delta on each suggestion (B5) without writing
    anything. Must not mutate `quotation` or touch the database.

    Returns:
        Decimal — the hypothetical `margin_pct`.
    """
    unit_price = resolve_unit_price(product, quotation.customer)

    subtotal = Decimal("0")
    cost = Decimal("0")
    for line in quotation.lines.select_related("product").all():
        subtotal += line_total(line.qty, line.unit_price, line.discount_pct)
        cost += _money(Decimal(line.qty) * line.product.cost)

    subtotal += line_total(qty, unit_price, discount_pct)
    cost += _money(Decimal(qty) * product.cost)

    total = _money(_money(subtotal) * _discount_multiplier(quotation.order_discount_pct))
    if total <= 0:
        return Decimal("0.00")
    return _money((total - cost) / total * HUNDRED)
