"""
Upsell and cross-sell suggestions — BR-7.

Implements FR-28 (B5). Owned by **T-19**.

SPEC marks the panel SHOULD because its *configuration screen* (PDF A6) is explicitly
Optional — but the panel itself appears in the PDF's own acceptance test as AC-4, so it
is built as P1 rather than P2. That reading is recorded in DECISIONS.md rather than
assumed here.

Ranking, per BR-7: co-purchase history first, promoted products lifted, and **only
suggestions above the configured minimum margin threshold surface**. A suggestion that
would damage the deal's margin is not a suggestion.

AC-4 is the acceptance test that matters: adding a suggestion must update the order total
and the margin indicator **immediately**. The panel is rendered inside the builder's live
region, so adding one swaps the lines, the totals, the margin and the remaining
suggestions in a single exchange — not a full page reload.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

# ADR-011. A placeholder for the A6 configuration row that does not exist yet, named
# once so it is visible and trivial to replace. Every caller may override it, and T-27
# will read a real row and pass it in. This is NOT a business rule hidden in code — see
# the ADR for why it is treated differently from ceilings, bands and shipping weights.
DEFAULT_MIN_MARGIN_PCT = Decimal("15")

# How much a promoted product is boosted in the ranking. Stated as a multiplier so the
# rule stays explainable: "ranked by how often they are bought together, with promoted
# products given a 50% boost."
PROMOTED_BOOST = Decimal("1.5")


@dataclass(frozen=True)
class Suggestion:
    """One ranked suggestion, as the panel renders it (B5).

    `margin_delta_pct` is the quotation's margin percentage **after** adding this line
    minus its margin now — computed through `pricing.margin_after_adding()` so the panel
    and the indicator cannot disagree.

    `promotion_tag` is non-empty only for promoted products, and is what the panel shows
    as the promotion badge.
    """

    product_id: int
    name: str
    category: str
    unit_price: Decimal
    margin_delta_pct: Decimal
    co_purchase_count: int
    promotion_tag: str
    rank_reason: str


def _candidates(quotation):
    """Products co-purchased with something already on the quotation, either direction.

    `ProductPair` is stored one-directionally, so both columns are consulted; a pairing
    seeded only as A-to-B still suggests B when A is on the quote.
    """
    from core.models import ProductPair

    on_quote = set(quotation.lines.values_list("product_id", flat=True))
    if not on_quote:
        return {}

    counts = {}
    pairs = ProductPair.objects.filter(product_a_id__in=on_quote).select_related(
        "product_b__category", "product_b__subscription_plan"
    ).prefetch_related("product_b__price_entries")
    for pair in pairs:
        counts[pair.product_b] = max(
            counts.get(pair.product_b, 0), pair.co_purchase_count
        )

    pairs = ProductPair.objects.filter(product_b_id__in=on_quote).select_related(
        "product_a__category", "product_a__subscription_plan"
    ).prefetch_related("product_a__price_entries")
    for pair in pairs:
        counts[pair.product_a] = max(
            counts.get(pair.product_a, 0), pair.co_purchase_count
        )

    # Never suggest something already on the quotation, or a retired product.
    return {
        product: count
        for product, count in counts.items()
        if product.pk not in on_quote and product.active
    }


def suggest(quotation, limit=3, min_margin_pct=None, exclude_product_ids=()):
    """Ranked suggestions for what to add to this quotation. Reads only.

    Ranking:
      1. Candidates are products co-purchased with something already on the quotation,
         via `ProductPair.co_purchase_count`.
      2. Products with `is_promoted` are boosted by `PROMOTED_BOOST`.
      3. Anything already on the quotation, dismissed, or inactive is excluded.
      4. Any product whose OWN margin is below `min_margin_pct` is dropped — the rule is
         about the health of the thing being suggested, not the size of the order it
         lands on.

    With the seeded data the top suggestion for a quotation containing Laptop Pro 14 is
    **Care Plan 2yr** (co-purchase count 42, and promoted), which is what makes DEMO step
    A5 predictable on stage.

    Args:
        quotation: a `core.models.Quotation`.
        limit: maximum suggestions to return.
        min_margin_pct: the minimum margin a suggested product must itself carry. `None` uses
            `DEFAULT_MIN_MARGIN_PCT` — see ADR-011 for why that is a constant today.
        exclude_product_ids: products the rep has dismissed this session.

    Returns:
        list[Suggestion], best first, at most `limit` long.
    """
    from core.services import pricing

    threshold = DEFAULT_MIN_MARGIN_PCT if min_margin_pct is None else Decimal(min_margin_pct)
    dismissed = {int(pk) for pk in exclude_product_ids}
    current_margin = quotation.margin_pct

    scored = []
    for product, count in _candidates(quotation).items():
        if product.pk in dismissed:
            continue

        # BR-7: the threshold is about the SUGGESTED PRODUCT'S OWN margin, not the
        # margin the order is left with. Testing the order margin does not work: on a
        # quotation dominated by one large line, adding a thin item barely moves the
        # total and would sail through, which is exactly the case the rule exists to
        # stop. We do not suggest products that are themselves unhealthy.
        if product.list_price <= 0:
            continue
        product_margin_pct = (
            (product.list_price - product.cost) / product.list_price * Decimal("100")
        )
        if product_margin_pct < threshold:
            continue

        projected = pricing.margin_after_adding(quotation, product, qty=1)

        rank = Decimal(count) * (PROMOTED_BOOST if product.is_promoted else Decimal("1"))
        reason = f"bought together {count} times"
        if product.is_promoted:
            reason += ", promoted"

        scored.append(
            (
                rank,
                Suggestion(
                    product_id=product.pk,
                    name=product.name,
                    category=product.category.name,
                    unit_price=pricing.resolve_unit_price(product, quotation.customer),
                    margin_delta_pct=(projected - current_margin).quantize(Decimal("0.01")),
                    co_purchase_count=count,
                    promotion_tag="Promoted" if product.is_promoted else "",
                    rank_reason=reason,
                ),
            )
        )

    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [suggestion for _, suggestion in scored[:limit]]


def add_to_quotation(quotation, product, qty=1, discount_pct=Decimal("0")):
    """Add a suggested product as a line and recompute. One transaction.

    Sets `added_via_upsell=True` on the line, so reporting can later show how much
    revenue the panel actually produced. Sets `line_type` and `subscription_plan` from
    the product, which keeps invariant 9 satisfied without the caller thinking about it.

    Returns:
        tuple `(QuotationLine, pricing.QuotationTotals)` — the totals come back with the
        line so the HTMX swap has everything it needs in one round trip (AC-4).
    """
    from core.models import QuotationLine
    from core.services import pricing

    recurring = product.subscription_plan is not None
    with transaction.atomic():
        line = QuotationLine.objects.create(
            quotation=quotation,
            product=product,
            qty=qty,
            unit_price=pricing.resolve_unit_price(product, quotation.customer),
            discount_pct=Decimal(discount_pct),
            line_type=(
                QuotationLine.LineType.RECURRING if recurring
                else QuotationLine.LineType.ONE_TIME
            ),
            subscription_plan=product.subscription_plan if recurring else None,
            added_via_upsell=True,
        )
        totals = pricing.recompute_quotation(quotation)
    return line, totals


def dismiss(session, product_id):
    """Record that a suggestion was dismissed, so it stops being offered.

    **Session-scoped rather than persisted**, and the signature says so: dismissing a
    suggestion is a statement about this editing session, not a permanent fact about the
    customer, and there is no entity in DATA_MODEL.md for it. The contract originally
    took `(quotation, product)`; it takes the session instead because that is where the
    state honestly belongs.

    Returns:
        The updated list of dismissed product ids.
    """
    dismissed = list(session.get("upsell_dismissed", []))
    if int(product_id) not in dismissed:
        dismissed.append(int(product_id))
    session["upsell_dismissed"] = dismissed
    return dismissed
