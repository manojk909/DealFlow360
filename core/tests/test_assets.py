"""ADR-013 — the asset lifecycle: what a customer owns, what it earns, and renewals.

An asset is the record quotations cannot replace. A quotation says what was agreed on a
day; an asset says what is true today, which is the only basis on which MRR, churn and
renewals can be computed. These tests pin the three properties that make it trustworthy:

* assets are created by the system at confirmation and never twice for the same line,
* MRR is normalised to a month whatever the plan interval,
* a renewal is priced at today's price list, not the price on the original order.
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Asset, Customer, PriceListEntry, Product, Quotation, QuotationLine, Role,
    SubscriptionPlan, User,
)
from core.services import assets, billing, pricing


class AssetTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def setUp(self):
        self.rep = User.objects.get(email="rep@dealflow.test")
        self.customer = Customer.objects.get(name="Harbour Analytics")
        self.laptop = Product.objects.get(name="Laptop Pro 14")
        self.care = Product.objects.get(name="Care Plan 2yr")

    def confirmed_order(self, lines):
        quotation = Quotation.objects.create(
            number=f"Q-AST-{Quotation.objects.count() + 1}",
            customer=self.customer, rep=self.rep,
            stage=Quotation.Stage.CONFIRMED, last_activity_at=timezone.now(),
        )
        for product, qty in lines:
            recurring = product.subscription_plan is not None
            QuotationLine.objects.create(
                quotation=quotation, product=product, qty=qty,
                unit_price=pricing.resolve_unit_price(product, self.customer),
                discount_pct=Decimal("0"),
                line_type=(
                    QuotationLine.LineType.RECURRING if recurring
                    else QuotationLine.LineType.ONE_TIME
                ),
                subscription_plan=product.subscription_plan if recurring else None,
            )
        pricing.recompute_quotation(quotation)
        return quotation


class CreationTests(AssetTestCase):
    def test_confirming_an_order_creates_one_asset_per_line(self):
        quotation = self.confirmed_order([(self.laptop, 2), (self.care, 3)])
        billing.on_order_confirmed(quotation)
        self.assertEqual(2, quotation.assets.count())

    def test_a_one_time_purchase_never_expires(self):
        """Owning a laptop does not run out, so it carries no end date and no MRR."""
        quotation = self.confirmed_order([(self.laptop, 1)])
        billing.on_order_confirmed(quotation)
        asset = quotation.assets.get()
        self.assertIsNone(asset.end_date)
        self.assertEqual(Decimal("0.00"), asset.mrr)
        self.assertFalse(asset.is_recurring)

    def test_a_recurring_line_gets_a_term_and_an_mrr(self):
        quotation = self.confirmed_order([(self.care, 2)])
        billing.on_order_confirmed(quotation)
        asset = quotation.assets.get()
        self.assertIsNotNone(asset.end_date)
        self.assertGreater(asset.mrr, Decimal("0"))
        self.assertTrue(asset.is_recurring)

    def test_confirming_twice_does_not_duplicate_assets(self):
        """Both the rep's split confirmation and the portal's reach the same hook."""
        quotation = self.confirmed_order([(self.laptop, 1), (self.care, 1)])
        billing.on_order_confirmed(quotation)
        billing.on_order_confirmed(quotation)
        self.assertEqual(2, quotation.assets.count())


class MrrTests(AssetTestCase):
    def test_mrr_is_normalised_across_plan_intervals(self):
        """A quarterly plan billed 900 is 300 a month; without this every dashboard lies."""
        quarterly = SubscriptionPlan.objects.get(name="Quarterly Support")
        product = Product.objects.get(name="Priority Support SLA")
        product.subscription_plan = quarterly
        product.save(update_fields=["subscription_plan"])

        quotation = self.confirmed_order([(product, 1)])
        line = quotation.lines.get()
        billing.on_order_confirmed(quotation)

        asset = quotation.assets.get()
        self.assertEqual((line.line_total / 3).quantize(Decimal("0.01")), asset.mrr)

    def test_arr_is_twelve_months_of_mrr(self):
        quotation = self.confirmed_order([(self.care, 2)])
        billing.on_order_confirmed(quotation)
        summary = assets.mrr_summary(self.customer)
        self.assertEqual((summary["mrr"] * 12).quantize(Decimal("0.01")), summary["arr"])

    def test_one_time_assets_contribute_nothing_to_mrr(self):
        before = assets.mrr_summary()["mrr"]
        quotation = self.confirmed_order([(self.laptop, 5)])
        billing.on_order_confirmed(quotation)
        self.assertEqual(before, assets.mrr_summary()["mrr"])

    def test_a_cancelled_asset_leaves_mrr(self):
        quotation = self.confirmed_order([(self.care, 1)])
        billing.on_order_confirmed(quotation)
        with_asset = assets.mrr_summary(self.customer)["mrr"]

        quotation.assets.update(status=Asset.Status.CANCELLED)
        self.assertLess(assets.mrr_summary(self.customer)["mrr"], with_asset)


class RenewalTests(AssetTestCase):
    def expiring(self, days):
        quotation = self.confirmed_order([(self.care, 2)])
        billing.on_order_confirmed(quotation)
        asset = quotation.assets.get()
        asset.end_date = timezone.localdate() + timedelta(days=days)
        asset.save(update_fields=["end_date"])
        return asset

    def test_the_queue_finds_contracts_inside_the_window(self):
        asset = self.expiring(20)
        due = [row.pk for row in assets.due_for_renewal(within_days=30)]
        self.assertIn(asset.pk, due)

    def test_the_queue_ignores_contracts_beyond_the_window(self):
        asset = self.expiring(200)
        due = [row.pk for row in assets.due_for_renewal(within_days=30)]
        self.assertNotIn(asset.pk, due)

    def test_an_already_lapsed_contract_is_still_in_the_queue(self):
        """Something nobody renewed is more urgent than something expiring next month."""
        asset = self.expiring(-10)
        due = [row.pk for row in assets.due_for_renewal(within_days=30)]
        self.assertIn(asset.pk, due)

    def test_a_renewal_is_priced_at_todays_price_list_not_the_old_order(self):
        """A renewal is a new agreement. Carrying the old price forward leaks margin."""
        asset = self.expiring(15)
        asset.unit_price = Decimal("1.00")  # what they paid last time
        asset.save(update_fields=["unit_price"])

        renewal = assets.create_renewal_quotation([asset], self.rep)
        line = renewal.lines.get()
        self.assertEqual(
            pricing.resolve_unit_price(self.care, self.customer), line.unit_price
        )
        self.assertNotEqual(Decimal("1.00"), line.unit_price)

    def test_a_renewal_starts_as_a_draft_the_rep_can_still_edit(self):
        renewal = assets.create_renewal_quotation([self.expiring(15)], self.rep)
        self.assertEqual(Quotation.Stage.DRAFT, renewal.stage)

    def test_renewing_marks_the_asset_and_links_the_new_quotation(self):
        asset = self.expiring(15)
        renewal = assets.create_renewal_quotation([asset], self.rep)
        asset.refresh_from_db()
        self.assertEqual(Asset.Status.RENEWED, asset.status)
        self.assertEqual(renewal, asset.renewed_into)

    def test_an_asset_cannot_be_renewed_twice(self):
        asset = self.expiring(15)
        assets.create_renewal_quotation([asset], self.rep)
        due = [row.pk for row in assets.due_for_renewal(within_days=30)]
        self.assertNotIn(asset.pk, due)

    def test_a_renewal_covers_one_customer_at_a_time(self):
        mine = self.expiring(15)
        other_customer = Customer.objects.exclude(pk=self.customer.pk).first()
        theirs = self.expiring(15)
        theirs.customer = other_customer
        theirs.save(update_fields=["customer"])

        with self.assertRaises(ValueError):
            assets.create_renewal_quotation([mine, theirs], self.rep)

    def test_renewing_nothing_is_refused(self):
        with self.assertRaises(ValueError):
            assets.create_renewal_quotation([], self.rep)

    def test_the_renewal_is_recorded_in_the_audit_trail(self):
        renewal = assets.create_renewal_quotation([self.expiring(15)], self.rep)
        self.assertTrue(renewal.audit_log.filter(action="RENEWAL_RAISED").exists())


class AssetScreenTests(AssetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.rep)

    def test_every_asset_screen_renders(self):
        for name, args in [
            ("core:customer_list", []),
            ("core:customer_detail", [self.customer.pk]),
            ("core:renewal_list", []),
        ]:
            with self.subTest(screen=name):
                self.assertEqual(200, self.client.get(reverse(name, args=args)).status_code)

    def test_raising_a_renewal_from_the_queue_lands_on_the_builder(self):
        quotation = self.confirmed_order([(self.care, 1)])
        billing.on_order_confirmed(quotation)
        asset = quotation.assets.get()
        asset.end_date = timezone.localdate() + timedelta(days=10)
        asset.save(update_fields=["end_date"])

        response = self.client.post(
            reverse("core:renewal_create", args=[self.customer.pk]), {"within": 30}
        )
        self.assertEqual(302, response.status_code)
        self.assertIn("/workspace/quotations/", response["Location"])
        asset.refresh_from_db()
        self.assertEqual(Asset.Status.RENEWED, asset.status)


class SeededAssetTests(TestCase):
    """The seed must leave both screens with something true to show."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def test_the_seed_creates_assets(self):
        self.assertGreater(Asset.objects.count(), 10)

    def test_the_seed_produces_a_real_mrr(self):
        self.assertGreater(assets.mrr_summary()["mrr"], Decimal("0"))

    def test_the_renewals_queue_is_populated_and_includes_something_lapsed(self):
        due = assets.due_for_renewal(within_days=90)
        self.assertTrue(due, "nothing up for renewal — the queue would demo empty")
        self.assertTrue(
            any(asset.end_date < timezone.localdate() for asset in due),
            "no lapsed contract seeded — the urgent case would never be shown",
        )


class CustomerAggregateTests(AssetTestCase):
    """The customers screen must agree with the database, and with its own tiles.

    The bug this guards against: annotating two multi-valued relations in one query —
    `assets` and `quotations` — makes SQL multiply the rows. A customer with 3 assets and
    4 quotations reported 12 assets and four times the MRR, while the summary tile above
    the table (a single-relation aggregate) reported the truth. The screen contradicted
    itself in two places at once, which is worse than being wrong in one.

    `distinct=True` repairs a Count under fan-out. It does nothing for a Sum. Both are
    subqueries now.
    """

    def setUp(self):
        super().setUp()
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.rep)

    def rows(self):
        return {
            row.pk: row
            for row in self.client.get(reverse("core:customer_list")).context["customers"]
        }

    def test_each_row_matches_a_direct_count_of_that_customers_assets(self):
        for customer_id, row in self.rows().items():
            expected = Asset.objects.filter(
                customer_id=customer_id, status=Asset.Status.ACTIVE
            ).count()
            with self.subTest(customer=row.name):
                self.assertEqual(expected, row.asset_count)

    def test_each_row_matches_a_direct_sum_of_that_customers_mrr(self):
        for customer_id, row in self.rows().items():
            expected = assets.mrr_summary(row)["mrr"]
            with self.subTest(customer=row.name):
                self.assertEqual(expected, row.monthly)

    def test_the_rows_add_up_to_the_summary_tile(self):
        """The tile and the table are two paths to one number; they must not disagree."""
        response = self.client.get(reverse("core:customer_list"))
        rows_total = sum((row.monthly for row in response.context["customers"]), Decimal("0"))
        self.assertEqual(response.context["summary"]["mrr"], rows_total)

    def test_a_customer_owning_nothing_shows_zero_not_none(self):
        """A subquery over no rows returns NULL, which the template printed as "None"."""
        empty = [row for row in self.rows().values() if row.asset_count == 0]
        self.assertTrue(empty, "expected at least one customer owning nothing")
        for row in empty:
            self.assertIsNotNone(row.asset_count)
            self.assertIsNotNone(row.quotation_count)

    def test_the_quotation_count_is_not_inflated_either(self):
        for customer_id, row in self.rows().items():
            expected = Quotation.objects.filter(customer_id=customer_id).count()
            with self.subTest(customer=row.name):
                self.assertEqual(expected, row.quotation_count)
