"""Regression guard: internal template comments must never reach the page.

Django's `{# ... #}` comment syntax is **single-line only**. A `{# ... #}` block that spans
a newline is not treated as a comment at all — the engine emits it verbatim — so developer
notes about HTMX targets and CDN fallbacks appeared on the rendered workspace. Multi-line
comments must use `{% comment %} ... {% endcomment %}`.

Two tests: one reads the template sources so the mistake cannot be reintroduced, one
renders every screen and asserts nothing comment-shaped comes back.
"""

import pathlib
import re
from decimal import Decimal

from django.test import Client, TestCase

from core.models import (
    ApprovalChainRule,
    Category,
    CategoryDiscountCeiling,
    Customer,
    CustomerTier,
    Product,
    Quotation,
    QuotationLine,
    Role,
    Stock,
    User,
    Warehouse,
)

BLOCK = re.compile(r"\{#(.*?)#\}", re.S)
TEMPLATE_ROOTS = [
    pathlib.Path(__file__).resolve().parent.parent / "templates",
    pathlib.Path(__file__).resolve().parent.parent.parent / "portal",
]


class TemplateCommentSyntaxTests(TestCase):
    """Source-level: no multi-line {# #} may exist in any template."""

    def test_no_multiline_hash_comments_anywhere(self):
        offenders = []
        for root in TEMPLATE_ROOTS:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.html")):
                source = path.read_text(encoding="utf-8")
                for match in BLOCK.finditer(source):
                    if "\n" in match.group(0):
                        offenders.append(f"{path.name}: {match.group(0)[:60]!r}")
        self.assertEqual(
            [],
            offenders,
            "Django's {# #} is single-line only; a multi-line one renders as visible "
            "text. Use {% comment %} ... {% endcomment %} instead.",
        )


class RenderedPagesAreCleanTests(TestCase):
    """Rendered output: no comment delimiters, no known internal phrases."""

    LEAK_MARKERS = [
        "{#",
        "#}",
        "{% comment %}",
        "{% endcomment %}",
        "hx-headers here rather than",
        "Minimal fallback so the app",
        "The live region",
        "Named in the mockup, not built yet",
        "Full-width chrome",
        "Replaces Django's flat alphabetical",
    ]

    def setUp(self):
        tier = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        hardware = Category.objects.create(name="Hardware")
        CategoryDiscountCeiling.objects.create(
            tier=tier, category=hardware, max_discount_pct=Decimal("15")
        )
        ApprovalChainRule.objects.create(
            score_min=Decimal("0.00"), score_max=Decimal("0.00")
        )
        ApprovalChainRule.objects.create(
            score_min=Decimal("0.01"), score_max=Decimal("9999.99"),
            requires_manager=True,
        )
        customer = Customer.objects.create(name="Acme", email="a@a.test", tier=tier)
        self.admin = User.objects.create_superuser(
            email="a@t.test", password="pw", name="Admin"
        )
        product = Product.objects.create(
            name="Laptop", category=hardware,
            list_price=Decimal("1000"), cost=Decimal("600"),
        )
        warehouse = Warehouse.objects.create(
            name="Main", shipping_cost_weight=Decimal("1.00")
        )
        Stock.objects.create(product=product, warehouse=warehouse, qty_on_hand=10)

        self.quotation = Quotation.objects.create(
            number="Q-T-1", customer=customer, rep=self.admin,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        QuotationLine.objects.create(
            quotation=self.quotation, product=product, qty=1,
            unit_price=Decimal("1000"), discount_pct=Decimal("0"),
        )

        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.admin)

    def assert_clean(self, url, body):
        for marker in self.LEAK_MARKERS:
            self.assertNotIn(
                marker, body, f"internal comment text leaked onto {url}: {marker!r}"
            )

    def test_every_workspace_screen_renders_without_leaking_comments(self):
        pk = self.quotation.pk
        # /login/ redirects for an authenticated user, so it is checked signed out.
        anonymous = Client(SERVER_NAME="localhost")
        response = anonymous.get("/login/")
        self.assertEqual(200, response.status_code)
        self.assert_clean("/login/", response.content.decode())

        urls = [
            "/health/",
            "/workspace/",
            f"/workspace/quotations/{pk}/",
            "/workspace/approvals/",
            "/workspace/fulfilment/",
            f"/workspace/fulfilment/{pk}/",
            "/workspace/invoices/",
            f"/workspace/invoices/{pk}/",
            "/admin/",
            "/admin/core/quotation/",
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(200, response.status_code, url)
                self.assert_clean(url, response.content.decode())

    def test_the_htmx_partial_is_clean_too(self):
        """The builder partial is swapped in on every edit, so it leaks separately."""
        line = self.quotation.lines.first()
        response = self.client.post(
            f"/workspace/quotations/{self.quotation.pk}/lines/{line.pk}/",
            {"discount_pct": "5"},
        )
        self.assertEqual(200, response.status_code)
        self.assert_clean("builder partial", response.content.decode())
