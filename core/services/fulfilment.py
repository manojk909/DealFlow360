"""
Warehouse split and backorders — BR-4, ADR-006.

Implements FR-17, FR-18, FR-19 and FR-35. Owned by **T-16** (T-24 for consolidation).

The rule, and it is **a heuristic — say so on the screen too**:

> Fill each line from the cheapest warehouse first and spill into the next cheapest,
> except that if the cheapest warehouse can cover the whole line by itself it ships
> alone; whatever is left over becomes a backorder.

Ranking is by ascending `shipping_cost_weight`, tie-broken by descending available
quantity, then by ascending warehouse id, so the suggestion is deterministic and
reproducible on stage.

The split is computed from **live** stock every time it is requested. Never cached and
never seeded — a hardcoded split would fail PDF §7's "real application logic" requirement
outright.

Invariants this module owns: 6 (allocations per line never exceed the line quantity, and
any shortfall exists as a backorder row), 7 (no allocation exceeds available stock at
allocation time), 8 (`qty_reserved` never exceeds `qty_on_hand`).

**Lines for non-stocked products are skipped, not backordered.** Services and
Subscriptions have no `Stock` rows at all — correctly, since you do not warehouse an
engagement — and reporting them as a total backorder makes the fulfilment screen look
broken. See the note in BACKLOG T-16.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Allocation:
    """One proposed movement: this much of this line, out of this warehouse."""

    quotation_line_id: int
    warehouse_id: int
    warehouse_name: str
    qty: int
    is_backorder: bool


@dataclass(frozen=True)
class SplitSuggestion:
    """What the fulfilment screen renders (B6): warehouse, qty, shipments, cost.

    `shipment_count` is the number of **distinct warehouses across non-backorder
    allocations** — a backorder is not a shipment.

    `estimated_cost` is `sum(qty * warehouse.shipping_cost_weight)` as a Decimal. It is
    displayed because it is the answer to "why not one shipment from East Depot?": for
    the seeded demo order that plan costs 8.40 against this one's 6.80.

    `skipped_line_ids` are lines with no stock rows anywhere — services and
    subscriptions. Surfaced rather than hidden, so the screen can say so.
    """

    allocations: list
    shipment_count: int
    estimated_cost: Decimal
    backorder_qty_by_line: dict
    skipped_line_ids: list


def available_qty(product, warehouse):
    """`qty_on_hand - qty_reserved` for one product in one warehouse.

    Zero when no `Stock` row exists. The one definition of "available" — nothing else in
    the codebase may subtract those two fields itself.
    """
    raise NotImplementedError("T-16 — warehouse split and backorders")


def suggest_split_for_line(line):
    """Allocations for one line, by the rule at the top of this module. Reads only.

    Solved per line, independently. Across a multi-line order the shipment count is
    therefore not globally optimal — two lines could each pick a different cheapest
    warehouse where one warehouse could have covered both. That is a known and documented
    limitation of the heuristic (ADR-006), not a defect to be quietly fixed.

    Args:
        line: a `core.models.QuotationLine`.

    Returns:
        list[Allocation]. Empty when the product has no stock rows anywhere.
    """
    raise NotImplementedError("T-16 — warehouse split and backorders")


def suggest_split(quotation):
    """The whole quotation's suggested split. Reads only — writes nothing.

    Returns:
        SplitSuggestion.
    """
    raise NotImplementedError("T-16 — warehouse split and backorders")


def accept_split(quotation, actor, suggestion=None):
    """Persist a split and reserve the stock. One transaction, or nothing.

    Re-computes the suggestion at commit time rather than trusting the one rendered on
    screen — stock may have moved between the page load and the click, and reserving
    against stale numbers is how invariant 7 gets violated.

    Writes `FulfilmentAllocation` rows, increments `Stock.qty_reserved`, moves the
    quotation to FULFILLED, writes an audit row and touches `last_activity_at`.

    Args:
        quotation: a `core.models.Quotation` in CONFIRMED.
        actor: the acting `core.models.User`.
        suggestion: optional; ignored for the allocation decision and used only to detect
            that the screen was showing something different, which is worth telling the
            user about rather than silently overriding.

    Returns:
        SplitSuggestion — what was actually committed.

    Raises:
        ValueError: if the quotation is not in a stage that can be fulfilled.
        InsufficientStock: if availability changed such that a reservation would exceed
            what is on hand.
    """
    raise NotImplementedError("T-16 — warehouse split and backorders")


def apply_manual_override(line, allocations, actor):
    """Replace one line's allocations wholesale with a manual plan.

    Re-validated against the same availability rule as the suggestion — an override that
    exceeds available stock is **rejected by the service**, not prevented by hiding the
    control. Rows are written with `is_manual_override=True` so the audit trail shows a
    human overrode the heuristic.

    Args:
        line: a `core.models.QuotationLine`.
        allocations: iterable of `(warehouse_id, qty)` pairs.
        actor: the acting `core.models.User`.

    Returns:
        list of created `FulfilmentAllocation` rows.

    Raises:
        InsufficientStock: if any warehouse cannot cover its requested quantity.
        ValueError: if the quantities sum to more than the line quantity.
    """
    raise NotImplementedError("T-16 — warehouse split and backorders")


def consolidate_backorder(line, actor):
    """Re-run the split against a line's outstanding backorder quantity. FR-35, T-24.

    The "Consolidate Remaining Backorder" prompt appears automatically when stock arrives
    for a backordered line; accepting calls this. It reuses `suggest_split_for_line()`
    against the remaining quantity rather than implementing a second rule.

    Returns:
        list[Allocation] — what the remaining quantity can now be filled from.
    """
    raise NotImplementedError("T-24 — consolidate remaining backorder")


class InsufficientStock(Exception):
    """A requested allocation exceeds what is available in that warehouse right now."""
