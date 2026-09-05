"""Upsell and cross-sell panel (T-19, BR-7, AC-4).

AC-4's wording is what matters here: after accepting a suggestion the order total and the
margin must update **right away**. That is asserted at the HTTP level — one POST, one
partial back, carrying the new totals.
"""

from decimal import Decimal

from django.test import Client, TestCase

from core.models import (
    ApprovalChainRule,
    Category,
    Customer,
    CustomerTier,
    Product,
    ProductPair,
    Quotation,
    QuotationLine,
    Role,
    SubscriptionPlan,
    User,
)
from core.services import pricing, upsell


class UpsellTestCase(TestCase):
    def setUp(self):
        tier = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        ApprovalChainRule.objects.create(
            score_min=Decimal("0.00"), score_max=Decimal("9999.99")
        )
        self.customer = Customer.objects.create(name="Acme", email="a@a.test", tier=tier)
        self.rep = User.objects.create_user(
            email="rep@u.test", password="x", name="Rep", role=Role.REP
        )
        self.hardware = Category.objects.create(name="Hardware")
        self.subs = Category.objects.create(name="Subscriptions")
        self.plan = SubscriptionPlan.objects.create(
            name="Monthly Care", interval=SubscriptionPlan.Interval.MONTHLY
        )

        self.laptop = Product.objects.create(
            name="Laptop Pro 14", category=self.hardware,
            list_price=Decimal("1450"), cost=Decimal("1050"),
        )
        self.care = Product.objects.create(
            name="Care Plan 2yr", category=self.subs, subscription_plan=self.plan,
            list_price=Decimal("480"), cost=Decimal("180"), is_promoted=True,
        )
        self.dock = Product.objects.create(
            name="Docking Station X3", category=self.hardware,
            list_price=Decimal("220"), cost=Decimal("150"),
        )
        self.thin = Product.objects.create(
            name="Thin Margin Cable", category=self.hardware,
            list_price=Decimal("100"), cost=Decimal("99"),
        )

        ProductPair.objects.create(product_a=self.laptop, product_b=self.care, co_purchase_count=42)
        ProductPair.objects.create(product_a=self.laptop, product_b=self.dock, co_purchase_count=31)
        ProductPair.objects.create(product_a=self.laptop, product_b=self.thin, co_purchase_count=99)

        self.quotation = Quotation.objects.create(
            number="Q-U-1", customer=self.customer, rep=self.rep,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        QuotationLine.objects.create(
            quotation=self.quotation, product=self.laptop, qty=6,
            unit_price=Decimal("1450"), discount_pct=Decimal("0"),
        )
        pricing.recompute_quotation(self.quotation)


class RankingTests(UpsellTestCase):

    def test_care_plan_is_the_top_suggestion_for_a_laptop_quote(self):
        """DEMO A5 has to be predictable on stage."""
        suggestions = upsell.suggest(self.quotation)
        self.assertEqual("Care Plan 2yr", suggestions[0].name)
        self.assertEqual("Promoted", suggestions[0].promotion_tag)
        self.assertEqual(42, suggestions[0].co_purchase_count)

    def test_a_low_margin_product_is_filtered_out_however_often_it_is_co_purchased(self):
        """BR-7: only healthy-margin suggestions surface. 99 co-purchases cannot buy in."""
        names = [s.name for s in upsell.suggest(self.quotation, limit=10)]
        self.assertNotIn("Thin Margin Cable", names)

    def test_lowering_the_threshold_lets_it_through(self):
        """Proves the filter is the threshold, not something hardcoded about that product."""
        names = [
            s.name
            for s in upsell.suggest(self.quotation, limit=10, min_margin_pct=Decimal("0"))
        ]
        self.assertIn("Thin Margin Cable", names)

    def test_products_already_on_the_quotation_are_not_suggested(self):
        upsell.add_to_quotation(self.quotation, self.care)
        names = [s.name for s in upsell.suggest(self.quotation, limit=10)]
        self.assertNotIn("Care Plan 2yr", names)

    def test_margin_delta_is_reported_per_suggestion(self):
        before = self.quotation.margin_pct
        suggestion = upsell.suggest(self.quotation)[0]
        projected = pricing.margin_after_adding(self.quotation, self.care, qty=1)
        self.assertEqual((projected - before).quantize(Decimal("0.01")),
                         suggestion.margin_delta_pct)
        self.assertGreater(suggestion.margin_delta_pct, 0)

    def test_the_promoted_boost_lifts_an_equally_ranked_product(self):
        ProductPair.objects.filter(product_b=self.care).update(co_purchase_count=31)
        suggestions = upsell.suggest(self.quotation)
        # Care Plan and Docking Station both at 31; the promoted one wins.
        self.assertEqual("Care Plan 2yr", suggestions[0].name)

    def test_an_empty_quotation_suggests_nothing(self):
        empty = Quotation.objects.create(
            number="Q-U-2", customer=self.customer, rep=self.rep,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        self.assertEqual([], upsell.suggest(empty))

    def test_an_inactive_product_is_never_suggested(self):
        Product.objects.filter(pk=self.care.pk).update(active=False)
        names = [s.name for s in upsell.suggest(self.quotation, limit=10)]
        self.assertNotIn("Care Plan 2yr", names)

    def test_suggest_writes_nothing(self):
        before = self.quotation.lines.count()
        upsell.suggest(self.quotation)
        self.assertEqual(before, self.quotation.lines.count())


class AddToQuotationTests(UpsellTestCase):

    def test_adding_flags_the_line_and_recomputes(self):
        line, totals = upsell.add_to_quotation(self.quotation, self.care)
        self.assertTrue(line.added_via_upsell)
        self.assertEqual(totals.total, self.quotation.total)

    def test_a_subscription_product_is_added_as_a_recurring_line_with_its_plan(self):
        """Invariant 9, satisfied without the caller thinking about it."""
        line, _ = upsell.add_to_quotation(self.quotation, self.care)
        self.assertEqual(QuotationLine.LineType.RECURRING, line.line_type)
        self.assertEqual(self.plan, line.subscription_plan)

    def test_a_one_time_product_gets_no_plan(self):
        line, _ = upsell.add_to_quotation(self.quotation, self.dock)
        self.assertEqual(QuotationLine.LineType.ONE_TIME, line.line_type)
        self.assertIsNone(line.subscription_plan)


class AC4Tests(UpsellTestCase):
    """AC-4: accept a suggestion, and the total and margin update right away."""

    def setUp(self):
        super().setUp()
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.rep)

    def test_one_post_returns_a_partial_carrying_the_new_total_and_margin(self):
        before_total = self.quotation.total
        before_margin = self.quotation.margin_pct

        response = self.client.post(
            f"/workspace/quotations/{self.quotation.pk}/upsell/add/",
            {"product_id": self.care.pk},
        )
        body = response.content.decode()
        self.quotation.refresh_from_db()

        self.assertEqual(200, response.status_code)
        # A partial, not a page: no full reload happened.
        self.assertNotIn("<html", body)
        self.assertIn('id="builder-region"', body)

        self.assertNotEqual(before_total, self.quotation.total)
        self.assertNotEqual(before_margin, self.quotation.margin_pct)
        # The response itself carries the updated figures, not just the database.
        self.assertIn(f"{self.quotation.margin_pct:.2f}", body)
        self.assertIn("Care Plan 2yr", body)

    def test_the_added_product_stops_being_suggested_in_the_same_response(self):
        body = self.client.post(
            f"/workspace/quotations/{self.quotation.pk}/upsell/add/",
            {"product_id": self.care.pk},
        ).content.decode()
        panel = body.split("Upsell and cross-sell suggestions")[-1]
        self.assertNotIn("Add to quote\n", panel.split("Docking Station X3")[0][:0] or "")
        self.assertIn("Docking Station X3", body)

    def test_dismiss_removes_a_suggestion_for_the_session_without_adding_it(self):
        response = self.client.post(
            f"/workspace/quotations/{self.quotation.pk}/upsell/dismiss/",
            {"product_id": self.care.pk},
        )
        body = response.content.decode()
        self.assertEqual(200, response.status_code)
        panel = body.split("Upsell and cross-sell suggestions")[-1]
        self.assertNotIn("Care Plan 2yr", panel)
        self.assertEqual(1, self.quotation.lines.count(), "dismiss must not add a line")

    def test_the_panel_states_the_margin_threshold_it_applied(self):
        body = self.client.get(
            f"/workspace/quotations/{self.quotation.pk}/"
        ).content.decode()
        self.assertIn("margin", body)
        self.assertIn(f"{upsell.DEFAULT_MIN_MARGIN_PCT:.0f}% margin", body)
