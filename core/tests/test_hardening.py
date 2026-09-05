"""T-26: input validation, no external dependencies, and layout containment.

Odoo scores validation, navigation and a clean responsive UI regardless of features, so
these are asserted rather than assumed.

**Honest scope note.** No browser runs here, so "responsive" is tested as *markup
containment* — every wide element scrolls inside its own container rather than the page,
and no fixed pixel width exceeds a 375px viewport. That is a real class of horizontal-scroll
bug caught mechanically. It is not a substitute for looking at the screens, which is what
the demo rehearsal is for.
"""

import pathlib
import re
from decimal import Decimal

from django.test import Client, TestCase

from core.models import (
    ApprovalChainRule, Category, CategoryDiscountCeiling, Customer, CustomerTier,
    Invoice, Product, Quotation, QuotationLine, Role, Stock, User, Warehouse,
)
from core.services import approval, billing, fulfilment, pricing

TEMPLATE_ROOTS = [
    pathlib.Path(__file__).resolve().parent.parent / "templates",
    pathlib.Path(__file__).resolve().parent.parent.parent / "portal" / "templates",
]


def all_templates():
    for root in TEMPLATE_ROOTS:
        if root.exists():
            yield from sorted(root.rglob("*.html"))


class NoExternalDependenciesTests(TestCase):
    """The demo must not depend on venue wifi."""

    def test_no_template_loads_anything_from_a_cdn(self):
        offenders = []
        for path in all_templates():
            source = path.read_text(encoding="utf-8")
            for host in ["cdn.tailwindcss.com", "unpkg.com", "cdnjs.cloudflare.com",
                         "jsdelivr.net", "code.jquery.com", "fonts.googleapis.com"]:
                if host in source:
                    offenders.append(f"{path.name} -> {host}")
        self.assertEqual([], offenders, "vendored assets only; see T-26")

    def test_no_template_references_an_absolute_http_url_for_an_asset(self):
        pattern = re.compile(r'(?:src|href)=["\']https?://')
        offenders = [
            path.name for path in all_templates()
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual([], offenders)

    def test_the_vendored_files_exist_and_are_real(self):
        vendor = pathlib.Path(__file__).resolve().parent.parent / "static" / "vendor"
        tailwind = vendor / "tailwind.js"
        htmx = vendor / "htmx.min.js"
        self.assertTrue(tailwind.exists(), "core/static/vendor/tailwind.js is missing")
        self.assertTrue(htmx.exists(), "core/static/vendor/htmx.min.js is missing")
        self.assertGreater(tailwind.stat().st_size, 100_000)
        self.assertGreater(htmx.stat().st_size, 20_000)
        self.assertIn("htmx", htmx.read_text(encoding="utf-8", errors="ignore")[:200])


class LayoutContainmentTests(TestCase):
    """No element may be wider than a 375px viewport, and wide content scrolls itself."""

    VIEWPORT = 375

    def test_every_table_scrolls_inside_its_own_container(self):
        offenders = []
        for path in all_templates():
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"<table", source):
                window = source[max(0, match.start() - 400):match.start()]
                if "overflow-x-auto" not in window:
                    offenders.append(f"{path.name} @ {match.start()}")
        self.assertEqual(
            [], offenders,
            "a wide table must scroll in its own overflow-x-auto container, not the page",
        )

    def test_no_fixed_pixel_width_exceeds_the_narrowest_viewport(self):
        offenders = []
        for path in all_templates():
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\b(?:min-)?w-\[(\d+)px\]", source):
                if int(match.group(1)) > self.VIEWPORT:
                    offenders.append(f"{path.name}: {match.group(0)}")
            for match in re.finditer(r'style="[^"]*width:\s*(\d+)px', source):
                if int(match.group(1)) > self.VIEWPORT:
                    offenders.append(f"{path.name}: inline {match.group(1)}px")
        self.assertEqual([], offenders)

    def test_every_page_declares_the_viewport_meta(self):
        for path in all_templates():
            source = path.read_text(encoding="utf-8")
            # `<head` alone also matches `<header>`, which is why this is a regex.
            if re.search(r"<head[\s>]", source):
                self.assertIn("width=device-width", source, path.name)


class FormValidationTests(TestCase):
    """Every form refuses bad input with a visible message, never a 500."""

    def setUp(self):
        tier = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        hardware = Category.objects.create(name="Hardware")
        CategoryDiscountCeiling.objects.create(
            tier=tier, category=hardware, max_discount_pct=Decimal("15")
        )
        ApprovalChainRule.objects.create(score_min=Decimal("0.00"), score_max=Decimal("0.00"))
        ApprovalChainRule.objects.create(
            score_min=Decimal("0.01"), score_max=Decimal("9999.99"), requires_manager=True
        )
        customer = Customer.objects.create(name="Acme", email="a@a.test", tier=tier)
        self.rep = User.objects.create_user(
            email="rep@h.test", password="x", name="Rep", role=Role.REP
        )
        self.manager = User.objects.create_user(
            email="mgr@h.test", password="x", name="Mgr", role=Role.MANAGER
        )
        product = Product.objects.create(
            name="Laptop", category=hardware,
            list_price=Decimal("1000"), cost=Decimal("600"),
        )
        self.warehouse = Warehouse.objects.create(
            name="Main", shipping_cost_weight=Decimal("1.00")
        )
        Stock.objects.create(product=product, warehouse=self.warehouse, qty_on_hand=10)

        self.quotation = Quotation.objects.create(
            number="Q-H-1", customer=customer, rep=self.rep,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        self.line = QuotationLine.objects.create(
            quotation=self.quotation, product=product, qty=2,
            unit_price=Decimal("1000"), discount_pct=Decimal("0"),
        )
        pricing.recompute_quotation(self.quotation)

        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.rep)

    def assert_refused_with_a_message(self, response, needle=None, client=None):
        """Follow the redirect with the SAME client that made the request.

        Using self.client here silently followed a manager's redirect as the rep and got
        a 403 instead of the message. The bug was in the test, not the application.
        """
        self.assertLess(response.status_code, 500, "a bad input must not 500")
        if response.status_code == 302:
            response = (client or self.client).get(response.headers["Location"])
        body = response.content.decode()
        if needle:
            self.assertIn(needle, body)
        return body

    def test_line_discount_above_100_is_refused_with_a_message(self):
        r = self.client.post(
            f"/workspace/quotations/{self.quotation.pk}/lines/{self.line.pk}/",
            {"discount_pct": "150"},
        )
        self.assertEqual(400, r.status_code)
        self.assert_refused_with_a_message(r, "at most 100")

    def test_a_non_numeric_discount_is_refused(self):
        r = self.client.post(
            f"/workspace/quotations/{self.quotation.pk}/lines/{self.line.pk}/",
            {"discount_pct": "twelve"},
        )
        self.assertEqual(400, r.status_code)
        self.assert_refused_with_a_message(r, "must be a number")

    def test_a_zero_quantity_is_refused(self):
        r = self.client.post(
            f"/workspace/quotations/{self.quotation.pk}/lines/{self.line.pk}/",
            {"qty": "0"},
        )
        self.assertEqual(400, r.status_code)
        self.assert_refused_with_a_message(r, "at least 1")

    def test_an_order_discount_above_100_is_refused(self):
        r = self.client.post(
            f"/workspace/quotations/{self.quotation.pk}/order-discount/",
            {"order_discount_pct": "500"},
        )
        self.assertEqual(400, r.status_code)
        self.assert_refused_with_a_message(r, "at most 100")

    def test_an_approval_with_a_blank_reason_is_refused_with_a_message(self):
        self.line.discount_pct = Decimal("40")
        self.line.save(update_fields=["discount_pct"])
        approval.submit(self.quotation, self.rep)
        self.quotation.refresh_from_db()
        step = self.quotation.approval_steps.get(level="MANAGER")

        mgr = Client(SERVER_NAME="localhost")
        mgr.force_login(self.manager)
        r = mgr.post(f"/workspace/approvals/{self.quotation.pk}/act/",
                     {"step_id": step.pk, "action": "approve", "reason": "  "})
        self.assert_refused_with_a_message(r, "reason is required", client=mgr)
        step.refresh_from_db()
        self.assertEqual("PENDING", step.status)

    def test_a_manual_override_beyond_stock_is_refused_with_a_message(self):
        self.quotation.stage = Quotation.Stage.APPROVED
        self.quotation.save(update_fields=["stage"])
        r = self.client.post(
            f"/workspace/fulfilment/{self.quotation.pk}/override/",
            {"line_id": self.line.pk, f"wh_{self.warehouse.pk}": "999"},
        )
        self.assert_refused_with_a_message(r, "available")

    def test_an_overpayment_is_refused_with_a_message(self):
        self.quotation.stage = Quotation.Stage.FULFILLED
        self.quotation.save(update_fields=["stage"])
        invoice = billing.generate_invoice(self.quotation)
        r = self.client.post(
            f"/workspace/invoices/{self.quotation.pk}/pay/",
            {"amount": str(invoice.amount + Decimal("10")), "method": "CARD"},
        )
        self.assert_refused_with_a_message(r, "overpay")
        self.assertEqual(0, Invoice.objects.get(pk=invoice.pk).payments.count())

    def test_a_zero_payment_is_refused(self):
        self.quotation.stage = Quotation.Stage.FULFILLED
        self.quotation.save(update_fields=["stage"])
        billing.generate_invoice(self.quotation)
        r = self.client.post(
            f"/workspace/invoices/{self.quotation.pk}/pay/", {"amount": "0"}
        )
        self.assert_refused_with_a_message(r, "at least")

    def test_a_portal_counter_out_of_range_is_refused_with_a_message(self):
        from django.core import signing

        self.quotation.stage = Quotation.Stage.SENT
        self.quotation.portal_token = signing.TimestampSigner().sign(str(self.quotation.pk))
        self.quotation.save(update_fields=["stage", "portal_token"])

        buyer = Client(SERVER_NAME="localhost")
        r = buyer.post(f"/portal/{self.quotation.portal_token}/counter/",
                       {"counter_discount_pct": "250"})
        body = self.assert_refused_with_a_message(r)
        self.assertIn("between 0 and 100", body)

    def test_a_portal_counter_that_is_not_a_number_is_refused(self):
        from django.core import signing

        self.quotation.stage = Quotation.Stage.SENT
        self.quotation.portal_token = signing.TimestampSigner().sign(str(self.quotation.pk))
        self.quotation.save(update_fields=["stage", "portal_token"])

        buyer = Client(SERVER_NAME="localhost")
        r = buyer.post(f"/portal/{self.quotation.portal_token}/counter/",
                       {"counter_discount_pct": "a lot"})
        body = self.assert_refused_with_a_message(r)
        self.assertIn("as a number", body)

    def test_an_empty_portal_comment_is_refused(self):
        from django.core import signing

        self.quotation.stage = Quotation.Stage.SENT
        self.quotation.portal_token = signing.TimestampSigner().sign(str(self.quotation.pk))
        self.quotation.save(update_fields=["stage", "portal_token"])

        buyer = Client(SERVER_NAME="localhost")
        r = buyer.post(f"/portal/{self.quotation.portal_token}/comment/", {"body": "   "})
        body = self.assert_refused_with_a_message(r)
        self.assertIn("cannot be empty", body)
