"""Tests for automatic approval routing and the audit trail (T-10).

The behaviour that matters most here is AC-3: the rep never asks for approval. `submit()`
reads the chain rules and decides on its own, and the tests assert the routing rather than
the button.
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
    Product,
    Quotation,
    QuotationLine,
    Role,
    User,
)
from core.services import approval


class ApprovalTestCase(TestCase):
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
        for lo, hi, mgr, fin in [
            ("0.00", "0.00", False, False),
            ("0.01", "7.99", True, False),
            ("8.00", "9999.99", True, True),
        ]:
            ApprovalChainRule.objects.create(
                score_min=Decimal(lo), score_max=Decimal(hi),
                requires_manager=mgr, requires_finance=fin,
            )

        self.customer = Customer.objects.create(name="Acme", email="a@a.test", tier=self.gold)
        self.rep = User.objects.create_user(email="r@t.test", password="x", name="Rep", role=Role.REP)
        self.manager = User.objects.create_user(email="m@t.test", password="x", name="Mgr", role=Role.MANAGER)
        self.finance = User.objects.create_user(email="f@t.test", password="x", name="Fin", role=Role.FINANCE)

        self.laptop = Product.objects.create(
            name="Laptop", category=self.hardware, list_price=Decimal("1450"), cost=Decimal("1050")
        )
        self.setup = Product.objects.create(
            name="Setup", category=self.services, list_price=Decimal("600"), cost=Decimal("330")
        )

    def quotation(self, lines, number="Q-A-1"):
        q = Quotation.objects.create(
            number=number, customer=self.customer, rep=self.rep,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        for product, qty, discount in lines:
            QuotationLine.objects.create(
                quotation=q, product=product, qty=qty,
                unit_price=product.list_price, discount_pct=Decimal(discount),
            )
        return q


class RequiredLevelsTests(ApprovalTestCase):
    def test_zero_needs_nobody(self):
        self.assertEqual((False, False), approval.required_levels(Decimal("0.00")))

    def test_mid_band_needs_manager_only(self):
        self.assertEqual((True, False), approval.required_levels(Decimal("7.00")))

    def test_eight_is_the_finance_boundary(self):
        self.assertEqual((True, True), approval.required_levels(Decimal("8.00")))

    def test_a_score_no_rule_covers_raises_rather_than_skipping_governance(self):
        ApprovalChainRule.objects.all().delete()
        with self.assertRaises(approval.ApprovalConfigurationError):
            approval.required_levels(Decimal("5.00"))

    def test_overlapping_bands_raise(self):
        ApprovalChainRule.objects.create(
            score_min=Decimal("5.00"), score_max=Decimal("9.00"),
            requires_manager=True, requires_finance=False,
        )
        with self.assertRaises(approval.ApprovalConfigurationError):
            approval.required_levels(Decimal("6.00"))


class SubmitRoutingTests(ApprovalTestCase):
    def test_clean_quote_skips_approval_entirely(self):
        q = self.quotation([(self.laptop, 2, "5")])
        steps = approval.submit(q, self.rep)
        q.refresh_from_db()

        self.assertEqual([], steps)
        self.assertEqual(Decimal("0.00"), q.risk_score)
        self.assertEqual(Quotation.Stage.APPROVED, q.stage)
        self.assertEqual(0, q.approval_steps.count())

    def test_the_pdf_example_routes_to_manager_then_finance_by_itself(self):
        """AC-3. The rep called submit; the system decided two approvers were needed."""
        q = self.quotation([(self.laptop, 6, "12"), (self.setup, 1, "18")])
        steps = approval.submit(q, self.rep)
        q.refresh_from_db()

        self.assertEqual(Decimal("8.00"), q.risk_score)
        self.assertEqual(Quotation.Stage.PENDING_APPROVAL, q.stage)
        self.assertEqual(["MANAGER", "FINANCE"], [s.level for s in steps])
        self.assertEqual([1, 2], [s.sequence for s in steps])

    def test_a_smaller_overage_routes_to_manager_only(self):
        q = self.quotation([(self.setup, 1, "13")])
        steps = approval.submit(q, self.rep)
        self.assertEqual(["MANAGER"], [s.level for s in steps])
        self.assertFalse(q.approval_steps.filter(level="FINANCE").exists())

    def test_submit_writes_an_audit_row_carrying_the_breakdown(self):
        q = self.quotation([(self.laptop, 6, "12"), (self.setup, 1, "18")])
        approval.submit(q, self.rep)

        entry = AuditLog.objects.get(quotation=q)
        self.assertEqual("SUBMITTED_FOR_APPROVAL", entry.action)
        self.assertEqual(self.rep, entry.actor)
        self.assertEqual("8.00", entry.payload["risk_score"])
        self.assertEqual(2, len(entry.payload["breakdown"]))

    def test_resubmitting_replaces_stale_steps(self):
        q = self.quotation([(self.laptop, 6, "12"), (self.setup, 1, "18")])
        approval.submit(q, self.rep)
        q.refresh_from_db()

        q.lines.filter(product=self.setup).update(discount_pct=Decimal("11"))
        q.stage = Quotation.Stage.DRAFT
        q.save(update_fields=["stage"])
        steps = approval.submit(q, self.rep)

        self.assertEqual(["MANAGER"], [s.level for s in steps])
        self.assertEqual(1, q.approval_steps.count())

    def test_an_empty_quotation_cannot_be_submitted(self):
        q = self.quotation([])
        with self.assertRaises(ValueError):
            approval.submit(q, self.rep)

    def test_cannot_submit_from_an_approved_stage(self):
        q = self.quotation([(self.laptop, 1, "0")])
        q.stage = Quotation.Stage.APPROVED
        q.save(update_fields=["stage"])
        with self.assertRaises(ValueError):
            approval.submit(q, self.rep)


class ApprovalActionTests(ApprovalTestCase):
    def setUp(self):
        super().setUp()
        self.q = self.quotation([(self.laptop, 6, "12"), (self.setup, 1, "18")])
        approval.submit(self.q, self.rep)
        self.q.refresh_from_db()
        self.manager_step = self.q.approval_steps.get(level="MANAGER")
        self.finance_step = self.q.approval_steps.get(level="FINANCE")

    def test_a_rep_is_refused_by_the_service_not_by_a_hidden_button(self):
        with self.assertRaises(approval.ApprovalPermissionError):
            approval.approve(self.manager_step, self.rep, "looks fine to me")
        self.manager_step.refresh_from_db()
        self.assertEqual(ApprovalStep.Status.PENDING, self.manager_step.status)

    def test_finance_cannot_act_on_a_manager_step(self):
        with self.assertRaises(approval.ApprovalPermissionError):
            approval.approve(self.manager_step, self.finance, "stepping in")

    def test_a_reason_is_required(self):
        with self.assertRaises(ValueError):
            approval.approve(self.manager_step, self.manager, "   ")

    def test_quotation_stays_pending_until_every_step_is_done(self):
        """Invariant 1 — no APPROVED while a step is still PENDING."""
        approval.approve(self.manager_step, self.manager, "margin acceptable")
        self.q.refresh_from_db()
        self.assertEqual(Quotation.Stage.PENDING_APPROVAL, self.q.stage)

        approval.approve(self.finance_step, self.finance, "within policy")
        self.q.refresh_from_db()
        self.assertEqual(Quotation.Stage.APPROVED, self.q.stage)

    def test_every_action_writes_an_audit_row_with_actor_reason_and_time(self):
        approval.approve(self.manager_step, self.manager, "margin acceptable")
        entry = AuditLog.objects.filter(action="APPROVED").get()
        self.assertEqual(self.manager, entry.actor)
        self.assertEqual("margin acceptable", entry.reason)
        self.assertIsNotNone(entry.created_at)

    def test_reject_is_terminal_and_leaves_the_trail_intact(self):
        approval.reject(self.manager_step, self.manager, "discount indefensible")
        self.q.refresh_from_db()
        self.assertEqual(Quotation.Stage.REJECTED, self.q.stage)
        # The untouched Finance step survives, so the trail shows how far it got.
        self.finance_step.refresh_from_db()
        self.assertEqual(ApprovalStep.Status.PENDING, self.finance_step.status)

    def test_return_for_revision_sends_it_back_to_draft_and_clears_pending_steps(self):
        approval.return_for_revision(self.manager_step, self.manager, "justify the service line")
        self.q.refresh_from_db()
        self.assertEqual(Quotation.Stage.DRAFT, self.q.stage)
        self.manager_step.refresh_from_db()
        self.assertEqual(ApprovalStep.Status.RETURNED, self.manager_step.status)
        self.assertFalse(
            self.q.approval_steps.filter(status=ApprovalStep.Status.PENDING).exists()
        )

    def test_acting_twice_on_one_step_is_refused(self):
        approval.approve(self.manager_step, self.manager, "fine")
        with self.assertRaises(ValueError):
            approval.approve(self.manager_step, self.manager, "fine again")

    def test_invariant_2_a_flagged_quote_never_reaches_approved_without_a_step(self):
        q = self.quotation([(self.setup, 1, "18")], number="Q-A-2")
        approval.submit(q, self.rep)
        q.refresh_from_db()
        self.assertGreater(q.risk_score, Decimal("0"))
        self.assertNotEqual(Quotation.Stage.APPROVED, q.stage)
        self.assertGreaterEqual(q.approval_steps.count(), 1)
