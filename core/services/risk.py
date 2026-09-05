"""
Blended discount risk score — BR-1, ADR-005. **The heart of the product.**

Implements FR-12. Owned by **T-09**.

> The blended risk score is the total number of discount percentage points given away
> above ceiling across the whole quotation, where every line is measured against the
> stricter of its customer tier's ceiling and its category's.

`core/tests/test_risk.py` asserts both worked examples from PDF §10 against the signatures
below. **Those tests are the specification.** They were written before this module and
must not be edited to match it. If the arithmetic here has to change, ADR-005 changes
first, in writing, with a reason.

Two functions, deliberately:

* `score_quotation()` is **pure** — plain dicts and Decimals in, a result object out. No
  ORM, no database. That is what makes the specification tests runnable without fixtures.
* `score_for_quotation()` is the thin ORM adapter that loads the configuration rows for a
  real quotation and calls the pure function. Everything in the application calls this one.

The routing bands that turn a score into approver levels are **not here**. They are
`ApprovalChainRule` rows and `approval.py` reads them. Nothing in this module knows the
number 8.
"""

from dataclasses import dataclass
from decimal import Decimal

CENTS = Decimal("0.01")
ONE = Decimal("1")
HUNDRED = Decimal("100")


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

    @property
    def is_over(self):
        """True when this line contributed to the score. Convenience for templates."""
        return self.over_by_pct > 0


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

    @property
    def offending_lines(self):
        """Only the lines that went over — what the approval screen leads with."""
        return [line for line in self.breakdown if line.is_over]


def effective_ceiling(tier_max_discount_pct, category_ceiling_pct):
    """`min()` of the two, treating `None` as "no category ceiling configured".

    Exposed on its own because the builder shows a per-line ceiling hint while the rep is
    typing, and that hint must come from the same function the score uses.
    """
    tier = Decimal(tier_max_discount_pct)
    if category_ceiling_pct is None:
        return tier
    return min(tier, Decimal(category_ceiling_pct))


def _given_pct(line_discount_pct, order_discount_pct):
    """The real discount on a line once the order-level discount is compounded in.

    Two successive discounts do not add — 10% then 5% is 14.5%, not 15% — so they are
    combined multiplicatively rather than summed.
    """
    line_factor = ONE - (Decimal(line_discount_pct) / HUNDRED)
    order_factor = ONE - (Decimal(order_discount_pct) / HUNDRED)
    return HUNDRED * (ONE - line_factor * order_factor)


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
    breakdown = []
    score = Decimal("0")

    for line in lines:
        category = line.get("category")
        given = _given_pct(line["discount_pct"], order_discount_pct)
        allowed = effective_ceiling(tier_max_discount_pct, category_ceilings.get(category))
        over_by = max(Decimal("0"), given - allowed)

        score += over_by
        breakdown.append(
            RiskLine(
                line_id=line.get("line_id"),
                label=line.get("label", ""),
                category=category,
                given_pct=given,
                allowed_pct=allowed,
                over_by_pct=over_by,
            )
        )

    score = score.quantize(CENTS)
    return RiskResult(score=score, flagged=score > 0, breakdown=breakdown)


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
    # Imported here rather than at module level so `score_quotation` above stays usable
    # as plain Python, with no Django import chain behind it.
    from core.models import CategoryDiscountCeiling

    tier = quotation.customer.tier
    ceilings = {
        row.category.name: row.max_discount_pct
        for row in CategoryDiscountCeiling.objects.filter(tier=tier).select_related("category")
    }

    lines = [
        {
            "line_id": line.pk,
            "label": line.product.name,
            "category": line.product.category.name,
            "discount_pct": line.discount_pct,
        }
        for line in quotation.lines.select_related("product__category").all()
    ]

    return score_quotation(
        lines=lines,
        tier_max_discount_pct=tier.max_discount_pct,
        category_ceilings=ceilings,
        order_discount_pct=quotation.order_discount_pct,
    )
