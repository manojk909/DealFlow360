"""Tests for the warehouse split (T-16, ADR-006).

Two of these are load-bearing for the demo and are named so nobody trims them:

* `test_the_seeded_demo_case_splits_four_plus_two_at_cost_680`
* `test_a_line_with_no_stock_rows_anywhere_is_skipped_not_backordered`

Builds its own warehouses and stock — independent of `seed_demo`.
"""

from decimal import Decimal

from django.test import TestCase

from core.models import (
    Category,
    Customer,
    CustomerTier,
    FulfilmentAllocation,
    Product,
    Quotation,
    QuotationLine,
    Role,
    Stock,
    SubscriptionPlan,
    User,
    Warehouse,
)
from core.services import fulfilment


class FulfilmentTestCase(TestCase):
    def setUp(self):
        tier = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        self.customer = Customer.objects.create(name="Acme", email="a@a.test", tier=tier)
        self.rep = User.objects.create_user(
            email="rep@f.test", password="x", name="Rep", role=Role.REP
        )
        self.hardware = Category.objects.create(name="Hardware")
        self.services = Category.objects.create(name="Services")

        self.main = Warehouse.objects.create(
            name="Main Warehouse", shipping_cost_weight=Decimal("1.00")
        )
        self.east = Warehouse.objects.create(
            name="East Depot", shipping_cost_weight=Decimal("1.40")
        )

        self.laptop = Product.objects.create(
            name="Laptop Pro 14", category=self.hardware,
            list_price=Decimal("1450"), cost=Decimal("1050"),
        )
        # The service is genuinely not stocked anywhere — you do not warehouse an
        # engagement. No Stock rows are created for it, on purpose.
        self.setup = Product.objects.create(
            name="Onsite Setup Service", category=self.services,
            list_price=Decimal("600"), cost=Decimal("330"),
        )

        Stock.objects.create(product=self.laptop, warehouse=self.main, qty_on_hand=4)
        Stock.objects.create(product=self.laptop, warehouse=self.east, qty_on_hand=10)

        self.quotation = Quotation.objects.create(
            number="Q-F-1", customer=self.customer, rep=self.rep,
            stage=Quotation.Stage.APPROVED,
            last_activity_at="2026-09-05T10:00:00Z",
        )

    def add_line(self, product, qty):
        return QuotationLine.objects.create(
            quotation=self.quotation, product=product, qty=qty,
            unit_price=product.list_price, discount_pct=Decimal("0"),
        )


class SplitRuleTests(FulfilmentTestCase):

    def test_the_seeded_demo_case_splits_four_plus_two_at_cost_680(self):
        """DEMO A10 and ADR-006, exactly.

        Main is cheapest (1.00 against 1.40) but holds only 4 of the 6, so the
        single-shipment shortcut cannot fire: 4 from Main, 2 from East. Two shipments,
        4 x 1.00 + 2 x 1.40 = 6.80.

        The rejected alternative is one shipment of 6 from East Depot, which is one
        FEWER shipment but costs 6 x 1.40 = 8.40. This test pins the cheaper plan.
        """
        line = self.add_line(self.laptop, 6)
        suggestion = fulfilment.suggest_split(self.quotation)

        plan = [(a.warehouse_name, a.qty, a.is_backorder) for a in suggestion.allocations]
        self.assertEqual([("Main Warehouse", 4, False), ("East Depot", 2, False)], plan)
        self.assertEqual(2, suggestion.shipment_count)
        self.assertEqual(Decimal("6.80"), suggestion.estimated_cost)
        self.assertFalse(suggestion.has_backorder)

        single_shipment_from_east = Decimal(6) * self.east.shipping_cost_weight
        self.assertEqual(Decimal("8.40"), single_shipment_from_east)
        self.assertLess(suggestion.estimated_cost, single_shipment_from_east)

    def test_a_line_with_no_stock_rows_anywhere_is_skipped_not_backordered(self):
        """Services are not warehoused. Reporting them as a backorder looks broken."""
        laptop_line = self.add_line(self.laptop, 2)
        service_line = self.add_line(self.setup, 1)

        suggestion = fulfilment.suggest_split(self.quotation)

        self.assertEqual([service_line.pk], suggestion.skipped_line_ids)
        self.assertEqual({}, suggestion.backorder_qty_by_line)
        self.assertFalse(suggestion.has_backorder)
        self.assertEqual(
            [laptop_line.pk], [a.quotation_line_id for a in suggestion.allocations]
        )

    def test_a_stocked_product_that_is_short_DOES_get_a_backorder(self):
        """The distinction that matters: short stock is a backorder, no stock is a skip."""
        line = self.add_line(self.laptop, 20)
        suggestion = fulfilment.suggest_split(self.quotation)

        self.assertEqual([], suggestion.skipped_line_ids)
        self.assertTrue(suggestion.has_backorder)
        self.assertEqual({line.pk: 6}, suggestion.backorder_qty_by_line)
        self.assertEqual(2, suggestion.shipment_count)
        # 4 + 10 shipped, 6 backordered — invariant 6: nothing is silently missing.
        self.assertEqual(20, sum(a.qty for a in suggestion.allocations))

    def test_single_shipment_shortcut_avoids_fragmenting_a_line(self):
        self.add_line(self.laptop, 3)
        suggestion = fulfilment.suggest_split(self.quotation)

        self.assertEqual(1, suggestion.shipment_count)
        self.assertEqual(1, len(suggestion.allocations))
        self.assertEqual("Main Warehouse", suggestion.allocations[0].warehouse_name)
        self.assertEqual(Decimal("3.00"), suggestion.estimated_cost)

    def test_reserved_stock_is_not_available(self):
        Stock.objects.filter(product=self.laptop, warehouse=self.main).update(qty_reserved=4)
        self.add_line(self.laptop, 6)
        suggestion = fulfilment.suggest_split(self.quotation)

        # Main has 4 on hand but all reserved, so everything comes from East.
        self.assertEqual(
            [("East Depot", 6, False)],
            [(a.warehouse_name, a.qty, a.is_backorder) for a in suggestion.allocations],
        )

    def test_ranking_is_deterministic_when_weights_tie(self):
        tied = Warehouse.objects.create(name="West Depot", shipping_cost_weight=Decimal("1.00"))
        Stock.objects.create(product=self.laptop, warehouse=tied, qty_on_hand=2)
        self.add_line(self.laptop, 6)

        first = fulfilment.suggest_split(self.quotation).allocations
        second = fulfilment.suggest_split(self.quotation).allocations
        self.assertEqual(first, second)
        # Same weight, so the one with more available goes first: Main has 4, West has 2.
        self.assertEqual("Main Warehouse", first[0].warehouse_name)

    def test_available_qty_is_zero_when_no_stock_row_exists(self):
        self.assertEqual(0, fulfilment.available_qty(self.setup, self.main))

    def test_suggest_split_writes_nothing(self):
        self.add_line(self.laptop, 6)
        fulfilment.suggest_split(self.quotation)
        self.assertEqual(0, FulfilmentAllocation.objects.count())
        self.assertEqual(
            0, Stock.objects.get(product=self.laptop, warehouse=self.main).qty_reserved
        )


class AcceptSplitTests(FulfilmentTestCase):

    def test_accepting_reserves_stock_and_moves_the_stage(self):
        self.add_line(self.laptop, 6)
        committed = fulfilment.accept_split(self.quotation, self.rep)
        self.quotation.refresh_from_db()

        self.assertEqual(Quotation.Stage.FULFILLED, self.quotation.stage)
        self.assertEqual(Decimal("6.80"), committed.estimated_cost)
        self.assertEqual(
            4, Stock.objects.get(product=self.laptop, warehouse=self.main).qty_reserved
        )
        self.assertEqual(
            2, Stock.objects.get(product=self.laptop, warehouse=self.east).qty_reserved
        )
        self.assertEqual(2, FulfilmentAllocation.objects.filter(quotation=self.quotation).count())

    def test_invariant_8_reserved_never_exceeds_on_hand(self):
        self.add_line(self.laptop, 6)
        fulfilment.accept_split(self.quotation, self.rep)
        for row in Stock.objects.all():
            self.assertLessEqual(row.qty_reserved, row.qty_on_hand)

    def test_accepting_from_approved_records_both_confirm_and_split(self):
        self.add_line(self.laptop, 2)
        fulfilment.accept_split(self.quotation, self.rep)
        actions = list(self.quotation.audit_log.values_list("action", flat=True))
        self.assertIn("ORDER_CONFIRMED", actions)
        self.assertIn("SPLIT_ACCEPTED", actions)

    def test_a_draft_cannot_be_fulfilled(self):
        self.quotation.stage = Quotation.Stage.DRAFT
        self.quotation.save(update_fields=["stage"])
        self.add_line(self.laptop, 1)
        with self.assertRaises(ValueError):
            fulfilment.accept_split(self.quotation, self.rep)

    def test_backorder_rows_are_written_but_reserve_nothing(self):
        self.add_line(self.laptop, 20)
        fulfilment.accept_split(self.quotation, self.rep)

        backorders = FulfilmentAllocation.objects.filter(is_backorder=True)
        self.assertEqual(1, backorders.count())
        self.assertEqual(6, backorders.first().qty)
        # 14 real units reserved, not 20 — a backorder is a promise, not a reservation.
        total_reserved = sum(Stock.objects.values_list("qty_reserved", flat=True))
        self.assertEqual(14, total_reserved)


class ManualOverrideTests(FulfilmentTestCase):

    def test_override_is_recorded_and_replaces_the_suggestion(self):
        line = self.add_line(self.laptop, 4)
        rows = fulfilment.apply_manual_override(line, [(self.east.pk, 4)], self.rep)

        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0].is_manual_override)
        self.assertEqual(self.east.pk, rows[0].warehouse_id)
        self.assertIn(
            "SPLIT_MANUAL_OVERRIDE",
            list(self.quotation.audit_log.values_list("action", flat=True)),
        )

    def test_an_override_beyond_available_stock_is_refused_by_the_service(self):
        line = self.add_line(self.laptop, 6)
        with self.assertRaises(fulfilment.InsufficientStock):
            fulfilment.apply_manual_override(line, [(self.main.pk, 6)], self.rep)
        self.assertEqual(0, FulfilmentAllocation.objects.count())

    def test_an_override_exceeding_the_line_quantity_is_refused(self):
        line = self.add_line(self.laptop, 2)
        with self.assertRaises(ValueError):
            fulfilment.apply_manual_override(
                line, [(self.main.pk, 2), (self.east.pk, 3)], self.rep
            )

    def test_a_partial_override_leaves_the_remainder_as_a_backorder(self):
        line = self.add_line(self.laptop, 6)
        fulfilment.apply_manual_override(line, [(self.main.pk, 4)], self.rep)

        rows = FulfilmentAllocation.objects.filter(quotation_line=line)
        self.assertEqual(2, rows.count())
        self.assertEqual(2, rows.get(is_backorder=True).qty)
