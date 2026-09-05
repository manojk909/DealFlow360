"""ADR-015 — amendments: changing what a customer already owns, mid-term.

The defining property is **co-terming**. Selling ten more seats in month four must not
restart the customer's term and must not bill them for a period they are already halfway
through. An amendment that creates a second contract alongside the first is not an
amendment — it is a new sale wearing the word.

These tests also guard the confirmation hot path. `on_order_confirmed()` now branches on
`Quotation.kind`, and that function is what Flow A and Flow B both run through, so the
branch is asserted in both directions: an amendment must not create assets or a second
schedule, and an ordinary order must behave exactly as it did before.
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Asset, BillingScheduleEntry, Customer, Product, Quotation, QuotationLine, User,
)
from core.services import assets, billing, pricing


class AmendmentTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def setUp(self):
        self.rep = User.objects.get(email="rep@dealflow.test")
        self.customer = Customer.objects.get(name="Harbour Analytics")
        self.care = Product.objects.get(name="Care Plan 2yr")
        self.laptop = Product.objects.get(name="Laptop Pro 14")
        self.asset = self.owned(self.care, 4)

    def owned(self, product, qty):
        """A confirmed order for `product`, and the asset it produced."""
        quotation = Quotation.objects.create(
            number=f"Q-AMD-{Quotation.objects.count() + 1}",
            customer=self.customer, rep=self.rep,
            stage=Quotation.Stage.CONFIRMED, last_activity_at=timezone.now(),
        )
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
        billing.on_order_confirmed(quotation)
        return quotation.assets.get()

    def mid_period(self, days_elapsed=15):
        """Age the schedule so `as_of` falls inside a period rather than on its first day.

        Amending on day one of a period correctly charges a full period — there is nothing
        elapsed to discount. That boundary is asserted separately; every other proration
        test needs a part-used period to be meaningful.
        """
        from core.models import BillingScheduleEntry

        for entry in BillingScheduleEntry.objects.filter(
            quotation_line=self.asset.source_line
        ):
            entry.due_date = entry.due_date - timedelta(days=days_elapsed)
            entry.save(update_fields=["due_date"])

    def confirm(self, quotation):
        quotation.stage = Quotation.Stage.CONFIRMED
        quotation.save(update_fields=["stage"])
        billing.on_order_confirmed(quotation)
        return quotation


class RaisingTests(AmendmentTestCase):
    def test_an_amendment_is_a_draft_quotation_referencing_the_asset(self):
        amendment = assets.create_amendment_quotation(self.asset, 6, self.rep)
        self.assertEqual(Quotation.Stage.DRAFT, amendment.stage)
        self.assertEqual(Quotation.Kind.AMENDMENT, amendment.kind)
        self.assertEqual(self.asset, amendment.amends_asset)

    def test_a_one_time_purchase_cannot_be_amended(self):
        """A laptop is not a term, so there is nothing to co-term to."""
        laptop_asset = self.owned(self.laptop, 1)
        with self.assertRaises(ValueError):
            assets.create_amendment_quotation(laptop_asset, 3, self.rep)

    def test_a_cancelled_contract_cannot_be_amended(self):
        self.asset.status = Asset.Status.CANCELLED
        self.asset.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            assets.create_amendment_quotation(self.asset, 6, self.rep)

    def test_amending_to_the_same_quantity_is_refused(self):
        with self.assertRaises(ValueError):
            assets.create_amendment_quotation(self.asset, self.asset.qty, self.rep)

    def test_raising_an_amendment_changes_nothing_yet(self):
        """Governance first. The asset moves on confirmation, not when the form is filled."""
        assets.create_amendment_quotation(self.asset, 9, self.rep)
        self.asset.refresh_from_db()
        self.assertEqual(4, self.asset.qty)


class CoTermTests(AmendmentTestCase):
    """The property that makes this an amendment rather than a second sale."""

    def test_the_end_date_does_not_move(self):
        original_end = self.asset.end_date
        self.confirm(assets.create_amendment_quotation(self.asset, 7, self.rep))
        self.asset.refresh_from_db()
        self.assertEqual(original_end, self.asset.end_date)

    def test_no_second_asset_is_created(self):
        before = Asset.objects.filter(customer=self.customer).count()
        self.confirm(assets.create_amendment_quotation(self.asset, 7, self.rep))
        self.assertEqual(before, Asset.objects.filter(customer=self.customer).count())

    def test_the_amendment_gets_no_billing_schedule_of_its_own(self):
        """The original line owns the schedule. A second one would double-bill."""
        amendment = self.confirm(assets.create_amendment_quotation(self.asset, 7, self.rep))
        self.assertFalse(amendment.billing_schedule.exists())

    def test_the_quantity_and_mrr_follow_the_amendment(self):
        self.confirm(assets.create_amendment_quotation(self.asset, 8, self.rep))
        self.asset.refresh_from_db()
        self.assertEqual(8, self.asset.qty)
        self.assertEqual(assets.monthly_value(self.asset.source_line), self.asset.mrr)


class ProrationTests(AmendmentTestCase):
    def test_an_increase_is_charged_only_for_the_days_remaining(self):
        self.mid_period()
        preview = assets.amendment_preview(self.asset, 6)
        self.assertLess(
            preview["days_remaining"], preview["days_in_period"],
            "fixture must be mid-period or there is nothing to prorate",
        )
        self.confirm(assets.create_amendment_quotation(self.asset, 6, self.rep))

        adjustment = BillingScheduleEntry.objects.filter(
            quotation_line=self.asset.source_line, is_proration_adjustment=True
        ).first()
        self.assertIsNotNone(adjustment)
        self.assertGreater(adjustment.amount, Decimal("0"))
        # Never a full period's worth for two extra seats mid-term.
        self.assertLess(adjustment.amount, preview["unit_period_price"] * 2)

    def test_a_reduction_produces_a_credit(self):
        self.mid_period()
        self.confirm(assets.create_amendment_quotation(self.asset, 2, self.rep))
        adjustment = BillingScheduleEntry.objects.filter(
            quotation_line=self.asset.source_line, is_proration_adjustment=True
        ).first()
        self.assertIsNotNone(adjustment)
        self.assertLess(adjustment.amount, Decimal("0"))

    def test_future_periods_bill_at_the_new_quantity_in_full(self):
        self.confirm(assets.create_amendment_quotation(self.asset, 6, self.rep))
        self.asset.source_line.refresh_from_db()
        future = BillingScheduleEntry.objects.filter(
            quotation_line=self.asset.source_line,
            is_proration_adjustment=False,
            due_date__gt=timezone.localdate(),
        )
        self.assertTrue(future.exists())
        for entry in future:
            self.assertEqual(self.asset.source_line.line_total, entry.amount)

    def test_amending_on_the_first_day_of_a_period_charges_that_period_in_full(self):
        """The boundary, asserted rather than left as a surprise: nothing has elapsed."""
        preview = assets.amendment_preview(self.asset, 6)
        self.assertEqual(preview["days_remaining"], preview["days_in_period"])
        self.assertEqual(preview["unit_period_price"] * 2, preview["prorated_now"])

    def test_the_preview_matches_what_confirmation_actually_charges(self):
        """The rep and the approver must see the number the service will use."""
        self.mid_period()
        preview = assets.amendment_preview(self.asset, 6)
        self.confirm(assets.create_amendment_quotation(self.asset, 6, self.rep))
        adjustment = BillingScheduleEntry.objects.filter(
            quotation_line=self.asset.source_line, is_proration_adjustment=True
        ).first()
        self.assertAlmostEqual(preview["prorated_now"], adjustment.amount, places=1)


class IdempotenceTests(AmendmentTestCase):
    def test_confirming_twice_applies_the_amendment_once(self):
        """Both the split confirmation and the portal confirmation reach this hook."""
        amendment = self.confirm(assets.create_amendment_quotation(self.asset, 6, self.rep))
        billing.on_order_confirmed(amendment)
        self.asset.refresh_from_db()
        self.assertEqual(6, self.asset.qty)
        self.assertEqual(
            1,
            BillingScheduleEntry.objects.filter(
                quotation_line=self.asset.source_line, is_proration_adjustment=True
            ).count(),
        )


class OrdinaryOrdersAreUnaffectedTests(AmendmentTestCase):
    """The confirmation hook is Flow A and Flow B. The new branch must not touch them."""

    def test_a_normal_order_still_creates_assets_and_a_schedule(self):
        quotation = Quotation.objects.create(
            number="Q-NORMAL-1", customer=self.customer, rep=self.rep,
            stage=Quotation.Stage.CONFIRMED, last_activity_at=timezone.now(),
        )
        QuotationLine.objects.create(
            quotation=quotation, product=self.care, qty=2,
            unit_price=pricing.resolve_unit_price(self.care, self.customer),
            discount_pct=Decimal("0"),
            line_type=QuotationLine.LineType.RECURRING,
            subscription_plan=self.care.subscription_plan,
        )
        pricing.recompute_quotation(quotation)
        billing.on_order_confirmed(quotation)

        self.assertEqual(Quotation.Kind.NEW, quotation.kind)
        self.assertTrue(quotation.assets.exists())
        self.assertTrue(quotation.billing_schedule.exists())
        self.assertIsNotNone(quotation.promised_delivery_date)


class AmendmentScreenTests(AmendmentTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.rep)

    def test_the_amend_button_raises_a_draft_and_opens_it(self):
        response = self.client.post(
            reverse("core:amendment_create", args=[self.asset.pk]), {"qty": 7}
        )
        self.assertEqual(302, response.status_code)
        self.assertIn("/workspace/quotations/", response["Location"])

    def test_the_builder_states_the_co_term_date_and_the_prorated_charge(self):
        amendment = assets.create_amendment_quotation(self.asset, 7, self.rep)
        response = self.client.get(reverse("core:quotation_builder", args=[amendment.pk]))
        body = response.content.decode()
        self.assertIn("Amendment", body)
        self.assertIn("Co-termed to", body)
        # The date is rendered in Django's localised format, so the context is what to
        # assert on; the template merely displays it.
        self.assertEqual(self.asset.end_date, response.context["amendment"]["co_term_date"])
        self.assertEqual(7, response.context["amendment"]["new_qty"])
        self.assertEqual(self.asset.qty, response.context["amendment"]["current_qty"])

    def test_an_invalid_amendment_returns_to_the_customer_with_a_message(self):
        response = self.client.post(
            reverse("core:amendment_create", args=[self.asset.pk]), {"qty": self.asset.qty}
        )
        self.assertEqual(302, response.status_code)
        self.assertIn(f"/workspace/customers/{self.customer.pk}/", response["Location"])
        self.assertIn("error=", response["Location"])


class SeedIsDemonstrableTests(TestCase):
    """The seed must let an amendment actually show proration.

    Every schedule used to start on the day the seed ran, so an amendment raised during a
    demo found a whole period remaining and charged it in full. Correct arithmetic, and a
    completely undemonstrative screen — the whole point of an amendment is the part-period.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def test_at_least_one_live_contract_sits_mid_period(self):
        live = Asset.objects.filter(status=Asset.Status.ACTIVE, end_date__isnull=False)
        self.assertTrue(live.exists(), "no live contract to amend")

        part_used = []
        for asset in live:
            preview = assets.amendment_preview(asset, asset.qty + 1)
            if 0 < preview["days_remaining"] < preview["days_in_period"]:
                part_used.append(asset)
        self.assertTrue(
            part_used,
            "every seeded schedule starts today, so an amendment would charge a full "
            "period and the proration would never be visible",
        )

    def test_amending_a_seeded_contract_charges_less_than_a_full_period(self):
        asset = next(
            a for a in Asset.objects.filter(status=Asset.Status.ACTIVE, end_date__isnull=False)
            if 0 < assets.amendment_preview(a, a.qty + 1)["days_remaining"]
            < assets.amendment_preview(a, a.qty + 1)["days_in_period"]
        )
        preview = assets.amendment_preview(asset, asset.qty + 2)
        self.assertLess(preview["prorated_now"], preview["unit_period_price"] * 2)
        self.assertGreater(preview["prorated_now"], Decimal("0"))
