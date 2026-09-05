"""T-20 and T-21: hybrid billing schedules, proration, cancellation, and deal health.

These are the two ADRs that were open until now. The tests pin the decisions:
ADR-008 daily pro-rata on the current period, ADR-007 thresholds read from `SalesSetting`
rather than from constants. Change the setting row and the detectors must move with it —
that is asserted, because "configured" is the word the PDF uses.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import (
    ApprovalChainRule, BillingScheduleEntry, Category, CategoryDiscountCeiling, Customer,
    CustomerTier, Invoice, Product, Quotation, QuotationLine, Role, SalesSetting,
    SubscriptionPlan, User,
)
from core.services import billing, health, pricing


class SubscriptionTestCase(TestCase):
    def setUp(self):
        tier = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        hardware = Category.objects.create(name="Hardware")
        subs = Category.objects.create(name="Subscriptions")
        for category in (hardware, subs):
            CategoryDiscountCeiling.objects.create(
                tier=tier, category=category, max_discount_pct=Decimal("15")
            )
        ApprovalChainRule.objects.create(score_min=Decimal("0"), score_max=Decimal("0"))
        self.customer = Customer.objects.create(name="Acme", email="a@a.test", tier=tier)
        self.rep = User.objects.create_user(
            email="rep@sub.test", password="x", name="Rep", role=Role.REP
        )
        self.plan = SubscriptionPlan.objects.create(
            name="Monthly", interval=SubscriptionPlan.Interval.MONTHLY,
            proration_method="DAILY", cancellation_policy="CREDIT_UNUSED_DAYS",
        )
        self.laptop = Product.objects.create(
            name="Laptop", category=hardware,
            list_price=Decimal("1000"), cost=Decimal("600"),
        )
        self.care = Product.objects.create(
            name="Care Plan", category=subs, list_price=Decimal("120"),
            cost=Decimal("40"), subscription_plan=self.plan,
        )
        self.quotation = Quotation.objects.create(
            number="Q-SUB-1", customer=self.customer, rep=self.rep,
            stage=Quotation.Stage.CONFIRMED, last_activity_at=timezone.now(),
        )
        self.one_time = QuotationLine.objects.create(
            quotation=self.quotation, product=self.laptop, qty=1,
            unit_price=Decimal("1000"), discount_pct=Decimal("0"),
        )
        self.recurring = QuotationLine.objects.create(
            quotation=self.quotation, product=self.care, qty=2,
            unit_price=Decimal("120"), discount_pct=Decimal("0"),
            line_type=QuotationLine.LineType.RECURRING, subscription_plan=self.plan,
        )
        pricing.recompute_quotation(self.quotation)
        self.recurring.refresh_from_db()


class BillingScheduleTests(SubscriptionTestCase):
    def test_a_schedule_covers_only_the_recurring_lines(self):
        """AC-6, invariant 10: the laptop is invoiced, the care plan is scheduled."""
        billing.build_billing_schedule(self.quotation, periods=3)
        lines = {entry.quotation_line_id for entry in self.quotation.billing_schedule.all()}
        self.assertEqual({self.recurring.pk}, lines)

    def test_entries_are_spaced_by_the_plan_interval(self):
        billing.build_billing_schedule(self.quotation, periods=3)
        dates = list(
            self.quotation.billing_schedule.order_by("due_date").values_list("due_date", flat=True)
        )
        self.assertEqual(3, len(dates))
        self.assertEqual(billing._add_months(dates[0], 1), dates[1])
        self.assertEqual(billing._add_months(dates[0], 2), dates[2])

    def test_a_quarterly_plan_is_spaced_three_months_apart(self):
        self.plan.interval = SubscriptionPlan.Interval.QUARTERLY
        self.plan.save(update_fields=["interval"])
        billing.build_billing_schedule(self.quotation, periods=2)
        first, second = self.quotation.billing_schedule.order_by("due_date")
        self.assertEqual(billing._add_months(first.due_date, 3), second.due_date)

    def test_building_twice_does_not_double_bill(self):
        billing.build_billing_schedule(self.quotation, periods=3)
        billing.build_billing_schedule(self.quotation, periods=3)
        self.assertEqual(3, self.quotation.billing_schedule.count())

    def test_the_invoice_still_excludes_recurring_lines(self):
        invoice = billing.generate_invoice(self.quotation)
        self.assertEqual(Decimal("1000.00"), invoice.amount)


class ProrationTests(SubscriptionTestCase):
    """ADR-008 — daily pro-rata on the current period."""

    def setUp(self):
        super().setUp()
        billing.build_billing_schedule(self.quotation, periods=3)
        self.start = self.quotation.billing_schedule.order_by("due_date").first().due_date
        self.period_end = billing._add_months(self.start, 1)

    def test_an_upgrade_halfway_through_charges_about_half_a_period(self):
        days = (self.period_end - self.start).days
        midpoint = self.start + timedelta(days=days // 2)
        entry = billing.prorate_quantity_change(self.recurring, 3, effective_date=midpoint)

        remaining = (self.period_end - midpoint).days
        expected = (Decimal("240") / 2) * Decimal(remaining) / Decimal(days)
        self.assertIsNotNone(entry)
        self.assertTrue(entry.is_proration_adjustment)
        self.assertAlmostEqual(expected, entry.amount, places=1)

    def test_a_downgrade_produces_a_negative_adjustment(self):
        days = (self.period_end - self.start).days
        midpoint = self.start + timedelta(days=days // 2)
        entry = billing.prorate_quantity_change(self.recurring, 1, effective_date=midpoint)
        self.assertLess(entry.amount, Decimal("0"))

    def test_future_periods_bill_at_the_new_quantity_in_full(self):
        midpoint = self.start + timedelta(days=5)
        billing.prorate_quantity_change(self.recurring, 4, effective_date=midpoint)
        future = self.quotation.billing_schedule.filter(
            is_proration_adjustment=False, due_date__gt=midpoint
        )
        self.assertTrue(future.exists())
        for entry in future:
            self.assertEqual(Decimal("480.00"), entry.amount)

    def test_no_change_is_not_an_adjustment(self):
        self.assertIsNone(billing.prorate_quantity_change(self.recurring, 2))

    def test_a_one_time_line_cannot_be_prorated(self):
        with self.assertRaises(ValueError):
            billing.prorate_quantity_change(self.one_time, 5)


class CancellationTests(SubscriptionTestCase):
    """FR-32 — cancel mid-cycle, credit the unused days, stop future billing."""

    def setUp(self):
        super().setUp()
        billing.build_billing_schedule(self.quotation, periods=3)
        self.start = self.quotation.billing_schedule.order_by("due_date").first().due_date

    def test_cancelling_credits_the_unused_days_of_the_current_period(self):
        period_end = billing._add_months(self.start, 1)
        days = (period_end - self.start).days
        midpoint = self.start + timedelta(days=days // 2)
        note = billing.cancel_subscription_line(self.recurring, effective_date=midpoint)
        self.assertIsNotNone(note)
        self.assertTrue(note.is_credit_note)
        self.assertGreater(note.amount, Decimal("0"))
        self.assertLess(note.amount, Decimal("240"))

    def test_cancelling_stops_every_future_billing_entry(self):
        billing.cancel_subscription_line(self.recurring, effective_date=self.start)
        remaining = self.quotation.billing_schedule.filter(
            status=BillingScheduleEntry.Status.SCHEDULED
        )
        self.assertEqual(0, remaining.count())

    def test_cancelling_writes_an_audit_row(self):
        billing.cancel_subscription_line(self.recurring, reason="Customer downsized")
        actions = list(self.quotation.audit_log.values_list("action", flat=True))
        self.assertIn("SUBSCRIPTION_CANCELLED", actions)


class DealHealthTests(SubscriptionTestCase):
    """T-21 / ADR-007 — every threshold comes off the SalesSetting row."""

    def stale(self, days):
        self.quotation.stage = Quotation.Stage.SENT
        self.quotation.last_activity_at = timezone.now() - timedelta(days=days)
        self.quotation.save(update_fields=["stage", "last_activity_at"])

    def test_a_quotation_idle_past_the_window_is_stalled(self):
        self.stale(30)
        rows = health.stalled_deals()
        self.assertEqual([self.quotation.pk], [r["quotation"].pk for r in rows])
        self.assertGreaterEqual(rows[0]["days_idle"], 30)

    def test_the_stall_window_is_configuration_not_a_constant(self):
        self.stale(10)
        self.assertEqual(1, len(health.stalled_deals()))
        setting = SalesSetting.load()
        setting.stall_days = 40
        setting.save()
        self.assertEqual([], health.stalled_deals())

    def test_a_finished_quotation_is_never_stalled(self):
        self.stale(90)
        self.quotation.stage = Quotation.Stage.PAID
        self.quotation.save(update_fields=["stage"])
        self.assertEqual([], health.stalled_deals())

    def test_a_discount_far_above_the_reps_own_average_is_an_anomaly(self):
        self.quotation.stage = Quotation.Stage.SENT
        self.quotation.save(update_fields=["stage"])
        # Six quiet lines at 2%, then one at 40%.
        for index in range(6):
            QuotationLine.objects.create(
                quotation=self.quotation, product=self.laptop, qty=1,
                unit_price=Decimal("1000"), discount_pct=Decimal("2"),
            )
        loud = QuotationLine.objects.create(
            quotation=self.quotation, product=self.laptop, qty=1,
            unit_price=Decimal("1000"), discount_pct=Decimal("40"),
        )
        flagged = [row["line"].pk for row in health.discount_anomalies()]
        self.assertIn(loud.pk, flagged)

    def test_a_rep_with_no_history_raises_no_anomalies(self):
        """A new rep has no average to be above; flagging them would be noise."""
        self.assertEqual([], health.discount_anomalies())

    def test_an_order_past_its_promise_with_nothing_shipped_has_slipped(self):
        self.quotation.stage = Quotation.Stage.CONFIRMED
        self.quotation.promised_delivery_date = date.today() - timedelta(days=3)
        self.quotation.save(update_fields=["stage", "promised_delivery_date"])
        rows = health.delivery_slippage()
        self.assertEqual([self.quotation.pk], [r["quotation"].pk for r in rows])
        self.assertEqual(3, rows[0]["days_late"])

    def test_an_order_with_no_promise_date_is_never_late(self):
        self.quotation.stage = Quotation.Stage.CONFIRMED
        self.quotation.save(update_fields=["stage"])
        self.assertEqual([], health.delivery_slippage())

    def test_the_dashboard_composes_all_three_detectors(self):
        self.stale(30)
        data = health.dashboard()
        self.assertEqual({"setting", "stalled", "anomalies", "slippage", "alert_count", "as_of"}, set(data))
        self.assertEqual(data["alert_count"], len(data["stalled"]) + len(data["anomalies"]) + len(data["slippage"]))


class SeedDemoTests(TestCase):
    """The seed is a deliverable ("sample seed data", PDF §8), so it is tested.

    It is also the only fixture the demo runs on: a seed that half-fails on stage is
    worse than no seed, and the failure would surface ninety seconds before the judges.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        from io import StringIO

        call_command("seed_demo", stdout=StringIO())

    def test_it_produces_a_populated_system(self):
        from core.models import Category, Customer, Product, Warehouse

        self.assertGreaterEqual(Quotation.objects.count(), 20)
        self.assertGreaterEqual(Product.objects.count(), 18)
        self.assertGreaterEqual(Customer.objects.count(), 8)
        self.assertGreaterEqual(User.objects.count(), 10)
        self.assertEqual(3, Warehouse.objects.count())
        self.assertEqual(3, Category.objects.count())

    def test_running_it_twice_leaves_one_clean_dataset(self):
        from django.core.management import call_command
        from io import StringIO

        before = Quotation.objects.count()
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(before, Quotation.objects.count())

    def test_the_settings_row_exists_so_the_dashboard_has_thresholds(self):
        self.assertEqual(7, SalesSetting.load().stall_days)

    def test_every_health_panel_has_something_to_show(self):
        """An empty dashboard proves nothing on stage, so the seed must populate all three."""
        data = health.dashboard()
        self.assertTrue(data["stalled"], "no stalled deals seeded")
        self.assertTrue(data["anomalies"], "no discount anomaly seeded")
        self.assertTrue(data["slippage"], "no delivery slippage seeded")

    def test_a_hybrid_order_arrives_with_a_billing_schedule(self):
        hybrid = Quotation.objects.get(number="Q-2026-0140")
        self.assertTrue(hybrid.billing_schedule.exists())
        self.assertTrue(billing.upcoming_schedule(hybrid))

    def test_the_split_trigger_stock_is_intact(self):
        """DEMO.md Flow A depends on Main holding fewer laptops than the demo order."""
        from core.models import Product, Stock

        laptop = Product.objects.get(name="Laptop Pro 14")
        main = Stock.objects.get(product=laptop, warehouse__name="Main Warehouse")
        self.assertEqual(4, main.qty_on_hand)


class BusinessDateTests(TestCase):
    """Dates are the configured zone's, not UTC's.

    Found at 00:24 IST: `timezone.now().date()` is the *UTC* date, so with
    TIME_ZONE = Asia/Kolkata every evening between 18:30 and midnight the application was
    a day behind — invoices dated yesterday, schedules starting yesterday, slippage
    counted a day short. Precisely the window an evening demo falls in.
    """

    def test_the_services_use_the_configured_zone_not_utc(self):
        import datetime

        from django.utils import timezone

        from core.services import billing

        # 18:54 UTC is already the next day in Asia/Kolkata.
        moment = datetime.datetime(2026, 9, 5, 18, 54, tzinfo=datetime.timezone.utc)
        self.assertNotEqual(
            moment.date(), timezone.localdate(moment),
            "this test is meaningless unless the two dates differ",
        )
        import inspect

        # The guard that matters: no service may derive a business date from UTC again.
        for module in (billing, health):
            source = inspect.getsource(module)
            self.assertNotIn(
                "now().date()", source,
                f"{module.__name__} derives a business date from UTC; use timezone.localdate()",
            )
