"""
Blended discount risk score — BR-1, ADR-005. **The heart of the product.**

Implements FR-12. Owned by **T-09**.

> The blended risk score is the total number of discount percentage points given away
> above ceiling across the whole quotation, where every line is measured against the
> stricter of its customer tier's ceiling and its category's.

`core/tests/test_risk.py` already asserts both worked examples from PDF §10 against the
signatures below. **Those tests are the specification.** Make them pass; do not edit them
to match whatever this module turns out to compute. If the arithmetic here has to change,
ADR-005 changes first, in writing, with a reason.

Two functions, deliberately:

* `score_quotation()` is **pure** — plain dicts and Decimals in, a result object out. No
  ORM, no database. That is what makes the specification tests runnable without fixtures.
* `score_for_quotation()` is the thin ORM adapter that loads the configuration rows for a
  real quotation and calls the pure function. Everything in the application calls this one.

The routing bands that turn a score into approver levels are **not here**. They are
`ApprovalChainRule` rows and `approval.py` reads them.
"""

from dataclasses import dataclass
from decimal import Decimal

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class RiskLine:
    """One line's contribution, as the approval screen must display it (FR-14).

    `given_pct` is the line discount **combined with any order-level discount** —
    `100 * (1 - (1 - line/100) * (1 - order/100))` — because an order discount is a real
    discount on every line and is scored as one.

    `allowed_pct` is `min(tier ceiling, category ceiling)`: the stricter always wins
    (DATA_MODEL.md invariant 14). A category with no ceiling row falls back to the tier
    ceiling alone.

    `over_by_pct` is `max(0, given - allowed)`. There is no credit for being under.
    """

    line_id: int
    label: str
    category: str
    given_pct: Decimal
    allowed_pct: Decimal
    over_by_pct: Decimal


@dataclass(frozen=True)
class RiskResult:
    """The score, whether it flags, and the breakdown that explains it.

    `breakdown` is in the same order as the input lines. It is not optional: the approval
    screen cannot justify the number without it, and a score a judge cannot check by hand
    is a score they will not believe.
    """

    score: Decimal
    flagged: bool
    breakdown: list


def score_quotation(lines, tier_max_discount_pct, category_ceilings,
                    order_discount_pct=Decimal("0")):
    """Blended risk score for a set of lines. Pure — no database, no ORM objects.

    Args:
        lines: iterable of dicts with keys `line_id`, `label`, `category`,
            `discount_pct` (Decimal).
        tier_max_discount_pct: Decimal — `CustomerTier.max_discount_pct`.
        category_ceilings: dict mapping category name to Decimal, already resolved for
            this customer's tier. A missing key means no category ceiling applies.
        order_discount_pct: Decimal — `Quotation.order_discount_pct`.

    Returns:
        RiskResult. `score` is the sum of every line's `over_by_pct`, quantised to 0.01.
        `flagged` is `score > 0` — any overage at all requires approval, which is what
        makes DATA_MODEL.md invariant 2 meaningful.

    An empty `lines` gives `score == Decimal("0.00")` and `flagged is False`. That is
    correct and is why the seeded empty Acme draft scores zero.
    """
    raise NotImplementedError("T-09 — blended discount risk score")


def score_for_quotation(quotation):
    """Load the configuration rows for a real quotation and score it.

    Reads `quotation.customer.tier.max_discount_pct` and the `CategoryDiscountCeiling`
    rows for that tier, then delegates to `score_quotation()`. Reads only; storing the
    result on `Quotation.risk_score` is the caller's job, and `approval.py` does it at
    submit time so the approval screen shows the score the approver acted on.

    Args:
        quotation: a `core.models.Quotation`.

    Returns:
        RiskResult.
    """
    raise NotImplementedError("T-09 — blended discount risk score")


def effective_ceiling(tier_max_discount_pct, category_ceiling_pct):
    """`min()` of the two, treating `None` as "no category ceiling configured".

    Exposed on its own because the builder shows a per-line ceiling hint while the rep is
    typing, and that hint must come from the same function the score uses.
    """
    raise NotImplementedError("T-09 — blended discount risk score")
