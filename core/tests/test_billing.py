"""Tests for the invoice and payment path (T-17, FR-20).

The two behaviours that matter: recurring lines never reach the one-time invoice
(invariant 10), and invoice status is derived from the payment sum rather than assigned
(invariant 11) — which SQLite cannot enforce, so these tests are the enforcement's proof.
"""

from decimal import Decimal

from django.test import TestCase

from core.models import (
    Category,
    Customer,
    CustomerTier,
    Invoice,
    Payment,
    Product,
    Quotation,
    QuotationLine,
    Role,
    SubscriptionPlan,
    User,
)
from core.services import billing, pricing


class BillingTestCase(TestCase):
    def setUp(self):
        tier = CustomerTier.objects.create(name="Gold", max_discount_pct=Decimal("15"))
        self.customer = Customer.objects.create(name="Acme", email="a@a.test", tier=tier)
        self.rep = User.objects.create_user(
            email="rep@b.test", password="x", name="Rep", role=Role.REP
        )
        self.hardware = Category.objects.create(name="Hardware")
        self.subs = Category.objects.create(name="Subscriptions")
        self.plan = SubscriptionPlan.objects.create(
            name="Monthly Care", interval=SubscriptionPlan.Interval.MONTHLY
        )
        self.laptop = Product.objects.create(
            name="Laptop", category=self.hardware,
            list_price=Decimal("1000.00"), cost=Decimal("600.00"),
        )
        self.care = Product.objects.create(
            name="Care Plan", category=self.subs, subscription_plan=self.plan,
            list_price=Decimal("500.00"), cost=Decimal("100.00"),
        )
        self.quotation = Quotation.objects.create(
            number="Q-B-1", customer=self.customer, rep=self.rep,
            stage=Quotation.Stage.FULFILLED,
            last_activity_at="2026-09-05T10:00:00Z",
        )

    def add(self, product, qty=1, discount="0", recurring=False):
        line = QuotationLine.objects.create(
            quotation=self.quotation, product=product, qty=qty,
            unit_price=product.list_price, discount_pct=Decimal(discount),
            line_type=(
                QuotationLine.LineType.RECURRING if recurring
                else QuotationLine.LineType.ONE_TIME
            ),
            subscription_plan=self.plan if recurring else None,
        )
        pricing.recompute_quotation(self.quotation)
        return line


class GenerateInvoiceTests(BillingTestCase):

    def test_invoice_covers_one_time_lines_only(self):
        """Invariant 10 — the recurring line must NOT be on this invoice."""
        self.add(self.laptop, qty=2)                      # 2000.00 one-time
        self.add(self.care, qty=1, recurring=True)        #  500.00 recurring

        invoice = billing.generate_invoice(self.quotation)

        self.assertEqual(Decimal("2000.00"), invoice.amount)
        self.assertNotEqual(Decimal("2500.00"), invoice.amount)
        self.assertEqual(Invoice.Status.UNPAID, invoice.status)

    def test_the_order_discount_is_applied(self):
        self.add(self.laptop, qty=2)
        self.quotation.order_discount_pct = Decimal("10")
        self.quotation.save(update_fields=["order_discount_pct"])
        pricing.recompute_quotation(self.quotation)

        invoice = billing.generate_invoice(self.quotation)
        self.assertEqual(Decimal("1800.00"), invoice.amount)

    def test_a_pure_subscription_order_gets_no_invoice_and_that_is_not_an_error(self):
        self.add(self.care, qty=1, recurring=True)
        self.assertIsNone(billing.generate_invoice(self.quotation))

    def test_generating_twice_returns_the_same_invoice(self):
        self.add(self.laptop)
        first = billing.generate_invoice(self.quotation)
        second = billing.generate_invoice(self.quotation)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(1, Invoice.objects.count())

    def test_stage_moves_to_invoiced(self):
        self.add(self.laptop)
        billing.generate_invoice(self.quotation)
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.INVOICED, self.quotation.stage)

    def test_a_draft_cannot_be_invoiced(self):
        self.quotation.stage = Quotation.Stage.DRAFT
        self.quotation.save(update_fields=["stage"])
        self.add(self.laptop)
        with self.assertRaises(ValueError):
            billing.generate_invoice(self.quotation)

    def test_an_audit_row_names_the_excluded_recurring_lines(self):
        self.add(self.laptop)
        self.add(self.care, recurring=True)
        billing.generate_invoice(self.quotation)
        entry = self.quotation.audit_log.get(action="INVOICE_GENERATED")
        self.assertIn("recurring", entry.reason)


class PaymentTests(BillingTestCase):
    def setUp(self):
        super().setUp()
        self.add(self.laptop, qty=1)          # 1000.00
        self.invoice = billing.generate_invoice(self.quotation)

    def test_partial_payment_derives_partial(self):
        billing.record_payment(self.invoice, Decimal("400.00"))
        self.invoice.refresh_from_db()
        self.assertEqual(Invoice.Status.PARTIAL, self.invoice.status)
        self.quotation.refresh_from_db()
        self.assertEqual(Quotation.Stage.INVOICED, self.quotation.stage)

    def test_full_payment_derives_paid_and_moves_the_quotation(self):
        billing.record_payment(self.invoice, Decimal("1000.00"))
        self.invoice.refresh_from_db()
        self.quotation.refresh_from_db()
        self.assertEqual(Invoice.Status.PAID, self.invoice.status)
        self.assertEqual(Quotation.Stage.PAID, self.quotation.stage)

    def test_two_partials_summing_to_full_derive_paid(self):
        billing.record_payment(self.invoice, Decimal("600.00"))
        billing.record_payment(self.invoice, Decimal("400.00"))
        self.invoice.refresh_from_db()
        self.assertEqual(Invoice.Status.PAID, self.invoice.status)
        self.assertEqual(2, self.invoice.payments.count())

    def test_overpayment_is_refused_and_writes_no_payment_row(self):
        """Invariant 11. Refused, not clamped — capping it would make the status a lie."""
        with self.assertRaises(billing.OverpaymentError):
            billing.record_payment(self.invoice, Decimal("1000.01"))
        self.assertEqual(0, Payment.objects.count())
        self.invoice.refresh_from_db()
        self.assertEqual(Invoice.Status.UNPAID, self.invoice.status)

    def test_overpayment_across_two_payments_is_also_refused(self):
        billing.record_payment(self.invoice, Decimal("900.00"))
        with self.assertRaises(billing.OverpaymentError):
            billing.record_payment(self.invoice, Decimal("200.00"))
        self.assertEqual(1, Payment.objects.count())

    def test_a_zero_or_negative_payment_is_refused(self):
        for bad in (Decimal("0"), Decimal("-5")):
            with self.assertRaises(ValueError):
                billing.record_payment(self.invoice, bad)
        self.assertEqual(0, Payment.objects.count())

    def test_derive_invoice_status_writes_nothing(self):
        billing.record_payment(self.invoice, Decimal("400.00"))
        self.invoice.refresh_from_db()
        before = self.invoice.status
        # Called directly it must only report, never persist.
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.Status.DRAFT)
        self.invoice.refresh_from_db()
        derived = billing.derive_invoice_status(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(Invoice.Status.PARTIAL, derived)
        self.assertEqual(Invoice.Status.DRAFT, self.invoice.status)
        self.assertEqual(before, Invoice.Status.PARTIAL)

    def test_payment_writes_an_audit_row(self):
        billing.record_payment(self.invoice, Decimal("1000.00"), method="CARD")
        entry = self.quotation.audit_log.get(action="PAYMENT_RECORDED")
        self.assertIn("CARD", entry.reason)
        self.assertEqual("PAID", entry.payload["status"])


class StillStubbedTests(BillingTestCase):
    """T-20 and ADR-008 work must stay unimplemented, not quietly guessed."""

    def test_schedule_and_proration_remain_stubs(self):
        for call in (
            lambda: billing.build_billing_schedule(self.quotation),
            lambda: billing.upcoming_schedule(self.quotation),
            lambda: billing.prorate_quantity_change(None, 2, None),
        ):
            with self.assertRaises(NotImplementedError):
                call()
