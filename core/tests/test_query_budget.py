"""Every list screen must cost a fixed number of queries, whatever the row count.

This is the test for "can it handle traffic". A page that issues one extra query per row
looks instant on seed data and falls over at a few thousand rows, and no amount of
profiling on a demo database reveals it. So the budget is asserted directly: load the
screen with the seeded data, load it again with an order of magnitude more, and require
the query count to be identical.

Three real N+1 loops were found this way and removed:

* `fulfilment_list` fetched each order's allocations inside the loop — 18 queries to 5.
* `subscription_list` called `upcoming_schedule()` and `.count()` per order — 13 to 5.
* `resolve_unit_price()` used `.filter()` on a related manager, which ignores a prefetch,
  so the upsell panel spent one query per suggestion.

The numbers below are ceilings, not targets. Tightening one is welcome; exceeding one
means a loop went back into a view, and the test names which screen.
"""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Customer, Product, Quotation, QuotationLine, Role, User

# Screen -> the most queries it may issue. Measured, then rounded up by a little.
BUDGET = {
    "core:quotation_list": 6,
    "core:pipeline": 6,
    "core:approval_list": 7,
    "core:fulfilment_list": 9,
    "core:billing_list": 10,
    "core:subscription_list": 9,
    "core:warehouse_list": 6,
    "core:reports": 12,
    "core:deal_health": 16,
    "core:profile": 9,
    "core:customer_list": 6,
    "core:renewal_list": 8,
}


class QueryBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def setUp(self):
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(User.objects.get(email="admin@dealflow.test"))

    def bulk_quotations(self, count):
        """Add `count` quotations with lines, cheaply, to move the row count by 10x."""
        rep = User.objects.filter(role=Role.REP).first()
        customer = Customer.objects.first()
        product = Product.objects.filter(subscription_plan__isnull=True).first()
        now = timezone.now()

        quotations = Quotation.objects.bulk_create(
            [
                Quotation(
                    number=f"Q-BULK-{index:05d}",
                    customer=customer,
                    rep=rep,
                    stage=Quotation.Stage.SENT,
                    last_activity_at=now,
                    subtotal=Decimal("100"),
                    total=Decimal("100"),
                )
                for index in range(count)
            ]
        )
        QuotationLine.objects.bulk_create(
            [
                QuotationLine(
                    quotation=quotation, product=product, qty=1,
                    unit_price=Decimal("100"), line_total=Decimal("100"),
                )
                for quotation in quotations
            ]
        )

    def measure(self, name):
        """Queries issued by one warm request. `assertNumQueries` is exact; this is a ceiling."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.get(reverse(name))  # warm any lazily created singleton row
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(200, self.client.get(reverse(name)).status_code)
        return len(captured)

    def test_every_screen_is_inside_its_query_budget(self):
        for name, budget in BUDGET.items():
            with self.subTest(screen=name):
                self.assertLessEqual(
                    self.measure(name), budget,
                    f"{name} exceeded its query budget of {budget}",
                )

    def test_query_counts_do_not_grow_with_the_number_of_quotations(self):
        """The property that decides whether this survives real traffic."""
        before = {name: self.measure(name) for name in BUDGET}
        self.bulk_quotations(250)
        self.assertGreater(Quotation.objects.count(), 250)
        after = {name: self.measure(name) for name in BUDGET}

        grew = {
            name: (before[name], after[name])
            for name in BUDGET
            if after[name] > before[name]
        }
        self.assertEqual({}, grew, f"query count grew with row count: {grew}")

    def test_the_quotation_builder_does_not_query_per_line(self):
        """The busiest screen: adding lines must not add queries."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        draft = Quotation.objects.filter(stage=Quotation.Stage.DRAFT).first()
        product = Product.objects.filter(subscription_plan__isnull=True).first()
        url = reverse("core:quotation_builder", args=[draft.pk])

        QuotationLine.objects.create(
            quotation=draft, product=product, qty=1,
            unit_price=Decimal("100"), line_total=Decimal("100"),
        )
        self.client.get(url)
        with CaptureQueriesContext(connection) as one_line:
            self.client.get(url)

        for _ in range(10):
            QuotationLine.objects.create(
                quotation=draft, product=product, qty=1,
                unit_price=Decimal("100"), line_total=Decimal("100"),
            )
        self.client.get(url)
        with CaptureQueriesContext(connection) as eleven_lines:
            self.client.get(url)

        self.assertLessEqual(
            len(eleven_lines), len(one_line),
            f"the builder queries per line: {len(one_line)} -> {len(eleven_lines)}",
        )
