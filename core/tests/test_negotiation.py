"""Portal negotiation and the re-approval loop (T-15, BR-6, AC-7).

The behaviour that matters: a customer action, taken with no user account, moves an
internal deal back into governance on its own — and the counter **replaces** a line's
discount rather than stacking on it, which is what keeps DEMO Flow B to one approver.
"""

from decimal import Decimal

from django.test import TestCase

from core.models import (
    ApprovalChainRule,
    ApprovalStep,
    AuditLog,
    Category,
    CategoryDiscountCeiling,
    Customer,
    CustomerTier,
    PortalMessage,
    Product,
    Quotation,
    QuotationLine,
    Role,
    User,
)
from core.services import negotiation, pricing


class NegotiationTestCase(TestCase):
    def setUp(self):
        self.silver = CustomerTier.objects.create(
            name="Silver", max_discount_pct=Decimal("10")
        )
        self.hardware = Category.objects.create(name="Hardware")
        self.services = Category.objects.create(name="Services")
        for lo, hi, mgr, fin in [
            ("0.00", "0.00", False, False),
            ("0.01", "7.99", True, False),
            ("8.00", "9999.99", True, True),
        ]:
            ApprovalChainRule.objects.create(
                score_min=Decimal(lo), score_max=Decimal(hi),
                requires_manager=mgr, requires_finance=fin,
            )
        self.customer = Customer.objects.create(
            name="Beta Industries", email="b@b.test", tier=self.silver
        )
        self.rep = User.objects.create_user(
            email="rep@n.test", password="x", name="Rep", role=Role.REP
        )
        self.manager = User.objects.create_user(
            email="mgr@n.test", password="x", name="Mgr", role=Role.MANAGER
        )
        self.laptop = Product.objects.create(
            name="Laptop Pro 14", category=self.hardware,
            list_price=Decimal("1450"), cost=Decimal("1050"),
        )
        self.setup = Product.objects.create(
            name="Onsite Setup Service", category=self.services,
            list_price=Decimal("600"), cost=Decimal("330"),
        )
        self.quotation = Quotation.objects.create(
            number="Q-N-1", customer=self.customer, rep=self.rep,
            stage=Quotation.Stage.SENT,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        self.laptop_line = QuotationLine.objects.create(
            quotation=self.quotation, product=self.laptop, qty=3,
            unit_price=Decimal("1450"), discount_pct=Decimal("5"),
        )
        self.service_line = QuotationLine.objects.create(
            quotation=self.quotation, product=self.setup, qty=1,
            unit_price=Decimal("600"), discount_pct=Decimal("8"),
        )
        pricing.recompute_quotation(self.quotation)


class CommentTests(NegotiationTestCase):

    def test_a_comment_moves_sent_to_under_negotiation(self):
        negotiation.add_comment(self.quotation, "Can we push this?", line=self.service_line)
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.UNDER_NEGOTIATION, self.quotation.stage)

    def test_a_comment_is_attributed_to_the_customer_with_no_user(self):
        negotiation.add_comment(self.quotation, "A question")
        message = PortalMessage.objects.get()
        self.assertEqual(PortalMessage.Author.CUSTOMER, message.author)
        entry = AuditLog.objects.get(action="PORTAL_COMMENT")
        self.assertIsNone(entry.actor, "a customer has no User row (ADR-004)")
        self.assertIn("Beta Industries", entry.reason)

    def test_an_empty_comment_is_refused(self):
        with self.assertRaises(ValueError):
            negotiation.add_comment(self.quotation, "   ")
        self.assertEqual(0, PortalMessage.objects.count())

    def test_a_line_from_another_quotation_is_refused(self):
        other = Quotation.objects.create(
            number="Q-N-2", customer=self.customer, rep=self.rep,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        stray = QuotationLine.objects.create(
            quotation=other, product=self.laptop, qty=1, unit_price=Decimal("1450")
        )
        with self.assertRaises(ValueError):
            negotiation.add_comment(self.quotation, "hello", line=stray)


class CounterOfferTests(NegotiationTestCase):

    def test_the_counter_REPLACES_the_line_discount_and_never_stacks(self):
        """The finding that keeps DEMO Flow B to a single approver.

        The service line already carries 8%. A 15% counter must leave it at 15%, which is
        5 points over Silver's 10% ceiling. Stacking would compound 8% and 15% to about
        21.8% given — roughly 11.8 points over on that line alone — and pull Finance in.
        """
        negotiation.submit_counter_offer(
            self.quotation, Decimal("15"), line=self.service_line
        )
        self.service_line.refresh_from_db()
        self.quotation.refresh_from_db()

        self.assertEqual(Decimal("15.00"), self.service_line.discount_pct)
        self.assertEqual(Decimal("5.00"), self.quotation.risk_score)
        self.assertLess(self.quotation.risk_score, Decimal("8.00"))

    def test_AC7_over_threshold_re_enters_approval_automatically(self):
        negotiation.submit_counter_offer(
            self.quotation, Decimal("15"), line=self.service_line
        )
        self.quotation.refresh_from_db()

        self.assertEqual(Quotation.Stage.PENDING_APPROVAL, self.quotation.stage)
        self.assertEqual(
            ["MANAGER"],
            list(self.quotation.approval_steps.values_list("level", flat=True)),
        )

    def test_a_five_point_counter_needs_the_manager_only_not_finance(self):
        """DEMO B5 shows exactly one approver. This is the assertion behind that."""
        negotiation.submit_counter_offer(
            self.quotation, Decimal("15"), line=self.service_line
        )
        self.assertFalse(self.quotation.approval_steps.filter(level="FINANCE").exists())

    def test_a_large_counter_does_pull_in_finance(self):
        negotiation.submit_counter_offer(
            self.quotation, Decimal("25"), line=self.service_line
        )
        self.quotation.refresh_from_db()
        self.assertEqual(Decimal("15.00"), self.quotation.risk_score)
        self.assertEqual(
            ["MANAGER", "FINANCE"],
            list(self.quotation.approval_steps.order_by("sequence").values_list("level", flat=True)),
        )

    def test_a_counter_inside_the_ceiling_needs_no_approval(self):
        negotiation.submit_counter_offer(
            self.quotation, Decimal("9"), line=self.service_line
        )
        self.quotation.refresh_from_db()
        self.assertEqual(Decimal("0.00"), self.quotation.risk_score)
        self.assertEqual(Quotation.Stage.UNDER_NEGOTIATION, self.quotation.stage)
        self.assertEqual(0, self.quotation.approval_steps.count())

    def test_re_entering_approval_generates_FRESH_steps(self):
        """Invariant 13. A second counter must not leave two generations of steps."""
        negotiation.submit_counter_offer(self.quotation, Decimal("15"), line=self.service_line)
        self.quotation.refresh_from_db()
        step = self.quotation.approval_steps.get()
        from core.services import approval
        approval.return_for_revision(step, self.manager, "Please justify.")

        self.quotation.refresh_from_db()
        self.quotation.stage = Quotation.Stage.UNDER_NEGOTIATION
        self.quotation.save(update_fields=["stage"])
        negotiation.submit_counter_offer(self.quotation, Decimal("25"), line=self.service_line)

        self.quotation.refresh_from_db()
        self.assertEqual(
            2, self.quotation.approval_steps.count(), "stale steps were not cleared"
        )
        self.assertEqual(
            0, self.quotation.approval_steps.exclude(status="PENDING").count()
        )

    def test_the_counter_is_recorded_as_an_append_only_message(self):
        negotiation.submit_counter_offer(
            self.quotation, Decimal("15"), line=self.service_line, body="Best you can do?"
        )
        message = PortalMessage.objects.get()
        self.assertEqual(Decimal("15.00"), message.counter_discount_pct)
        self.assertEqual("Best you can do?", message.body)
        self.assertEqual(self.service_line, message.quotation_line)

    def test_an_order_wide_counter_replaces_every_line(self):
        negotiation.submit_counter_offer(self.quotation, Decimal("12"))
        self.laptop_line.refresh_from_db()
        self.service_line.refresh_from_db()
        self.assertEqual(Decimal("12.00"), self.laptop_line.discount_pct)
        self.assertEqual(Decimal("12.00"), self.service_line.discount_pct)

    def test_an_out_of_range_counter_is_refused(self):
        for bad in (Decimal("-1"), Decimal("101")):
            with self.assertRaises(ValueError):
                negotiation.submit_counter_offer(self.quotation, bad)
        self.assertEqual(0, PortalMessage.objects.count())

    def test_the_audit_row_has_no_actor(self):
        negotiation.submit_counter_offer(self.quotation, Decimal("15"), line=self.service_line)
        entry = AuditLog.objects.get(action="COUNTER_OFFER_RECEIVED")
        self.assertIsNone(entry.actor)
        self.assertEqual("5.00", entry.payload["risk_score"])


class ConfirmTests(NegotiationTestCase):

    def test_a_customer_can_confirm_a_clean_quotation(self):
        negotiation.confirm(self.quotation)
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.CONFIRMED, self.quotation.stage)
        self.assertIsNone(AuditLog.objects.get(action="CUSTOMER_CONFIRMED").actor)

    def test_confirm_is_refused_while_an_approval_is_outstanding(self):
        negotiation.submit_counter_offer(self.quotation, Decimal("15"), line=self.service_line)
        self.quotation.refresh_from_db()
        with self.assertRaises(ValueError):
            negotiation.confirm(self.quotation)
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.PENDING_APPROVAL, self.quotation.stage)

    def test_confirm_works_once_the_manager_has_approved(self):
        from core.services import approval

        negotiation.submit_counter_offer(self.quotation, Decimal("15"), line=self.service_line)
        self.quotation.refresh_from_db()
        approval.approve(
            self.quotation.approval_steps.get(), self.manager, "Acceptable at 15%."
        )
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.APPROVED, self.quotation.stage)

        negotiation.confirm(self.quotation)
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.CONFIRMED, self.quotation.stage)

    def test_a_paid_order_cannot_be_confirmed_again(self):
        self.quotation.stage = Quotation.Stage.PAID
        self.quotation.save(update_fields=["stage"])
        with self.assertRaises(ValueError):
            negotiation.confirm(self.quotation)
