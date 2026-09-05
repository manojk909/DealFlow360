"""The whole flow, driven over HTTP by the role that actually performs each step.

Every other test file exercises one service or one screen. This one asks the question a
judge asks: can a Rep, a Manager, a Finance user and a customer, each signed in as
themselves, carry one deal from an empty draft to a paid invoice — and is every screen
each role can reach actually reachable?

Two failure modes it is written to catch:

* **A step that only works because the test client is an Admin.** Admin can do everything,
  so a suite that logs in as Admin proves nothing about the chain. Each step here uses the
  narrowest role that should be able to perform it.
* **A screen that 403s from its own navigation.** A link a role can see but not open is a
  bug, so visibility and permission are asserted together.
"""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from core.models import (
    ApprovalStep, Invoice, Product, ProductVariant, Quotation, QuotationLine, Role, User,
)
from core.services import negotiation
from core.views import SCREEN_ROLES, can_see

SCREEN_URLS = {
    "quotations": "core:quotation_list",
    "pipeline": "core:pipeline",
    "approvals": "core:approval_list",
    "fulfilment": "core:fulfilment_list",
    "invoices": "core:billing_list",
    "subscriptions": "core:subscription_list",
    "warehouses": "core:warehouse_list",
    "health": "core:deal_health",
    "reports": "core:reports",
}


def sign_in(email):
    client = Client(SERVER_NAME="localhost")
    client.force_login(User.objects.get(email=email))
    return client


class RoleAccessTests(TestCase):
    """Every role, every screen: reachable and 200, or hidden and 403. Never in between."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def test_each_role_gets_200_on_exactly_the_screens_it_may_see(self):
        for email in [
            "rep@dealflow.test", "manager@dealflow.test",
            "finance@dealflow.test", "admin@dealflow.test",
        ]:
            user = User.objects.get(email=email)
            client = sign_in(email)
            for screen, url_name in SCREEN_URLS.items():
                with self.subTest(role=user.role, screen=screen):
                    response = client.get(reverse(url_name))
                    expected = 200 if can_see(user, screen) else 403
                    self.assertEqual(expected, response.status_code)

    def test_the_sidebar_never_offers_a_link_the_role_cannot_open(self):
        """The bug this guards: a Rep seeing Approvals, clicking it, and getting a 403."""
        for email in ["rep@dealflow.test", "manager@dealflow.test", "finance@dealflow.test"]:
            user = User.objects.get(email=email)
            client = sign_in(email)
            body = client.get(reverse("core:quotation_list")).content.decode()
            for screen, url_name in SCREEN_URLS.items():
                href = 'href="{}"'.format(reverse(url_name))
                with self.subTest(role=user.role, screen=screen):
                    if can_see(user, screen):
                        self.assertIn(href, body)
                    else:
                        self.assertNotIn(href, body)

    def test_every_role_reaches_its_own_profile(self):
        for email in [
            "rep@dealflow.test", "manager@dealflow.test",
            "finance@dealflow.test", "admin@dealflow.test",
        ]:
            client = sign_in(email)
            for tab in ["overview", "activity", "access", "preferences"]:
                with self.subTest(email=email, tab=tab):
                    response = client.get(reverse("core:profile"), {"tab": tab})
                    self.assertEqual(200, response.status_code)

    def test_a_rep_can_read_the_approval_screen_for_their_own_quote(self):
        """PDF section 3 gives the Rep "tracks approval status"; the builder links here."""
        pending = Quotation.objects.filter(stage=Quotation.Stage.PENDING_APPROVAL).first()
        response = sign_in("rep@dealflow.test").get(
            reverse("core:approval_detail", args=[pending.pk])
        )
        self.assertEqual(200, response.status_code)
        self.assertFalse(response.context["actionable"], "a rep must not get the decision form")
        self.assertNotIn("Your decision", response.content.decode())

    def test_a_rep_still_cannot_act_on_an_approval_step(self):
        step = ApprovalStep.objects.filter(status=ApprovalStep.Status.PENDING).first()
        self.assertIsNotNone(step, "the seed must leave an approval step waiting")
        pending = step.quotation
        response = sign_in("rep@dealflow.test").post(
            reverse("core:approval_act", args=[pending.pk]),
            {"step_id": step.pk, "action": "approve", "reason": "nope"},
        )
        self.assertEqual(403, response.status_code)
        step.refresh_from_db()
        self.assertEqual(ApprovalStep.Status.PENDING, step.status)

    def test_a_refused_screen_renders_a_page_not_a_wall_of_text(self):
        response = sign_in("rep@dealflow.test").get(reverse("core:reports"))
        self.assertEqual(403, response.status_code)
        body = response.content.decode()
        self.assertIn("belongs to another role", body)
        self.assertIn(reverse("core:quotation_list"), body)

    def test_every_role_can_open_a_warehouse_and_see_its_products(self):
        """A4: warehouses and their stock are operational data every internal role reads."""
        from core.models import Warehouse

        warehouse = Warehouse.objects.get(name="Main Warehouse")
        for email in ["rep@dealflow.test", "finance@dealflow.test"]:
            with self.subTest(email=email):
                response = sign_in(email).get(
                    reverse("core:warehouse_detail", args=[warehouse.pk])
                )
                self.assertEqual(200, response.status_code)
                self.assertIn("Laptop Pro 14", response.content.decode())

    def test_only_staff_are_offered_the_back_end(self):
        admin_body = sign_in("admin@dealflow.test").get(reverse("core:profile")).content.decode()
        rep_body = sign_in("rep@dealflow.test").get(reverse("core:profile")).content.decode()
        self.assertIn('href="/admin/"', admin_body)
        self.assertNotIn('href="/admin/"', rep_body)

    def test_a_rep_cannot_reach_finance_only_billing_actions(self):
        """PDF section 3 gives credit notes and recurring reconciliation to Finance."""
        hybrid = Quotation.objects.get(number="Q-2026-0140")
        line = hybrid.lines.exclude(line_type=QuotationLine.LineType.ONE_TIME).first()
        response = sign_in("rep@dealflow.test").post(
            reverse("core:subscription_cancel", args=[hybrid.pk, line.pk])
        )
        self.assertEqual(403, response.status_code)
        self.assertTrue(line.billing_schedule.exists(), "the schedule must be untouched")


class QuoteToCashTests(TestCase):
    """PDF section 9, all eight steps, each performed by the role that owns it."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def setUp(self):
        self.rep = sign_in("rep@dealflow.test")
        self.manager = sign_in("manager@dealflow.test")
        self.finance = sign_in("finance@dealflow.test")
        self.quotation = Quotation.objects.get(number="Q-2026-0001")
        self.laptop = Product.objects.get(name="Laptop Pro 14")
        self.service = Product.objects.get(name="Onsite Setup Service")

    def add(self, product):
        response = self.rep.post(
            reverse("core:line_add", args=[self.quotation.pk]), {"product_id": product.pk}
        )
        self.assertEqual(200, response.status_code)
        return self.quotation.lines.get(product=product)

    def test_the_whole_flow_from_empty_draft_to_paid_invoice(self):
        # 2. A line discounted beyond what the category allows.
        laptop_line = self.add(self.laptop)
        self.rep.post(
            reverse("core:line_update", args=[self.quotation.pk, laptop_line.pk]),
            {"qty": "6", "discount_pct": "12"},
        )
        service_line = self.add(self.service)
        self.rep.post(
            reverse("core:line_update", args=[self.quotation.pk, service_line.pk]),
            {"discount_pct": "18"},
        )

        # 4. An upsell suggestion, and the margin moves.
        self.quotation.refresh_from_db()
        margin_before = self.quotation.margin_pct
        care = Product.objects.get(name="Care Plan 2yr")
        self.rep.post(reverse("core:upsell_add", args=[self.quotation.pk]), {"product_id": care.pk})
        self.quotation.refresh_from_db()
        self.assertNotEqual(margin_before, self.quotation.margin_pct)

        # 3. Submitting routes it on its own — the rep never asks for approval.
        self.rep.post(reverse("core:quotation_submit", args=[self.quotation.pk]))
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.PENDING_APPROVAL, self.quotation.stage)
        self.assertGreater(self.quotation.risk_score, 0)

        # A rep cannot approve their own deal, however the URL is reached.
        manager_step = self.quotation.approval_steps.get(level=ApprovalStep.Level.MANAGER)
        self.assertEqual(
            403,
            self.rep.post(
                reverse("core:approval_act", args=[self.quotation.pk]),
                {"step_id": manager_step.pk, "action": "approve", "reason": "me"},
            ).status_code,
        )

        # Manager, then Finance, because the score demanded both.
        self.manager.post(
            reverse("core:approval_act", args=[self.quotation.pk]),
            {"step_id": manager_step.pk, "action": "approve", "reason": "Margin acceptable."},
        )
        finance_step = self.quotation.approval_steps.get(level=ApprovalStep.Level.FINANCE)
        self.finance.post(
            reverse("core:approval_act", args=[self.quotation.pk]),
            {"step_id": finance_step.pk, "action": "approve", "reason": "Cleared."},
        )
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.APPROVED, self.quotation.stage)

        # 5. Six laptops cannot come from one warehouse, so the split runs.
        self.rep.post(reverse("core:fulfilment_accept", args=[self.quotation.pk]))
        self.quotation.refresh_from_db()
        warehouses = {a.warehouse_id for a in self.quotation.allocations.all()}
        self.assertGreaterEqual(len(warehouses), 2, "the demo order must split")

        # 6. One-time and recurring bill separately.
        self.rep.post(reverse("core:billing_generate", args=[self.quotation.pk]))
        invoice = self.quotation.invoices.get(is_credit_note=False)
        self.assertTrue(self.quotation.billing_schedule.exists(), "recurring line needs a schedule")
        billed_products = {
            entry.quotation_line.product_id for entry in self.quotation.billing_schedule.all()
        }
        self.assertEqual({care.pk}, billed_products, "only the recurring line is scheduled")

        # 8. Payment, and the status derives itself.
        self.rep.post(
            reverse("core:billing_pay", args=[self.quotation.pk]),
            {"amount": str(invoice.amount), "method": "BANK_TRANSFER"},
        )
        invoice.refresh_from_db()
        self.quotation.refresh_from_db()
        self.assertEqual(Invoice.Status.PAID, invoice.status)
        self.assertEqual(Quotation.Stage.PAID, self.quotation.stage)

    def test_the_customer_portal_counter_offer_re_enters_approval(self):
        """PDF section 9 step 7, driven by the customer, who has no account at all."""
        quotation = Quotation.objects.get(number="Q-2026-0002")
        portal_path = negotiation.portal_link(quotation, None)
        anonymous = Client(SERVER_NAME="localhost")

        self.assertEqual(200, anonymous.get(portal_path).status_code)

        line = quotation.lines.first()
        anonymous.post(
            portal_path + "comment/",
            {"line_id": line.pk, "body": "Can you do better on the service?"},
        )
        anonymous.post(
            portal_path + "counter/",
            {"line_id": line.pk, "counter_discount_pct": "15",
             "body": "15% and we sign today."},
        )
        quotation.refresh_from_db()
        self.assertIn(
            quotation.stage,
            {Quotation.Stage.UNDER_NEGOTIATION, Quotation.Stage.PENDING_APPROVAL},
        )
        self.assertTrue(quotation.approval_steps.exists(), "the counter must re-open approval")

    def test_the_portal_leaks_no_internal_navigation(self):
        quotation = Quotation.objects.get(number="Q-2026-0002")
        body = Client(SERVER_NAME="localhost").get(
            negotiation.portal_link(quotation, None)
        ).content.decode()
        for internal in ["/workspace/", "/admin/", "Deal Health", "Reports", "Sign out"]:
            self.assertNotIn(internal, body)
