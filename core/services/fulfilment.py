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
broken. Note the distinction: a product that *has* stock rows but insufficient quantity
does get a backorder row. Only a product with no stock rows anywhere is skipped.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

CENTS = Decimal("0.01")


class InsufficientStock(Exception):
    """A requested allocation exceeds what is available in that warehouse right now."""


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

    @property
    def has_backorder(self):
        return any(self.backorder_qty_by_line.values())


def available_qty(product, warehouse):
    """`qty_on_hand - qty_reserved` for one product in one warehouse.

    Zero when no `Stock` row exists. The one definition of "available" — nothing else in
    the codebase may subtract those two fields itself.
    """
    from core.models import Stock

    row = Stock.objects.filter(product=product, warehouse=warehouse).first()
    return 0 if row is None else row.qty_on_hand - row.qty_reserved


def _ranked_stock(product):
    """Stock rows holding `product`, cheapest warehouse first. Fully deterministic.

    Ascending shipping weight, then descending available quantity, then ascending
    warehouse id — so two warehouses on the same weight never reorder between requests.
    """
    from core.models import Stock

    rows = list(
        Stock.objects.filter(product=product).select_related("warehouse")
    )
    return sorted(
        rows,
        key=lambda row: (
            row.warehouse.shipping_cost_weight,
            -(row.qty_on_hand - row.qty_reserved),
            row.warehouse_id,
        ),
    )


def suggest_split_for_line(line):
    """Allocations for one line, by the rule at the top of this module. Reads only.

    Solved per line, independently. Across a multi-line order the shipment count is
    therefore not globally optimal — two lines could each pick a different cheapest
    warehouse where one warehouse could have covered both. That is a known and documented
    limitation of the heuristic (ADR-006), not a defect to be quietly fixed.

    Args:
        line: a `core.models.QuotationLine`.

    Returns:
        list[Allocation]. **Empty when the product has no stock rows anywhere** — that
        line is skipped, not backordered.
    """
    rows = _ranked_stock(line.product)
    if not rows:
        return []  # Not stocked anywhere. Skipped, deliberately — see the module note.

    cheapest = rows[0]
    remaining = line.qty
    allocations = []

    # Single-shipment shortcut: never fragment a line the cheapest warehouse could have
    # shipped on its own.
    if (cheapest.qty_on_hand - cheapest.qty_reserved) >= remaining:
        return [
            Allocation(
                quotation_line_id=line.pk,
                warehouse_id=cheapest.warehouse_id,
                warehouse_name=cheapest.warehouse.name,
                qty=remaining,
                is_backorder=False,
            )
        ]

    for row in rows:
        if remaining <= 0:
            break
        take = min(remaining, row.qty_on_hand - row.qty_reserved)
        if take <= 0:
            continue
        allocations.append(
            Allocation(
                quotation_line_id=line.pk,
                warehouse_id=row.warehouse_id,
                warehouse_name=row.warehouse.name,
                qty=take,
                is_backorder=False,
            )
        )
        remaining -= take

    if remaining > 0:
        # Backordered against the cheapest warehouse — the one it is most likely to be
        # replenished into. A shortfall exists as a row, never as a missing quantity.
        allocations.append(
            Allocation(
                quotation_line_id=line.pk,
                warehouse_id=cheapest.warehouse_id,
                warehouse_name=cheapest.warehouse.name,
                qty=remaining,
                is_backorder=True,
            )
        )
    return allocations


def _summarise(allocations, skipped_line_ids):
    from core.models import Warehouse

    weights = {w.pk: w.shipping_cost_weight for w in Warehouse.objects.all()}

    shipping_from = {a.warehouse_id for a in allocations if not a.is_backorder}
    cost = Decimal("0")
    backorders = {}
    for allocation in allocations:
        if allocation.is_backorder:
            backorders[allocation.quotation_line_id] = (
                backorders.get(allocation.quotation_line_id, 0) + allocation.qty
            )
        else:
            cost += Decimal(allocation.qty) * weights[allocation.warehouse_id]

    return SplitSuggestion(
        allocations=allocations,
        shipment_count=len(shipping_from),
        estimated_cost=cost.quantize(CENTS),
        backorder_qty_by_line=backorders,
        skipped_line_ids=skipped_line_ids,
    )


def suggest_split(quotation):
    """The whole quotation's suggested split. Reads only — writes nothing.

    Returns:
        SplitSuggestion.
    """
    allocations = []
    skipped = []
    for line in quotation.lines.select_related("product").all():
        line_allocations = suggest_split_for_line(line)
        if not line_allocations:
            skipped.append(line.pk)
        allocations.extend(line_allocations)
    return _summarise(allocations, skipped)


def _reserve(allocations, actor_note=""):
    """Write allocation rows and increment reservations. Caller supplies the transaction.

    Re-checks availability immediately before each reservation: stock can move between
    the page load and the click, and reserving against stale numbers is how invariant 7
    gets violated.
    """
    from core.models import QuotationLine, Stock

    product_by_line = dict(
        QuotationLine.objects.filter(
            pk__in={a.quotation_line_id for a in allocations}
        ).values_list("pk", "product_id")
    )

    for allocation in allocations:
        if allocation.is_backorder:
            continue
        row = Stock.objects.filter(
            product_id=product_by_line[allocation.quotation_line_id],
            warehouse_id=allocation.warehouse_id,
        ).first()
        if row is None or (row.qty_on_hand - row.qty_reserved) < allocation.qty:
            available = 0 if row is None else row.qty_on_hand - row.qty_reserved
            raise InsufficientStock(
                f"{allocation.warehouse_name} has {available} available but the plan "
                f"reserves {allocation.qty}. Stock moved since the split was suggested."
            )
        row.qty_reserved += allocation.qty
        row.save(update_fields=["qty_reserved"])


def accept_split(quotation, actor, suggestion=None):
    """Persist a split and reserve the stock. One transaction, or nothing.

    **Recomputes the suggestion at commit time** rather than trusting the one rendered on
    screen — stock may have moved between the page load and the click.

    Stage handling follows ADR-010. Flow A has no customer in it, so a rep accepting the
    split is also the confirmation: from APPROVED this writes CONFIRMED and then FULFILLED
    in the same transaction, with an audit row for each, so the trail shows both events
    rather than one compound jump. From CONFIRMED (the portal route, T-15) it just moves
    to FULFILLED.

    Args:
        quotation: a `core.models.Quotation` in APPROVED or CONFIRMED.
        actor: the acting `core.models.User`.
        suggestion: optional; ignored for the allocation decision and used only to detect
            that the screen was showing something different, which is worth telling the
            user about rather than silently overriding.

    Returns:
        SplitSuggestion — what was actually committed.

    Raises:
        ValueError: if the quotation is not in a stage that can be fulfilled.
        InsufficientStock: if availability changed underneath.
    """
    from core.models import FulfilmentAllocation, Quotation
    from core.services import approval

    allowed = {Quotation.Stage.APPROVED, Quotation.Stage.CONFIRMED}
    if quotation.stage not in allowed:
        raise ValueError(
            f"A quotation in {quotation.stage} cannot be fulfilled; expected one of "
            f"{sorted(allowed)}."
        )

    with transaction.atomic():
        committed = suggest_split(quotation)

        if suggestion is not None and suggestion.allocations != committed.allocations:
            # Not an error — stock moved. Recorded so the difference is visible.
            approval.record(
                quotation,
                action="SPLIT_RECOMPUTED",
                actor=actor,
                reason="Stock changed between the split being shown and accepted; the "
                       "committed plan is the one computed at accept time.",
            )

        FulfilmentAllocation.objects.filter(quotation=quotation).delete()
        FulfilmentAllocation.objects.bulk_create(
            [
                FulfilmentAllocation(
                    quotation=quotation,
                    quotation_line_id=a.quotation_line_id,
                    warehouse_id=a.warehouse_id,
                    qty=a.qty,
                    is_backorder=a.is_backorder,
                )
                for a in committed.allocations
            ]
        )
        _reserve(committed.allocations)

        if quotation.stage == Quotation.Stage.APPROVED:
            quotation.stage = Quotation.Stage.CONFIRMED
            quotation.save(update_fields=["stage"])
            approval.record(
                quotation,
                action="ORDER_CONFIRMED",
                actor=actor,
                reason="Rep confirmed the order alongside accepting the warehouse split.",
            )

        quotation.stage = Quotation.Stage.FULFILLED
        quotation.last_activity_at = timezone.now()
        quotation.save(update_fields=["stage", "last_activity_at"])

        approval.record(
            quotation,
            action="SPLIT_ACCEPTED",
            actor=actor,
            reason=(
                f"{committed.shipment_count} shipment(s), estimated cost "
                f"{committed.estimated_cost}."
            ),
            payload={
                "shipment_count": committed.shipment_count,
                "estimated_cost": str(committed.estimated_cost),
                "allocations": [
                    {
                        "line": a.quotation_line_id,
                        "warehouse": a.warehouse_name,
                        "qty": a.qty,
                        "backorder": a.is_backorder,
                    }
                    for a in committed.allocations
                ],
                "skipped_lines": committed.skipped_line_ids,
            },
        )
    return committed


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
    from core.models import FulfilmentAllocation, Warehouse
    from core.services import approval

    pairs = [(int(w), int(q)) for w, q in allocations if int(q) > 0]
    total = sum(q for _, q in pairs)
    if total > line.qty:
        raise ValueError(
            f"Override allocates {total} units but the line is only {line.qty} "
            f"(invariant 6)."
        )

    warehouses = {w.pk: w for w in Warehouse.objects.filter(pk__in=[w for w, _ in pairs])}
    for warehouse_id, qty in pairs:
        warehouse = warehouses.get(warehouse_id)
        if warehouse is None:
            raise ValueError(f"Warehouse {warehouse_id} does not exist.")
        if available_qty(line.product, warehouse) < qty:
            raise InsufficientStock(
                f"{warehouse.name} has {available_qty(line.product, warehouse)} "
                f"available; the override asks for {qty}."
            )

    with transaction.atomic():
        FulfilmentAllocation.objects.filter(quotation_line=line).delete()
        rows = FulfilmentAllocation.objects.bulk_create(
            [
                FulfilmentAllocation(
                    quotation=line.quotation,
                    quotation_line=line,
                    warehouse_id=warehouse_id,
                    qty=qty,
                    is_manual_override=True,
                )
                for warehouse_id, qty in pairs
            ]
            + (
                [
                    FulfilmentAllocation(
                        quotation=line.quotation,
                        quotation_line=line,
                        warehouse_id=pairs[0][0] if pairs else None,
                        qty=line.qty - total,
                        is_backorder=True,
                        is_manual_override=True,
                    )
                ]
                if total < line.qty and pairs
                else []
            )
        )
        approval.record(
            line.quotation,
            action="SPLIT_MANUAL_OVERRIDE",
            actor=actor,
            reason=f"Manual split for {line.product.name}: "
                   + ", ".join(f"{q} from {warehouses[w].name}" for w, q in pairs),
        )
    return rows


def consolidate_backorder(line, actor):
    """Re-run the split against a line's outstanding backorder quantity. FR-35, T-24.

    The "Consolidate Remaining Backorder" prompt appears automatically when stock arrives
    for a backordered line; accepting calls this. It reuses `suggest_split_for_line()`
    against the remaining quantity rather than implementing a second rule.

    Returns:
        list[Allocation] — what the remaining quantity can now be filled from.
    """
    raise NotImplementedError("T-24 — consolidate remaining backorder")
