"""ADR-017 — the two bounds: the policy ceiling and the economic floor.

A ceiling is a percentage; margin is a fact about a particular product. A rep can sit
comfortably inside every ceiling and still sell below cost, because 15% off a laptop
carrying 28% margin is fine and 15% off a service carrying 12% is not. The ceiling is
already enforced. This adds the other bound and, on the rep's own screen, tells them what
a discount will cost them in approvals *before* they submit — which is the only moment at
which that knowledge can still change the discount.
"""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ApprovalChainRule, Category, CategoryDiscountCeiling, Customer, CustomerTier,
    Product, Quotation, QuotationLine, Role, User,
)
from core.services import pricing, risk


class MarginFloorTests(TestCase):
    """`margin_floor_discount` is pure arithmetic — no database needed."""

    def test_the_floor_is_the_discount_that_sells_at_cost(self):
        # 1000 list, 600 cost -> 40% off leaves exactly cost.
        self.assertEqual(
            Decimal("40.00"), risk.margin_floor_discount(Decimal("1000"), Decimal("600"))
        )

    def test_a_thin_margin_gives_a_low_floor(self):
        """The point of the feature: a 12%-margin line cannot take a 15% discount."""
        floor = risk.margin_floor_discount(Decimal("1000"), Decimal("880"))
        self.assertEqual(Decimal("12.00"), floor)
        self.assertLess(floor, Decimal("15"))

    def test_the_order_discount_is_compounded_in(self):
        """The figure must be comparable to the number in the line's discount box."""
        plain = risk.margin_floor_discount(Decimal("1000"), Decimal("600"))
        with_order = risk.margin_floor_discount(
            Decimal("1000"), Decimal("600"), order_discount_pct=Decimal("10")
        )
        self.assertLess(with_order, plain)

    def test_a_line_already_at_or_below_cost_has_no_floor_to_quote(self):
        """Better to say "none" than to print a negative percentage."""
        self.assertIsNone(risk.margin_floor_discount(Decimal("500"), Decimal("500")))
        self.assertIsNone(risk.margin_floor_discount(Decimal("500"), Decimal("700")))

    def test_a_zero_price_has_no_floor(self):
        self.assertIsNone(risk.margin_floor_discount(Decimal("0"), Decimal("0")))

    def test_it_rounds_down_so_the_quoted_floor_is_never_optimistic(self):
        floor = risk.margin_floor_discount(Decimal("999"), Decimal("777"))
        at_floor = Decimal("999") * (Decimal("1") - floor / Decimal("100"))
        self.assertGreaterEqual(at_floor, Decimal("777"))


class RoutingPreviewTests(TestCase):
    def setUp(self):
        gold = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        hardware = Category.objects.create(name="Hardware")
        services = Category.objects.create(name="Services")
        CategoryDiscountCeiling.objects.create(
            tier=gold, category=hardware, max_discount_pct=Decimal("15")
        )
        CategoryDiscountCeiling.objects.create(
            tier=gold, category=services, max_discount_pct=Decimal("10")
        )
        ApprovalChainRule.objects.create(score_min=Decimal("0"), score_max=Decimal("0"))
        ApprovalChainRule.objects.create(
            score_min=Decimal("0.01"), score_max=Decimal("8.00"), requires_manager=True
        )
        ApprovalChainRule.objects.create(
            score_min=Decimal("8.01"), score_max=Decimal("9999"),
            requires_manager=True, requires_finance=True,
        )
        customer = Customer.objects.create(name="Acme", email="a@a.test", tier=gold)
        self.rep = User.objects.create_user(
            email="rep@fl.test", password="x", name="Rep", role=Role.REP
        )
        self.setup = Product.objects.create(
            name="Setup", category=services,
            list_price=Decimal("1000"), cost=Decimal("500"),
        )
        self.quotation = Quotation.objects.create(
            number="Q-FL-1", customer=customer, rep=self.rep,
            last_activity_at=timezone.now(),
        )

    def add(self, discount):
        line = QuotationLine.objects.create(
            quotation=self.quotation, product=self.setup, qty=1,
            unit_price=Decimal("1000"), discount_pct=Decimal(discount),
        )
        pricing.recompute_quotation(self.quotation)
        return line

    def test_a_clean_quotation_previews_no_approval(self):
        self.add("5")
        self.assertEqual("No approval needed", risk.routing_preview(self.quotation)["label"])

    def test_a_small_overage_previews_the_manager(self):
        self.add("14")  # 4 over a 10% ceiling
        self.assertEqual("Sales Manager", risk.routing_preview(self.quotation)["label"])

    def test_a_large_overage_previews_both_levels(self):
        self.add("25")  # 15 over
        preview = risk.routing_preview(self.quotation)
        self.assertEqual("Sales Manager, then Finance", preview["label"])
        self.assertTrue(preview["requires_finance"])

    def test_the_preview_agrees_with_what_a_real_submit_would_route(self):
        """A preview that promises one chain and a submit that produces another is a lie."""
        from core.services import approval

        self.add("25")
        preview = risk.routing_preview(self.quotation)
        manager, finance = approval.required_levels(
            risk.score_for_quotation(self.quotation).score
        )
        self.assertEqual(manager, preview["requires_manager"])
        self.assertEqual(finance, preview["requires_finance"])


class BuilderScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def setUp(self):
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(User.objects.get(email="rep@dealflow.test"))

    def test_the_builder_shows_the_routing_a_submit_would_produce(self):
        draft = Quotation.objects.filter(stage=Quotation.Stage.DRAFT).first()
        laptop = Product.objects.get(name="Laptop Pro 14")
        QuotationLine.objects.create(
            quotation=draft, product=laptop, qty=1,
            unit_price=pricing.resolve_unit_price(laptop, draft.customer),
            discount_pct=Decimal("30"),
        )
        response = self.client.get(reverse("core:quotation_builder", args=[draft.pk]))
        self.assertIsNotNone(response.context["routing"])
        self.assertTrue(response.context["routing"]["flagged"])
        self.assertIn("If submitted now", response.content.decode())

    def test_every_line_carries_a_floor(self):
        draft = Quotation.objects.filter(stage=Quotation.Stage.DRAFT).first()
        laptop = Product.objects.get(name="Laptop Pro 14")
        QuotationLine.objects.create(
            quotation=draft, product=laptop, qty=1,
            unit_price=pricing.resolve_unit_price(laptop, draft.customer),
            discount_pct=Decimal("5"),
        )
        response = self.client.get(reverse("core:quotation_builder", args=[draft.pk]))
        # The seeded draft already carries lines, so pick the row for the line under test
        # rather than the first one — otherwise this asserts against somebody else's price.
        row = next(r for r in response.context["rows"] if r["line"].product_id == laptop.pk)
        self.assertIsNotNone(row["floor_pct"])
        self.assertGreater(row["floor_pct"], Decimal("0"))
        self.assertIn("Floor", response.content.decode())

    def test_the_floor_sits_where_the_line_would_sell_at_cost(self):
        draft = Quotation.objects.filter(stage=Quotation.Stage.DRAFT).first()
        laptop = Product.objects.get(name="Laptop Pro 14")
        line = QuotationLine.objects.create(
            quotation=draft, product=laptop, qty=1,
            unit_price=pricing.resolve_unit_price(laptop, draft.customer),
            discount_pct=Decimal("0"),
        )
        response = self.client.get(reverse("core:quotation_builder", args=[draft.pk]))
        floor = next(
            r for r in response.context["rows"] if r["line"].pk == line.pk
        )["floor_pct"]

        line.discount_pct = floor
        line.save(update_fields=["discount_pct"])
        pricing.recompute_quotation(draft)
        line.refresh_from_db()
        # At the floor the line earns essentially nothing, and never less than nothing.
        margin = line.line_total - line.line_cost
        self.assertGreaterEqual(
            margin, Decimal("0"), "the quoted floor must never sell below cost"
        )
        self.assertLess(
            margin, line.line_cost * Decimal("0.01"),
            "the floor must be the real walk-away point, not a cautious guess",
        )
