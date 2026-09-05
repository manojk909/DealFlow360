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
from decimal import ROUND_DOWN, Decimal

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


# ------------------------------------------------- ADR-016: solving for the approvable discount


def _line_discount_for_given(given_pct, order_discount_pct):
    """Invert `_given_pct`: the line discount that produces `given_pct` after compounding.

    `given = 100(1 - (1 - l/100)(1 - o/100))`, so
    `l = 100(1 - (1 - given/100) / (1 - o/100))`.

    An order discount of 100% leaves the line with no influence at all, so there is no
    line discount to solve for and `None` says so rather than dividing by zero.
    """
    order_factor = ONE - (Decimal(order_discount_pct) / HUNDRED)
    if order_factor <= 0:
        return None
    line_factor = (ONE - (Decimal(given_pct) / HUNDRED)) / order_factor
    return (HUNDRED * (ONE - line_factor)).quantize(CENTS, rounding=ROUND_DOWN)


def headroom_for_line(result, line_id, target_score, order_discount_pct=Decimal("0")):
    """The largest discount this line can carry while the quotation stays at or under
    `target_score`.

    The blended score is a **sum** of per-line overages, so a line's allowance depends on
    what every other line has already spent. That is the whole point of blending, and it
    is why this cannot be answered per line in isolation: three lines each 3 points over
    leave no room for a fourth even though none of them looks alarming alone.

    Returns:
        dict with `reachable`, `max_discount_pct` and `spent_by_others`. `reachable` is
        False when the other lines have already exhausted the target on their own — no
        discount on this line, not even zero, can bring the quotation back.

    Rounding is **down**, always. A suggestion that rounds up by a hundredth is a
    suggestion that gets rejected on submit, which is worse than no suggestion.
    """
    this_line = next((row for row in result.breakdown if row.line_id == line_id), None)
    if this_line is None:
        return {"reachable": False, "max_discount_pct": None, "spent_by_others": None}

    spent_by_others = (result.score - this_line.over_by_pct).quantize(CENTS)
    headroom = Decimal(target_score) - spent_by_others

    if headroom < 0:
        # Even at nothing, the rest of the quotation is already past the target.
        return {
            "reachable": False,
            "max_discount_pct": None,
            "spent_by_others": spent_by_others,
        }

    max_given = this_line.allowed_pct + headroom
    max_line = _line_discount_for_given(min(max_given, HUNDRED), order_discount_pct)
    if max_line is None:
        return {"reachable": False, "max_discount_pct": None, "spent_by_others": spent_by_others}

    return {
        "reachable": True,
        "max_discount_pct": max(Decimal("0.00"), max_line),
        "spent_by_others": spent_by_others,
    }


def approval_bands():
    """The chain's bands, cheapest first, as (label, ceiling score, rule).

    Read from `ApprovalChainRule` rather than hard-coded, so a chain reconfigured in the
    back-end changes the suggestions too. A band whose `score_max` is unbounded in
    practice is still a real band; it simply never constrains anything.
    """
    from core.models import ApprovalChainRule

    bands = []
    for rule in ApprovalChainRule.objects.order_by("score_min"):
        if rule.requires_finance:
            label = "Sales Manager, then Finance"
        elif rule.requires_manager:
            label = "Sales Manager only"
        else:
            label = "Auto-approved"
        bands.append({"label": label, "ceiling": rule.score_max, "rule": rule})
    return bands


def what_would_clear_this(quotation):
    """For a flagged quotation: the discount on each over-ceiling line that would move the
    whole quotation into a cheaper approval band.

    This is the question an approver actually has. The screen already answers *why* a quote
    was flagged; without this it never answers *what would make it approvable*, and the
    manager is left doing the arithmetic on paper — which is exactly the manual step the
    product claims to remove.

    Reads only. Suggests; never applies.

    Returns:
        list of dicts, worst line first, each carrying the line, what it costs today, and
        the discount that would reach each cheaper band.
    """
    result = score_for_quotation(quotation)
    if not result.flagged:
        return []

    bands = approval_bands()
    current = next(
        (
            band
            for band in bands
            if band["rule"].score_min <= result.score <= band["rule"].score_max
        ),
        None,
    )
    cheaper = [
        band
        for band in bands
        if current is None or band["rule"].score_min < current["rule"].score_min
    ]

    lines = {line.pk: line for line in quotation.lines.select_related("product")}
    suggestions = []
    for row in sorted(result.breakdown, key=lambda r: r.over_by_pct, reverse=True):
        if row.over_by_pct <= 0:
            continue
        targets = []
        for band in cheaper:
            headroom = headroom_for_line(
                result, row.line_id, band["ceiling"], quotation.order_discount_pct
            )
            if headroom["reachable"]:
                targets.append(
                    {
                        "label": band["label"],
                        "max_discount_pct": headroom["max_discount_pct"],
                        "spent_by_others": headroom["spent_by_others"],
                    }
                )
        suggestions.append(
            {
                "line": lines.get(row.line_id),
                "risk": row,
                "targets": targets,
                # The cheapest band this line alone can reach, which is what the button offers.
                "best": targets[0] if targets else None,
            }
        )
    return suggestions


def margin_floor_discount(unit_price, cost, order_discount_pct=Decimal("0")):
    """The line discount at which this line sells **at cost** — the walk-away point.

    The ceiling says what policy permits. This says what the business survives. A rep can
    be comfortably inside every ceiling and still be giving the product away, because a
    ceiling is a percentage and margin is a fact about this particular product: 15% off a
    laptop that carries 28% margin is fine, and 15% off a service that carries 12% is
    selling below cost.

    `given` at the floor is `100 x (1 - cost / unit_price)`; the returned figure is the
    **line** discount that produces it once the order-level discount is compounded in, so
    it is directly comparable to the number in the discount box.

    Returns:
        Decimal, rounded **down** so the figure quoted is never below the true floor, or
        `None` when there is no floor to compute — a zero price, or a cost at or above the
        price, in which case any discount at all is under water and the caller should say
        so rather than print a negative percentage.
    """
    unit_price = Decimal(unit_price)
    cost = Decimal(cost)
    if unit_price <= 0 or cost >= unit_price:
        return None

    given_at_floor = HUNDRED * (ONE - (cost / unit_price))
    floor = _line_discount_for_given(given_at_floor, order_discount_pct)
    if floor is None or floor <= 0:
        return None
    return floor


def routing_preview(quotation):
    """What approval this quotation would attract **if it were submitted right now**.

    The rep's screen otherwise only says a line is over its ceiling; it never says what
    that costs them. Knowing before you submit that a discount buys a two-step chain is
    what changes the discount — after the fact it only changes the paperwork.

    Reads only, and routes through the same `approval.required_levels()` a real submit
    uses, so the preview cannot promise one chain and the submit produce another.
    """
    from core.services import approval

    result = score_for_quotation(quotation)
    try:
        requires_manager, requires_finance = approval.required_levels(result.score)
    except Exception:
        # A misconfigured chain must not take the builder down with it; the submit will
        # still refuse loudly, which is where that error belongs.
        return None

    if requires_finance:
        label = "Sales Manager, then Finance"
    elif requires_manager:
        label = "Sales Manager"
    else:
        label = "No approval needed"

    return {
        "score": result.score,
        "label": label,
        "requires_manager": requires_manager,
        "requires_finance": requires_finance,
        "flagged": result.flagged,
    }
