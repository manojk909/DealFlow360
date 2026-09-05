"""Tests for the pricing engine (T-08, FR-10, FR-11).

Builds its own rows in `setUp` — deliberately independent of `seed_demo`, so a broken
seed cannot make these pass or fail for the wrong reason.

Every assertion compares exact `Decimal` values. Comparing money "approximately" would
defeat the point of ADR-002.
"""

from decimal import Decimal

from django.test import TestCase

from core.models import (
    Category,
    Customer,
    CustomerTier,
    PriceListEntry,
    Product,
    ProductVariant,
    Quotation,
    QuotationLine,
    Role,
    User,
)
from core.services import pricing


class PricingTestCase(TestCase):
    def setUp(self):
        self.tier = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        self.customer = Customer.objects.create(
            name="Acme Corp", email="buyer@acme.test", tier=self.tier
        )
        self.rep = User.objects.create_user(
            email="rep@test.test", password="x", name="Rep", role=Role.REP
        )
        self.hardware = Category.objects.create(name="Hardware")
        self.laptop = Product.objects.create(
            name="Laptop", category=self.hardware,
            list_price=Decimal("1000.00"), cost=Decimal("600.00"),
        )
        self.quotation = Quotation.objects.create(
            number="Q-TEST-1", customer=self.customer, rep=self.rep,
            last_activity_at="2026-09-05T10:00:00Z",
        )

    def add_line(self, product=None, qty=1, unit_price="1000.00", discount="0"):
        return QuotationLine.objects.create(
            quotation=self.quotation,
            product=product or self.laptop,
            qty=qty,
            unit_price=Decimal(unit_price),
            discount_pct=Decimal(discount),
        )


class LineTotalTests(PricingTestCase):
    """`qty * unit_price * (1 - discount/100)` — the one definition of a line's money."""

    def test_zero_discount_is_qty_times_price(self):
        self.assertEqual(
            Decimal("3000.00"), pricing.line_total(3, Decimal("1000.00"), Decimal("0"))
        )

    def test_full_line_discount_gives_exactly_zero(self):
        """A 100% discount is free, not a rounding artefact near zero."""
        self.assertEqual(
            Decimal("0.00"), pricing.line_total(3, Decimal("1000.00"), Decimal("100"))
        )

    def test_partial_discount(self):
        # 6 x 1450 = 8700, less 12% = 7656.00 — the demo's laptop line.
        self.assertEqual(
            Decimal("7656.00"), pricing.line_total(6, Decimal("1450.00"), Decimal("12"))
        )

    def test_rounds_to_two_places(self):
        # 1 x 33.33 less 7.5% = 30.830250 -> 30.83
        self.assertEqual(
            Decimal("30.83"), pricing.line_total(1, Decimal("33.33"), Decimal("7.5"))
        )

    def test_rejects_discount_above_100(self):
        with self.assertRaises(ValueError):
            pricing.line_total(1, Decimal("10.00"), Decimal("101"))

    def test_rejects_negative_discount(self):
        with self.assertRaises(ValueError):
            pricing.line_total(1, Decimal("10.00"), Decimal("-1"))

    def test_rejects_non_positive_quantity(self):
        with self.assertRaises(ValueError):
            pricing.line_total(0, Decimal("10.00"), Decimal("0"))


class RecomputeQuotationTests(PricingTestCase):
    def test_zero_discount_anywhere(self):
        self.add_line(qty=2, unit_price="1000.00", discount="0")
        totals = pricing.recompute_quotation(self.quotation)

        self.assertEqual(Decimal("2000.00"), totals.subtotal)
        self.assertEqual(Decimal("2000.00"), totals.total)
        # cost 2 x 600 = 1200; margin 800 of 2000 = 40%
        self.assertEqual(Decimal("800.00"), totals.margin_amount)
        self.assertEqual(Decimal("40.00"), totals.margin_pct)

    def test_full_line_discount_zeroes_the_line_but_not_the_cost(self):
        """Giving a line away free still costs us — margin must go negative."""
        self.add_line(qty=1, unit_price="1000.00", discount="100")
        totals = pricing.recompute_quotation(self.quotation)

        self.assertEqual(Decimal("0.00"), totals.subtotal)
        self.assertEqual(Decimal("0.00"), totals.total)
        self.assertEqual(Decimal("-600.00"), totals.margin_amount)
        # total is zero, so margin_pct is 0.00 rather than a division by zero.
        self.assertEqual(Decimal("0.00"), totals.margin_pct)

    def test_mixed_line_and_order_discount(self):
        """Line discounts first, then the order discount on the sum (FR-10).

        2 x 1000 less 10% = 1800. Then a 5% order discount = 1710.00.
        Applying both to the gross would give 2000 x 0.85 = 1700 — a different number,
        and the wrong one.
        """
        self.add_line(qty=2, unit_price="1000.00", discount="10")
        self.quotation.order_discount_pct = Decimal("5")
        self.quotation.save(update_fields=["order_discount_pct"])

        totals = pricing.recompute_quotation(self.quotation)

        self.assertEqual(Decimal("1800.00"), totals.subtotal)
        self.assertEqual(Decimal("1710.00"), totals.total)
        self.assertNotEqual(Decimal("1700.00"), totals.total)
        # cost 1200; margin 510 of 1710 = 29.82%
        self.assertEqual(Decimal("510.00"), totals.margin_amount)
        self.assertEqual(Decimal("29.82"), totals.margin_pct)

    def test_multiple_lines_with_different_discounts(self):
        service = Product.objects.create(
            name="Setup", category=Category.objects.create(name="Services"),
            list_price=Decimal("600.00"), cost=Decimal("330.00"),
        )
        self.add_line(qty=6, unit_price="1450.00", discount="12")   # 7656.00
        self.add_line(product=service, qty=1, unit_price="600.00", discount="18")  # 492.00

        totals = pricing.recompute_quotation(self.quotation)
        self.assertEqual(Decimal("8148.00"), totals.subtotal)
        self.assertEqual(Decimal("8148.00"), totals.total)

    def test_empty_quotation_has_no_margin_rather_than_an_undefined_one(self):
        totals = pricing.recompute_quotation(self.quotation)
        self.assertEqual(Decimal("0.00"), totals.subtotal)
        self.assertEqual(Decimal("0.00"), totals.total)
        self.assertEqual(Decimal("0.00"), totals.margin_amount)
        self.assertEqual(Decimal("0.00"), totals.margin_pct)

    def test_save_persists_lines_and_header(self):
        line = self.add_line(qty=2, unit_price="1000.00", discount="10")
        pricing.recompute_quotation(self.quotation)

        line.refresh_from_db()
        self.quotation.refresh_from_db()
        self.assertEqual(Decimal("1800.00"), line.line_total)
        self.assertEqual(Decimal("1200.00"), line.line_cost)
        self.assertEqual(Decimal("1800.00"), self.quotation.total)

    def test_save_false_writes_nothing(self):
        line = self.add_line(qty=2, unit_price="1000.00", discount="10")
        totals = pricing.recompute_quotation(self.quotation, save=False)

        self.assertEqual(Decimal("1800.00"), totals.total)
        line.refresh_from_db()
        self.quotation.refresh_from_db()
        self.assertEqual(Decimal("0.00"), line.line_total)
        self.assertEqual(Decimal("0.00"), self.quotation.total)


class ResolveUnitPriceTests(PricingTestCase):
    def test_falls_back_to_list_price_when_no_price_list_entry(self):
        self.assertEqual(
            Decimal("1000.00"), pricing.resolve_unit_price(self.laptop, self.customer)
        )

    def test_uses_the_tier_price_list_entry_when_one_exists(self):
        PriceListEntry.objects.create(
            product=self.laptop, tier=self.tier, price=Decimal("950.00")
        )
        self.assertEqual(
            Decimal("950.00"), pricing.resolve_unit_price(self.laptop, self.customer)
        )

    def test_another_tiers_price_is_not_used(self):
        silver = CustomerTier.objects.create(name="Silver", max_discount_pct=Decimal("10"))
        PriceListEntry.objects.create(
            product=self.laptop, tier=silver, price=Decimal("970.00")
        )
        self.assertEqual(
            Decimal("1000.00"), pricing.resolve_unit_price(self.laptop, self.customer)
        )

    def test_variant_surcharge_is_added_on_top_of_the_tier_price(self):
        PriceListEntry.objects.create(
            product=self.laptop, tier=self.tier, price=Decimal("950.00")
        )
        variant = ProductVariant.objects.create(
            product=self.laptop, attribute="Memory", value="32 GB",
            extra_price=Decimal("180.00"),
        )
        self.assertEqual(
            Decimal("1130.00"),
            pricing.resolve_unit_price(self.laptop, self.customer, variant=variant),
        )

    def test_variant_from_another_product_is_rejected(self):
        other = Product.objects.create(
            name="Monitor", category=self.hardware,
            list_price=Decimal("300.00"), cost=Decimal("200.00"),
        )
        variant = ProductVariant.objects.create(
            product=other, attribute="Stand", value="Tall", extra_price=Decimal("10.00")
        )
        with self.assertRaises(ValueError):
            pricing.resolve_unit_price(self.laptop, self.customer, variant=variant)


class MarginAfterAddingTests(PricingTestCase):
    def test_projects_margin_without_writing_anything(self):
        self.add_line(qty=1, unit_price="1000.00", discount="0")
        pricing.recompute_quotation(self.quotation)
        before = self.quotation.margin_pct

        addon = Product.objects.create(
            name="Care Plan", category=self.hardware,
            list_price=Decimal("500.00"), cost=Decimal("100.00"),
        )
        projected = pricing.margin_after_adding(self.quotation, addon, qty=1)

        # 1500 revenue, 700 cost -> 800/1500 = 53.33%, up from 40.00%.
        self.assertEqual(Decimal("53.33"), projected)
        self.assertGreater(projected, before)

        # Nothing was written.
        self.quotation.refresh_from_db()
        self.assertEqual(before, self.quotation.margin_pct)
        self.assertEqual(1, self.quotation.lines.count())

    def test_a_low_margin_addon_drags_the_projection_down(self):
        self.add_line(qty=1, unit_price="1000.00", discount="0")
        pricing.recompute_quotation(self.quotation)

        thin = Product.objects.create(
            name="Thin Margin Item", category=self.hardware,
            list_price=Decimal("500.00"), cost=Decimal("480.00"),
        )
        projected = pricing.margin_after_adding(self.quotation, thin, qty=1)
        self.assertLess(projected, self.quotation.margin_pct)
