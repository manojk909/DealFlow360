"""Regression tests for two bugs found by clicking through the running app (T-36).

Both survived a 170-test suite because both live in the gap between "the service refuses
it" and "the screen says so":

1. **Sign-out was a GET.** `LogoutView` has rejected GET since Django 5.0, so the
   workspace's sign-out control returned a 405 error page and left the session signed in.
   Nothing in the suite referenced logout at all, and the demo needs three role switches.

2. **Locked quotations were still editable over HTTP.** The builder page hid the product
   picker once a quotation left DRAFT, but `line_add`, `line_update`, `line_delete`,
   `order_discount` and `upsell_add` never checked the stage. Anything able to reach the
   URL could change quantities and discounts on a quotation already sitting in approval,
   which is precisely the governance the product claims to enforce.
"""

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from core.models import (
    ApprovalChainRule, Category, CategoryDiscountCeiling, Customer, CustomerTier,
    Product, Quotation, QuotationLine, Role, User,
)
from core.services import pricing


class StageLockTestCase(TestCase):
    def setUp(self):
        tier = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        self.hardware = Category.objects.create(name="Hardware")
        CategoryDiscountCeiling.objects.create(
            tier=tier, category=self.hardware, max_discount_pct=Decimal("15")
        )
        ApprovalChainRule.objects.create(score_min=Decimal("0.00"), score_max=Decimal("0.00"))
        ApprovalChainRule.objects.create(
            score_min=Decimal("0.01"), score_max=Decimal("9999.99"), requires_manager=True
        )
        customer = Customer.objects.create(name="Acme", email="a@a.test", tier=tier)
        self.rep = User.objects.create_user(
            email="rep@lock.test", password="x", name="Rep", role=Role.REP
        )
        self.product = Product.objects.create(
            name="Laptop", category=self.hardware,
            list_price=Decimal("1000"), cost=Decimal("600"),
        )
        self.quotation = Quotation.objects.create(
            number="Q-LOCK-1", customer=customer, rep=self.rep,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        self.line = QuotationLine.objects.create(
            quotation=self.quotation, product=self.product, qty=2,
            unit_price=Decimal("1000"), discount_pct=Decimal("0"),
        )
        pricing.recompute_quotation(self.quotation)

        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.rep)

    def lock(self, stage=Quotation.Stage.PENDING_APPROVAL):
        self.quotation.stage = stage
        self.quotation.save(update_fields=["stage"])


class SignOutTests(StageLockTestCase):
    def test_the_workspace_offers_sign_out_as_a_post_form_not_a_link(self):
        """A GET link here renders a 405 page and leaves the user signed in."""
        body = self.client.get(reverse("core:quotation_list")).content.decode()
        self.assertIn('action="{}"'.format(reverse("core:logout")), body)
        self.assertNotIn('href="{}"'.format(reverse("core:logout")), body)

    def test_posting_to_logout_actually_ends_the_session(self):
        self.client.post(reverse("core:logout"))
        response = self.client.get(reverse("core:quotation_list"))
        self.assertEqual(302, response.status_code)
        self.assertIn(reverse("core:login"), response["Location"])


class LockedQuotationTests(StageLockTestCase):
    """A quotation past DRAFT is read-only, and the endpoints — not the template — say so."""

    def test_quantity_cannot_be_changed_once_pending_approval(self):
        self.lock()
        response = self.client.post(
            reverse("core:line_update", args=[self.quotation.pk, self.line.pk]),
            {"qty": "9"},
        )
        self.assertEqual(409, response.status_code)
        self.line.refresh_from_db()
        self.assertEqual(2, self.line.qty)

    def test_discount_cannot_be_changed_once_pending_approval(self):
        self.lock()
        response = self.client.post(
            reverse("core:line_update", args=[self.quotation.pk, self.line.pk]),
            {"discount_pct": "40"},
        )
        self.assertEqual(409, response.status_code)
        self.line.refresh_from_db()
        self.assertEqual(Decimal("0"), self.line.discount_pct)

    def test_a_line_cannot_be_deleted_once_pending_approval(self):
        self.lock()
        response = self.client.post(
            reverse("core:line_delete", args=[self.quotation.pk, self.line.pk])
        )
        self.assertEqual(409, response.status_code)
        self.assertTrue(QuotationLine.objects.filter(pk=self.line.pk).exists())

    def test_a_line_cannot_be_added_once_pending_approval(self):
        self.lock()
        response = self.client.post(
            reverse("core:line_add", args=[self.quotation.pk]),
            {"product_id": self.product.pk},
        )
        self.assertEqual(409, response.status_code)
        self.assertEqual(1, self.quotation.lines.count())

    def test_the_order_discount_cannot_be_changed_once_pending_approval(self):
        self.lock()
        response = self.client.post(
            reverse("core:order_discount", args=[self.quotation.pk]),
            {"order_discount_pct": "25"},
        )
        self.assertEqual(409, response.status_code)
        self.quotation.refresh_from_db()
        self.assertEqual(Decimal("0"), self.quotation.order_discount_pct)

    def test_the_refusal_is_visible_rather_than_silent(self):
        """The 409 carries the re-rendered live region, so the user is told why."""
        self.lock()
        response = self.client.post(
            reverse("core:line_update", args=[self.quotation.pk, self.line.pk]),
            {"qty": "9"},
        )
        self.assertIn("locked", response.content.decode().lower())

    def test_a_draft_is_still_editable(self):
        """The guard must not lock the stage the rep actually works in."""
        response = self.client.post(
            reverse("core:line_update", args=[self.quotation.pk, self.line.pk]),
            {"qty": "5"},
        )
        self.assertEqual(200, response.status_code)
        self.line.refresh_from_db()
        self.assertEqual(5, self.line.qty)

    def test_a_quotation_under_negotiation_is_still_editable(self):
        """The portal counter-offer loop depends on this stage staying writable."""
        self.lock(Quotation.Stage.UNDER_NEGOTIATION)
        response = self.client.post(
            reverse("core:line_update", args=[self.quotation.pk, self.line.pk]),
            {"qty": "4"},
        )
        self.assertEqual(200, response.status_code)
        self.line.refresh_from_db()
        self.assertEqual(4, self.line.qty)
