"""Every screen added in T-20 to T-25 renders, and each one refuses an anonymous visitor.

Thin on purpose: the logic behind these pages is tested in its own service tests. What is
asserted here is the wiring — URL, view, template, context — which is exactly the class of
break that a passing service suite hides until someone clicks the nav.
"""

from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Quotation, QuotationLine, Role, User


class ScreenTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def setUp(self):
        self.client = Client(SERVER_NAME="localhost")
        self.manager = User.objects.get(email="manager@dealflow.test")
        self.client.force_login(self.manager)


class ScreensRenderTests(ScreenTestCase):
    def test_every_workspace_screen_returns_200(self):
        for name in [
            "quotation_list", "pipeline", "approval_list", "fulfilment_list",
            "billing_list", "subscription_list", "deal_health", "reports",
        ]:
            with self.subTest(screen=name):
                self.assertEqual(200, self.client.get(reverse(f"core:{name}")).status_code)

    def test_every_workspace_screen_requires_a_login(self):
        anonymous = Client(SERVER_NAME="localhost")
        for name in ["subscription_list", "deal_health", "reports", "pipeline"]:
            with self.subTest(screen=name):
                response = anonymous.get(reverse(f"core:{name}"))
                self.assertEqual(302, response.status_code)
                self.assertIn(reverse("core:login"), response["Location"])

    def test_the_deal_health_page_names_the_configured_thresholds(self):
        """A number on this page is meaningless unless the page says what produced it."""
        body = self.client.get(reverse("core:deal_health")).content.decode()
        self.assertIn("idle more than 7 days", body)
        self.assertIn("above the rep", body)

    def test_the_subscription_screen_lists_a_hybrid_order(self):
        body = self.client.get(reverse("core:subscription_list")).content.decode()
        self.assertIn("Q-2026-0140", body)


class ReportFilterTests(ScreenTestCase):
    def test_filtering_by_rep_narrows_the_result(self):
        rep = User.objects.get(email="rep3@dealflow.test")
        response = self.client.get(reverse("core:reports"), {"rep": rep.pk})
        returned = {q.rep_id for q in response.context["quotations"]}
        self.assertEqual({rep.pk}, returned)

    def test_filtering_by_team_narrows_the_result(self):
        response = self.client.get(reverse("core:reports"), {"team": "East"})
        self.assertTrue(response.context["quotations"])
        for q in response.context["quotations"]:
            self.assertEqual("East", q.rep.team)

    def test_filtering_by_approval_status_narrows_the_result(self):
        response = self.client.get(
            reverse("core:reports"), {"status": Quotation.Stage.PENDING_APPROVAL}
        )
        self.assertTrue(response.context["quotations"])
        for q in response.context["quotations"]:
            self.assertEqual(Quotation.Stage.PENDING_APPROVAL, q.stage)

    def test_the_export_returns_csv_with_one_row_per_quotation(self):
        response = self.client.get(reverse("core:reports_export"))
        self.assertEqual("text/csv", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
        rows = response.content.decode().strip().splitlines()
        self.assertEqual(Quotation.objects.count() + 1, len(rows))  # + header

    def test_the_export_obeys_the_same_filters_as_the_screen(self):
        rep = User.objects.get(email="rep3@dealflow.test")
        screen = self.client.get(reverse("core:reports"), {"rep": rep.pk})
        export = self.client.get(reverse("core:reports_export"), {"rep": rep.pk})
        rows = export.content.decode().strip().splitlines()
        self.assertEqual(len(screen.context["quotations"]) + 1, len(rows))


class NudgeTests(ScreenTestCase):
    def test_a_nudge_records_an_audit_row_and_resets_the_clock(self):
        from core.services import health

        stalled = health.stalled_deals()[0]["quotation"]
        before = stalled.last_activity_at
        self.client.post(
            reverse("core:deal_health_nudge", args=[stalled.pk]), {"note": "Any movement?"}
        )
        stalled.refresh_from_db()
        self.assertGreater(stalled.last_activity_at, before)
        entry = stalled.audit_log.get(action="NUDGE_SENT")
        self.assertIn("Any movement?", entry.reason)


class VariantPickerTests(ScreenTestCase):
    def test_choosing_a_variant_reprices_the_line_through_the_pricing_service(self):
        from core.models import Product, ProductVariant
        from core.services import pricing

        draft = Quotation.objects.filter(stage=Quotation.Stage.DRAFT).first()
        laptop = Product.objects.get(name="Laptop Pro 14")
        line = QuotationLine.objects.create(
            quotation=draft, product=laptop, qty=1,
            unit_price=pricing.resolve_unit_price(laptop, draft.customer),
        )
        upgrade = ProductVariant.objects.get(product=laptop, value="32 GB")

        response = self.client.post(
            reverse("core:line_update", args=[draft.pk, line.pk]),
            {"variant_id": upgrade.pk},
        )
        self.assertEqual(200, response.status_code)
        line.refresh_from_db()
        self.assertEqual(upgrade, line.variant)
        self.assertEqual(
            pricing.resolve_unit_price(laptop, draft.customer, variant=upgrade),
            line.unit_price,
        )
