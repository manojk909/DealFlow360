"""ADR-016 — solving for the approvable discount.

The approval screen already answers *why* a quotation was flagged. This answers the
question the approver actually has: **what would make it approvable?** Every commercial
CPQ judges a discount; none of them solve for the one that clears.

The property that matters is that the suggestion is *correct* — apply it and the quotation
really does land in the promised band. So these tests do not check arithmetic in the
abstract: they take the suggested number, write it onto the line, re-score through the same
function the rest of the application uses, and assert the band actually moved.
"""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ApprovalChainRule, Category, CategoryDiscountCeiling, Customer, CustomerTier,
    Product, Quotation, QuotationLine, Role, User,
)
from core.services import pricing, risk


class HeadroomTestCase(TestCase):
    def setUp(self):
        self.gold = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        self.hardware = Category.objects.create(name="Hardware")
        self.services = Category.objects.create(name="Services")
        CategoryDiscountCeiling.objects.create(
            tier=self.gold, category=self.hardware, max_discount_pct=Decimal("15")
        )
        CategoryDiscountCeiling.objects.create(
            tier=self.gold, category=self.services, max_discount_pct=Decimal("10")
        )
        # Bands: 0 auto · up to 8 manager · beyond that manager then finance.
        ApprovalChainRule.objects.create(score_min=Decimal("0"), score_max=Decimal("0"))
        ApprovalChainRule.objects.create(
            score_min=Decimal("0.01"), score_max=Decimal("8.00"), requires_manager=True
        )
        ApprovalChainRule.objects.create(
            score_min=Decimal("8.01"), score_max=Decimal("9999"),
            requires_manager=True, requires_finance=True,
        )
        self.customer = Customer.objects.create(
            name="Acme", email="a@a.test", tier=self.gold
        )
        self.rep = User.objects.create_user(
            email="rep@hr.test", password="x", name="Rep", role=Role.REP
        )
        self.laptop = Product.objects.create(
            name="Laptop", category=self.hardware,
            list_price=Decimal("1000"), cost=Decimal("600"),
        )
        self.setup = Product.objects.create(
            name="Setup", category=self.services,
            list_price=Decimal("1000"), cost=Decimal("500"),
        )
        self.quotation = Quotation.objects.create(
            number="Q-HR-1", customer=self.customer, rep=self.rep,
            last_activity_at=timezone.now(),
        )

    def add(self, product, discount):
        line = QuotationLine.objects.create(
            quotation=self.quotation, product=product, qty=1,
            unit_price=product.list_price, discount_pct=Decimal(discount),
        )
        pricing.recompute_quotation(self.quotation)
        return line

    def score(self):
        return risk.score_for_quotation(self.quotation).score

    def apply(self, line, discount):
        line.discount_pct = Decimal(discount)
        line.save(update_fields=["discount_pct"])
        pricing.recompute_quotation(self.quotation)


class SuggestionCorrectnessTests(HeadroomTestCase):
    """Take the suggestion, apply it, re-score. The band must actually move."""

    def test_the_suggested_discount_really_reaches_auto_approval(self):
        line = self.add(self.setup, "18")  # 8 points over a 10% ceiling
        self.assertEqual(Decimal("8.00"), self.score())

        suggestion = risk.what_would_clear_this(self.quotation)[0]
        auto = next(t for t in suggestion["targets"] if t["label"] == "Auto-approved")

        self.apply(line, auto["max_discount_pct"])
        self.assertEqual(Decimal("0.00"), self.score())

    def test_a_hundredth_above_the_suggestion_does_not_clear(self):
        """Proves the suggestion is the *maximum*, not merely a safe number."""
        line = self.add(self.setup, "18")
        suggestion = risk.what_would_clear_this(self.quotation)[0]
        auto = next(t for t in suggestion["targets"] if t["label"] == "Auto-approved")

        self.apply(line, auto["max_discount_pct"] + Decimal("0.01"))
        self.assertGreater(self.score(), Decimal("0.00"))

    def test_the_manager_only_suggestion_lands_inside_the_manager_band(self):
        line = self.add(self.setup, "30")  # 20 over — manager and finance
        self.assertGreater(self.score(), Decimal("8.00"))

        suggestion = risk.what_would_clear_this(self.quotation)[0]
        manager = next(t for t in suggestion["targets"] if t["label"] == "Sales Manager only")

        self.apply(line, manager["max_discount_pct"])
        score = self.score()
        self.assertGreater(score, Decimal("0"))
        self.assertLessEqual(score, Decimal("8.00"))

    def test_it_rounds_down_never_up(self):
        """A suggestion that rounds up is a suggestion that gets rejected on submit."""
        self.quotation.order_discount_pct = Decimal("7")
        self.quotation.save(update_fields=["order_discount_pct"])
        line = self.add(self.setup, "25")

        suggestion = risk.what_would_clear_this(self.quotation)[0]
        auto = next(t for t in suggestion["targets"] if t["label"] == "Auto-approved")
        self.apply(line, auto["max_discount_pct"])
        self.assertLessEqual(self.score(), Decimal("0.00"))


class BlendingTests(HeadroomTestCase):
    """A line's allowance depends on what the others already spent. That is the blend."""

    def test_one_lines_headroom_shrinks_when_another_line_spends_it(self):
        # 30% is 20 points over a 10% ceiling, so the quotation sits in the dearest band
        # and "Sales Manager only" is genuinely a cheaper one to aim at. At 18% it is
        # already the current band, and a band is not offered as a target of itself.
        alone = self.add(self.setup, "30")
        first = risk.what_would_clear_this(self.quotation)[0]
        manager_alone = next(
            t for t in first["targets"] if t["label"] == "Sales Manager only"
        )["max_discount_pct"]

        # A second line eats into the shared budget.
        self.add(self.laptop, "20")  # 5 over its own 15% ceiling
        again = next(
            s for s in risk.what_would_clear_this(self.quotation)
            if s["line"].pk == alone.pk
        )
        manager_shared = next(
            t for t in again["targets"] if t["label"] == "Sales Manager only"
        )["max_discount_pct"]

        self.assertLess(manager_shared, manager_alone)

    def test_a_band_is_unreachable_when_the_other_lines_have_already_spent_it(self):
        """No discount on this line, not even zero, can bring the quotation back."""
        self.add(self.laptop, "40")  # 25 over on its own — past every cheap band
        setup_line = self.add(self.setup, "12")

        suggestion = next(
            s for s in risk.what_would_clear_this(self.quotation)
            if s["line"].pk == setup_line.pk
        )
        labels = [t["label"] for t in suggestion["targets"]]
        self.assertNotIn("Auto-approved", labels)

    def test_the_worst_line_is_suggested_first(self):
        self.add(self.laptop, "18")   # 3 over
        worst = self.add(self.setup, "28")  # 18 over
        suggestions = risk.what_would_clear_this(self.quotation)
        self.assertEqual(worst.pk, suggestions[0]["line"].pk)


class QuietQuotationTests(HeadroomTestCase):
    def test_a_clean_quotation_has_nothing_to_suggest(self):
        self.add(self.laptop, "12")
        self.assertEqual([], risk.what_would_clear_this(self.quotation))

    def test_lines_inside_their_ceiling_are_not_suggested(self):
        self.add(self.laptop, "10")   # inside
        over = self.add(self.setup, "18")
        suggestions = risk.what_would_clear_this(self.quotation)
        self.assertEqual([over.pk], [s["line"].pk for s in suggestions])


class ApprovalScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def test_the_approver_is_shown_the_number_that_would_clear(self):
        manager = User.objects.get(email="manager@dealflow.test")
        client = Client(SERVER_NAME="localhost")
        client.force_login(manager)

        flagged = Quotation.objects.filter(
            stage=Quotation.Stage.PENDING_APPROVAL, risk_score__gt=0
        ).first()
        response = client.get(reverse("core:approval_detail", args=[flagged.pk]))

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.context["clearing"], "no suggestion offered on a flagged quote")
        self.assertIn("would clear", response.content.decode().lower())
