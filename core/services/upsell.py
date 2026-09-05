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
and the margin indicator **immediately**. That is an HTMX swap of the line-items partial,
not a full page reload — which is why `add_to_quotation()` returns the recomputed totals
rather than leaving the caller to ask for them separately.
"""

from dataclasses import dataclass
from decimal import Decimal


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


def suggest(quotation, limit=3, min_margin_pct=None):
    """Ranked suggestions for what to add to this quotation. Reads only.

    Ranking:
      1. Candidates are products co-purchased with something already on the quotation,
         via `ProductPair.co_purchase_count`.
      2. Products with `is_promoted` are lifted above equally-ranked candidates.
      3. Anything already on the quotation is excluded.
      4. Anything whose resulting margin would fall below `min_margin_pct` is dropped.

    With the seeded data the top suggestion for a quotation containing Laptop Pro 14 is
    **Care Plan 2yr** (co-purchase count 42, and promoted), which is what makes DEMO step
    A5 predictable on stage.

    Args:
        quotation: a `core.models.Quotation`.
        limit: maximum suggestions to return.
        min_margin_pct: the configured minimum margin threshold. When `None`, read it
            from configuration rather than defaulting to a number written here — a
            threshold in code is the hardcoding CLAUDE.md forbids.

    Returns:
        list[Suggestion], best first, at most `limit` long.
    """
    raise NotImplementedError("T-19 — upsell and cross-sell panel")


def add_to_quotation(quotation, product, qty=1, discount_pct=Decimal("0")):
    """Add a suggested product as a line and recompute. One transaction.

    Sets `added_via_upsell=True` on the line, so reporting can later show how much
    revenue the panel actually produced. Sets `line_type` and `subscription_plan` from
    the product, which keeps invariant 9 satisfied without the caller thinking about it.

    Returns:
        tuple `(QuotationLine, pricing.QuotationTotals)` — the totals come back with the
        line so the HTMX swap has everything it needs in one round trip (AC-4).
    """
    raise NotImplementedError("T-19 — upsell and cross-sell panel")


def dismiss(quotation, product):
    """Record that a suggestion was dismissed, so it stops being offered.

    Session-scoped rather than persisted: dismissing a suggestion is a statement about
    this editing session, not a permanent fact about the customer, and there is no
    entity in DATA_MODEL.md for it. Kept in the service interface so the panel's Dismiss
    button has somewhere to call.
    """
    raise NotImplementedError("T-19 — upsell and cross-sell panel")
