"""
`python manage.py seed_demo` — rebuild the exact demo state described in docs/DEMO.md.

Idempotent: it wipes every demo-owned row and recreates it, so running it twice gives the
same result. Users are updated in place rather than deleted, so a superuser created with
`createsuperuser` survives a reseed.

**The single most important number in this file** is the Laptop Pro 14 stock split:
Main Warehouse 4, East Depot 10, against a demo order of 6. Single-warehouse fulfilment is
therefore impossible and ADR-006's split is forced to run. Without it AC-5 cannot be
demonstrated at all. If you change one number here, change it knowing that.

**There is no arithmetic in this file.** Totals, margin and the risk score come from
`core/services/pricing.py` and `core/services/risk.py`, the same functions the application
uses. An earlier version carried provisional copies of both formulas, because the seed had
to store numbers before either service existed; those were deleted when T-08 and T-09
landed, which was a written acceptance criterion on both tasks rather than a comment.

That matters for more than tidiness: the seeded risk score of 8.00 on Q-2026-0003 is now
produced by the same code path that scores a quotation at submit time, so the demo data
cannot drift away from the behaviour it is demonstrating.
"""

from datetime import timedelta
from decimal import Decimal

from django.core import signing
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.services import billing, fulfilment, pricing, risk
from core.models import (
    ApprovalChainRule,
    Asset,
    ApprovalStep,
    AuditLog,
    BillingScheduleEntry,
    Category,
    CategoryDiscountCeiling,
    Customer,
    CustomerTier,
    FulfilmentAllocation,
    Invoice,
    Payment,
    PortalMessage,
    PriceListEntry,
    Product,
    ProductPair,
    ProductVariant,
    Quotation,
    QuotationLine,
    Role,
    SalesSetting,
    Stock,
    SubscriptionPlan,
    User,
    Warehouse,
)

DEMO_PASSWORD = "dealflow360"
CENTS = Decimal("0.01")


# --------------------------------------------------------------------------- helpers


def _money(value):
    return Decimal(value).quantize(CENTS)


class Command(BaseCommand):
    help = "Reset the database to the exact demo state in docs/DEMO.md. Idempotent."

    @transaction.atomic
    def handle(self, *args, **options):
        self.now = timezone.now()

        self._wipe()

        users = self._seed_users()
        tiers = self._seed_tiers()
        categories = self._seed_categories()
        self._seed_category_ceilings(tiers, categories)
        self._seed_chain_rules()
        customers = self._seed_customers(tiers)
        plans = self._seed_subscription_plans()
        products = self._seed_products(categories, plans)
        self._seed_variants(products)
        self._seed_price_lists(products, tiers)
        self._seed_product_pairs(products)
        warehouses = self._seed_warehouses()
        self._seed_stock(products, warehouses)
        self._seed_settings()
        quotations = self._seed_quotations(users, customers, products)
        self._seed_history(users, customers, products)

        self._report(quotations)

    # ----------------------------------------------------------------- wipe

    def _wipe(self):
        """Children before parents — several relations are PROTECT."""
        # Assets hold PROTECT keys to lines, quotations, customers and products, so they
        # go first or the whole wipe fails on the second run.
        Asset.objects.all().delete()
        Payment.objects.all().delete()
        BillingScheduleEntry.objects.all().delete()
        Invoice.objects.all().delete()
        FulfilmentAllocation.objects.all().delete()
        PortalMessage.objects.all().delete()
        AuditLog.objects.all().delete()
        ApprovalStep.objects.all().delete()
        QuotationLine.objects.all().delete()
        Quotation.objects.all().delete()
        Stock.objects.all().delete()
        Warehouse.objects.all().delete()
        ProductPair.objects.all().delete()
        ProductVariant.objects.all().delete()
        PriceListEntry.objects.all().delete()
        Product.objects.all().delete()
        SubscriptionPlan.objects.all().delete()
        CategoryDiscountCeiling.objects.all().delete()
        ApprovalChainRule.objects.all().delete()
        Category.objects.all().delete()
        Customer.objects.all().delete()
        CustomerTier.objects.all().delete()

    # ----------------------------------------------------------------- config

    def _seed_users(self):
        """
        DEMO.md: four demo users plus a second set as a mid-demo fallback.

        Only ADMIN is staff/superuser. Manager and Finance reach governance through the
        hand-built approval screen (T-13), not through Django admin; granting them
        backend permissions belongs to T-06, when the config models are registered.
        """
        spec = [
            ("rep@dealflow.test", "Rita Patel", Role.REP, "West"),
            ("manager@dealflow.test", "Marco Silva", Role.MANAGER, "West"),
            ("finance@dealflow.test", "Farah Ng", Role.FINANCE, ""),
            ("admin@dealflow.test", "Alex Kim", Role.ADMIN, ""),
            ("rep2@dealflow.test", "Ravi Desai", Role.REP, "East"),
            ("manager2@dealflow.test", "Mona Haddad", Role.MANAGER, "East"),
            ("finance2@dealflow.test", "Felix Braun", Role.FINANCE, ""),
            ("admin2@dealflow.test", "Aisha Noor", Role.ADMIN, ""),
            ("rep3@dealflow.test", "Sara Iqbal", Role.REP, "West"),
            ("rep4@dealflow.test", "Tom Okafor", Role.REP, "East"),
        ]
        users = {}
        for email, name, role, team in spec:
            is_admin = role == Role.ADMIN
            user, _ = User.objects.update_or_create(
                email=email,
                defaults={
                    "name": name,
                    "role": role,
                    "team": team,
                    "is_staff": is_admin,
                    "is_superuser": is_admin,
                    "is_active": True,
                },
            )
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
            users[email] = user
        return users

    def _seed_tiers(self):
        """PDF example: Bronze <= 5%, Silver <= 10%, Gold <= 15%."""
        return {
            name: CustomerTier.objects.create(name=name, max_discount_pct=Decimal(pct))
            for name, pct in (("Bronze", "5"), ("Silver", "10"), ("Gold", "15"))
        }

    def _seed_categories(self):
        return {
            name: Category.objects.create(name=name)
            for name in ("Hardware", "Services", "Subscriptions")
        }

    def _seed_category_ceilings(self, tiers, categories):
        """
        DEMO.md seeds category ceilings for **Gold only**: Hardware 15, Services 10,
        Subscriptions 12. The Hardware-15 / Services-10 pair is what makes the PDF's
        worked example runnable.

        Bronze and Silver deliberately have no category rows, so their effective ceiling
        is the tier ceiling alone. That is what makes Flow B's arithmetic work: Beta is
        Silver, ceiling 10, and a 15% counter is exactly 5 points over — inside the
        Manager-only band (ADR-005). Adding a stricter Services row for Silver would
        change Flow B's routing, so do not add one without re-reading DEMO.md.
        """
        gold = tiers["Gold"]
        values = {"Hardware": "15", "Services": "10", "Subscriptions": "12"}
        for category_name, pct in values.items():
            CategoryDiscountCeiling.objects.create(
                tier=gold, category=categories[category_name], max_discount_pct=Decimal(pct)
            )
        return {name: Decimal(pct) for name, pct in values.items()}

    def _seed_chain_rules(self):
        """ADR-005's three rows. Inclusive bands, tiling with no gap and no overlap."""
        rows = [
            ("0.00", "0.00", False, False),
            ("0.01", "7.99", True, False),
            ("8.00", "9999.99", True, True),
        ]
        for lo, hi, manager, finance in rows:
            ApprovalChainRule.objects.create(
                score_min=Decimal(lo),
                score_max=Decimal(hi),
                requires_manager=manager,
                requires_finance=finance,
            )

    def _seed_customers(self, tiers):
        spec = [
            ("Acme Corp", "buyer@acme.test", "Gold"),
            ("Beta Industries", "purchasing@beta.test", "Silver"),
            ("Cirrus Ltd", "ops@cirrus.test", "Bronze"),
            ("Delta Robotics", "finance@delta.test", "Gold"),
            ("Everline Health", "procure@everline.test", "Silver"),
            ("Foxglove Media", "ap@foxglove.test", "Bronze"),
            ("Granite Logistics", "buying@granite.test", "Silver"),
            ("Harbour Analytics", "ops@harbour.test", "Gold"),
        ]
        return {
            name: Customer.objects.create(name=name, email=email, tier=tiers[tier])
            for name, email, tier in spec
        }

    def _seed_subscription_plans(self):
        """
        MUST as of the A5 split — AC-1 requires a subscription plan to persist.

        ADR-008 is now closed, so both rule fields carry the decision rather than
        UNDECIDED: daily pro-rata on the current period, and cancellation credits the
        unused days of that period.
        """
        rules = {"proration_method": "DAILY", "cancellation_policy": "CREDIT_UNUSED_DAYS"}
        return {
            "Monthly Care": SubscriptionPlan.objects.create(
                name="Monthly Care", interval=SubscriptionPlan.Interval.MONTHLY, **rules
            ),
            "Quarterly Support": SubscriptionPlan.objects.create(
                name="Quarterly Support", interval=SubscriptionPlan.Interval.QUARTERLY, **rules
            ),
            "Annual Platform": SubscriptionPlan.objects.create(
                name="Annual Platform", interval=SubscriptionPlan.Interval.YEARLY, **rules
            ),
        }

    def _seed_products(self, categories, plans):
        """Ten products across the three categories. Every one carries a cost, because
        the live margin indicator (B3, AC-4) cannot exist without it."""
        spec = [
            # name, category, list, cost, unit, promoted, plan
            ("Laptop Pro 14", "Hardware", "1450.00", "1050.00", "unit", False, None),
            ("Docking Station X3", "Hardware", "220.00", "150.00", "unit", True, None),
            ('27" 4K Monitor', "Hardware", "390.00", "265.00", "unit", False, None),
            ("Wireless Headset Duo", "Hardware", "95.00", "58.00", "unit", False, None),
            ("Onsite Setup Service", "Services", "600.00", "330.00", "engagement", False, None),
            ("Data Migration Service", "Services", "1800.00", "1100.00", "engagement", False, None),
            ("Admin Training Day", "Services", "750.00", "420.00", "day", False, None),
            ("Care Plan 2yr", "Subscriptions", "480.00", "180.00", "month", True, "Monthly Care"),
            ("Cloud Backup 1TB", "Subscriptions", "240.00", "90.00", "month", False, "Monthly Care"),
            ("Priority Support SLA", "Subscriptions", "360.00", "140.00", "quarter", False, "Quarterly Support"),
            ("Rugged Tablet 10", "Hardware", "680.00", "455.00", "unit", False, None),
            ("Label Printer Z2", "Hardware", "310.00", "205.00", "unit", True, None),
            ("Network Switch 24p", "Hardware", "540.00", "360.00", "unit", False, None),
            ("Conference Camera", "Hardware", "820.00", "560.00", "unit", False, None),
            ("Security Audit", "Services", "2400.00", "1450.00", "engagement", False, None),
            ("Custom Integration", "Services", "3200.00", "2050.00", "engagement", True, None),
            ("Platform Licence", "Subscriptions", "1200.00", "430.00", "year", False, "Annual Platform"),
            ("Analytics Add-on", "Subscriptions", "300.00", "115.00", "month", False, "Monthly Care"),
        ]
        products = {}
        for name, category, price, cost, unit, promoted, plan in spec:
            products[name] = Product.objects.create(
                name=name,
                category=categories[category],
                list_price=Decimal(price),
                cost=Decimal(cost),
                unit=unit,
                tax_pct=Decimal("20.00"),
                description=f"{name} — seeded demo product.",
                is_promoted=promoted,
                subscription_plan=plans[plan] if plan else None,
            )
        return products

    def _seed_variants(self, products):
        """SHOULD (T-25). Enough rows for the variant work to have something to read."""
        spec = [
            ("Laptop Pro 14", "Memory", "16 GB", "0.00"),
            ("Laptop Pro 14", "Memory", "32 GB", "180.00"),
            ('27" 4K Monitor', "Stand", "Fixed", "0.00"),
            ('27" 4K Monitor', "Stand", "Height adjustable", "45.00"),
            ("Rugged Tablet 10", "Storage", "64 GB", "0.00"),
            ("Rugged Tablet 10", "Storage", "128 GB", "90.00"),
            ("Rugged Tablet 10", "Storage", "256 GB", "210.00"),
            ("Network Switch 24p", "Uplink", "Copper", "0.00"),
            ("Network Switch 24p", "Uplink", "Fibre SFP+", "160.00"),
            ("Conference Camera", "Field of view", "90 degrees", "0.00"),
            ("Conference Camera", "Field of view", "120 degrees", "75.00"),
        ]
        for product, attribute, value, extra in spec:
            ProductVariant.objects.create(
                product=products[product], attribute=attribute, value=value, extra_price=Decimal(extra)
            )

    def _seed_price_lists(self, products, tiers):
        """
        Tier pricing (FR-04): Bronze pays list, Silver 3% less, Gold 5% less. These are
        *prices*, not discounts — the discount ceilings are a separate mechanism, and
        conflating them is a mistake worth not making.
        """
        factors = {"Bronze": Decimal("1.00"), "Silver": Decimal("0.97"), "Gold": Decimal("0.95")}
        for product in products.values():
            for tier_name, factor in factors.items():
                PriceListEntry.objects.create(
                    product=product,
                    tier=tiers[tier_name],
                    price=_money(product.list_price * factor),
                    currency="INR",
                )

    def _seed_product_pairs(self, products):
        """
        DEMO.md: Laptop Pro 14 and Care Plan 2yr must have a high co-purchase count, so
        the upsell panel's top suggestion is predictable on stage (Flow A step A5).
        """
        spec = [
            ("Laptop Pro 14", "Care Plan 2yr", 42),
            ("Laptop Pro 14", "Docking Station X3", 31),
            ("Laptop Pro 14", '27" 4K Monitor', 24),
            ("Laptop Pro 14", "Wireless Headset Duo", 9),
            ("Onsite Setup Service", "Admin Training Day", 12),
            ('27" 4K Monitor', "Docking Station X3", 7),
        ]
        for a, b, count in spec:
            ProductPair.objects.create(
                product_a=products[a], product_b=products[b], co_purchase_count=count
            )

    def _seed_warehouses(self):
        return {
            "Main Warehouse": Warehouse.objects.create(
                name="Main Warehouse", shipping_cost_weight=Decimal("1.00")
            ),
            "East Depot": Warehouse.objects.create(
                name="East Depot", shipping_cost_weight=Decimal("1.40")
            ),
            "North Hub": Warehouse.objects.create(
                name="North Hub", shipping_cost_weight=Decimal("1.75")
            ),
        }

    def _seed_stock(self, products, warehouses):
        """
        **Main Warehouse 4 / East Depot 10 for Laptop Pro 14 is load-bearing.** The demo
        orders 6, so one warehouse cannot fill it and ADR-006's split has to run: 4 from
        Main (weight 1.0), 2 from East (1.4), two shipments, estimated cost 6.80.

        Only Hardware is stocked. Services and Subscriptions have no stock rows at all,
        which is correct — you do not warehouse an engagement — but it means the split
        service must skip non-stocked lines rather than treat them as a total backorder.
        Noted in BACKLOG T-16 so it is not discovered on stage.
        """
        main = warehouses["Main Warehouse"]
        east = warehouses["East Depot"]
        north = warehouses["North Hub"]
        # name, Main, East, North, reorder point
        spec = [
            ("Laptop Pro 14", 4, 10, 3, 5),  # <- the split trigger. Do not "tidy" this.
            ("Docking Station X3", 25, 12, 8, 10),
            ('27" 4K Monitor', 18, 6, 4, 8),
            ("Wireless Headset Duo", 40, 15, 20, 12),
            ("Rugged Tablet 10", 2, 3, 1, 6),      # below reorder point on every site
            ("Label Printer Z2", 14, 5, 0, 6),
            ("Network Switch 24p", 9, 2, 5, 4),
            ("Conference Camera", 3, 0, 2, 5),     # thin, so a large order backorders
        ]
        for name, main_qty, east_qty, north_qty, reorder in spec:
            for warehouse, qty in ((main, main_qty), (east, east_qty), (north, north_qty)):
                Stock.objects.create(
                    product=products[name], warehouse=warehouse,
                    qty_on_hand=qty, reorder_point=reorder,
                )

    def _seed_settings(self):
        """ADR-007. The thresholds the deal health dashboard reads.

        Left at the documented defaults rather than tuned to make the demo data look
        alarming: the seeded history below is what produces the alerts, so the numbers
        here stay defensible.
        """
        setting = SalesSetting.load()
        setting.stall_days = 7
        setting.anomaly_window_days = 90
        setting.anomaly_threshold_pct = Decimal("10.00")
        setting.delivery_promise_days = 5
        setting.currency_code = "INR"
        setting.currency_symbol = "\u20b9"
        setting.currency_rate = Decimal("1.000000")
        setting.save()
        return setting

    # ----------------------------------------------------------------- quotations

    def _price_for(self, product, customer):
        entry = PriceListEntry.objects.filter(product=product, tier=customer.tier).first()
        return entry.price if entry else product.list_price

    def _build(self, number, customer, rep, stage, line_specs,
               order_discount_pct=Decimal("0"), days_idle=0):
        """Create one quotation, then let the services compute its money and its score.

        The tier ceiling and the category ceilings are not passed in: `score_for_quotation`
        reads them from the database itself, which is the point — the seed configures
        governance and then asks the real scorer what that configuration produces.
        """
        activity = self.now - timedelta(days=days_idle)
        quotation = Quotation.objects.create(
            number=number,
            customer=customer,
            rep=rep,
            stage=stage,
            order_discount_pct=order_discount_pct,
            last_activity_at=activity,
        )
        lines = []
        for product, qty, discount in line_specs:
            is_recurring = product.subscription_plan is not None
            line = QuotationLine(
                quotation=quotation,
                product=product,
                qty=qty,
                unit_price=self._price_for(product, customer),
                discount_pct=Decimal(discount),
                line_type=(
                    QuotationLine.LineType.RECURRING
                    if is_recurring
                    else QuotationLine.LineType.ONE_TIME
                ),
                subscription_plan=product.subscription_plan if is_recurring else None,
            )
            lines.append(line)

        QuotationLine.objects.bulk_create(lines)

        # Line totals, order total and margin — core/services/pricing.py (T-08).
        pricing.recompute_quotation(quotation)

        # Blended risk score — core/services/risk.py (T-09), reading the ceiling rows
        # seeded above. Snapshotted here the way approval.py snapshots it at submit.
        quotation.risk_score = risk.score_for_quotation(quotation).score
        quotation.save(update_fields=["risk_score"])
        return quotation

    def _seed_quotations(self, users, customers, products):
        rep = users["rep@dealflow.test"]
        acme, beta, cirrus = customers["Acme Corp"], customers["Beta Industries"], customers["Cirrus Ltd"]
        made = {}

        # --- Q-2026-0001: Flow A starts here. Draft, deliberately EMPTY.
        # DEMO.md step A2 expects "empty cart, margin indicator neutral" — the rep builds
        # the lines live on stage. Its risk score is therefore 0.00, which is correct.
        made["draft"] = self._build(
            "Q-2026-0001", acme, rep, Quotation.Stage.DRAFT, []
        )

        # --- Q-2026-0002: Flow B starts here. Sent, with a live portal token.
        # Both lines are inside Silver's 10% ceiling, so it currently scores 0.00. The
        # customer's 15% counter in the portal is what pushes it over (5 points -> Manager
        # only, per ADR-005 and the note in DEMO.md B3).
        beta_quote = self._build(
            "Q-2026-0002",
            beta,
            rep,
            Quotation.Stage.SENT,
            [
                (products["Laptop Pro 14"], 3, "5.00"),
                (products["Onsite Setup Service"], 1, "8.00"),
            ],
        )
        beta_quote.portal_token = signing.TimestampSigner().sign(str(beta_quote.pk))
        beta_quote.save(update_fields=["portal_token"])
        PortalMessage.objects.create(
            quotation=beta_quote,
            author=PortalMessage.Author.REP,
            body="Quotation is ready for your review — happy to talk through any line.",
        )
        made["portal"] = beta_quote

        # --- Q-2026-0003: the PDF's worked example, sitting in approval.
        # Laptop 12% against a 15% Hardware ceiling is fine; Onsite Setup 18% against a
        # 10% Services ceiling is 8 points over. Score 8.00 -> Manager AND Finance.
        pending = self._build(
            "Q-2026-0003",
            acme,
            rep,
            Quotation.Stage.PENDING_APPROVAL,
            [
                (products["Laptop Pro 14"], 6, "12.00"),
                (products["Onsite Setup Service"], 1, "18.00"),
            ],
        )
        ApprovalStep.objects.create(
            quotation=pending, sequence=1, level=ApprovalStep.Level.MANAGER
        )
        ApprovalStep.objects.create(
            quotation=pending, sequence=2, level=ApprovalStep.Level.FINANCE
        )
        AuditLog.objects.create(
            quotation=pending,
            actor=rep,
            action="SUBMITTED_FOR_APPROVAL",
            reason="Automatic: blended risk score 8.00 crossed the Finance threshold.",
            payload={"risk_score": "8.00", "steps": ["MANAGER", "FINANCE"]},
        )
        made["pending"] = pending

        # --- Q-2026-0004: approved, and the stalled deal for the health dashboard.
        stalled = self._build(
            "Q-2026-0004",
            cirrus,
            rep,
            Quotation.Stage.APPROVED,
            [
                (products["Docking Station X3"], 8, "4.00"),
                (products["Wireless Headset Duo"], 8, "3.00"),
            ],
            days_idle=14,
        )
        AuditLog.objects.create(
            quotation=stalled, actor=rep, action="APPROVED", reason="Within Bronze ceiling; no approval required."
        )
        made["stalled"] = stalled

        # --- Q-2026-0005: a closed deal, invoiced and paid, so the list is not all open.
        paid = self._build(
            "Q-2026-0005",
            beta,
            rep,
            Quotation.Stage.PAID,
            [
                (products['27" 4K Monitor'], 4, "6.00"),
                (products["Data Migration Service"], 1, "5.00"),
            ],
        )
        invoice = Invoice.objects.create(
            quotation=paid,
            number="INV-2026-0001",
            amount=paid.total,
            status=Invoice.Status.PAID,
            issue_date=(self.now - timedelta(days=20)).date(),
            due_date=(self.now - timedelta(days=6)).date(),
        )
        Payment.objects.create(
            invoice=invoice,
            amount=paid.total,
            method="BANK_TRANSFER",
            paid_at=self.now - timedelta(days=5),
        )
        made["paid"] = paid

        return made

    def _seed_history(self, users, customers, products):
        """Volume and history, so the analytics screens have something true to say.

        Three things are seeded deliberately rather than incidentally:

        * **A rep's discount baseline.** Sara Iqbal writes many small discounts and then
          one very large one, so `health.discount_anomalies()` has a real average to
          measure against. Without a baseline every rep is unremarkable and the panel is
          honestly, but uselessly, empty.
        * **Stalled deals.** Several quotations are backdated past the 7-day window.
        * **Delivery slippage.** One confirmed order carries a promise date in the past
          with its stock still on backorder.
        """
        rep = users["rep@dealflow.test"]
        rep2 = users["rep2@dealflow.test"]
        sara = users["rep3@dealflow.test"]
        tom = users["rep4@dealflow.test"]

        delta = customers["Delta Robotics"]
        everline = customers["Everline Health"]
        foxglove = customers["Foxglove Media"]
        granite = customers["Granite Logistics"]
        harbour = customers["Harbour Analytics"]

        laptop = products["Laptop Pro 14"]
        dock = products["Docking Station X3"]
        monitor = products['27" 4K Monitor']
        headset = products["Wireless Headset Duo"]
        tablet = products["Rugged Tablet 10"]
        printer = products["Label Printer Z2"]
        switch = products["Network Switch 24p"]
        camera = products["Conference Camera"]
        setup = products["Onsite Setup Service"]
        training = products["Admin Training Day"]
        audit = products["Security Audit"]
        care = products["Care Plan 2yr"]
        backup = products["Cloud Backup 1TB"]
        licence = products["Platform Licence"]
        analytics = products["Analytics Add-on"]

        # number, customer, rep, stage, lines, days idle
        spec = [
            ("Q-2026-0006", harbour, rep2, Quotation.Stage.SENT,
             [(laptop, 3, "8.00"), (dock, 3, "5.00")], 2),
            ("Q-2026-0007", granite, rep2, Quotation.Stage.DRAFT,
             [(switch, 2, "0.00"), (printer, 4, "4.00")], 1),
            ("Q-2026-0008", foxglove, tom, Quotation.Stage.PAID,
             [(monitor, 6, "3.00"), (headset, 10, "2.00")], 34),
            ("Q-2026-0009", everline, tom, Quotation.Stage.INVOICED,
             [(tablet, 4, "6.00"), (training, 2, "5.00")], 12),
            ("Q-2026-0010", delta, rep, Quotation.Stage.REJECTED,
             [(audit, 1, "22.00")], 26),
            ("Q-2026-0011", harbour, rep2, Quotation.Stage.APPROVED,
             [(licence, 1, "6.00"), (setup, 1, "8.00")], 3),
            ("Q-2026-0012", granite, tom, Quotation.Stage.SENT,
             [(camera, 2, "4.00"), (analytics, 3, "3.00")], 19),
            ("Q-2026-0013", foxglove, rep, Quotation.Stage.PENDING_APPROVAL,
             [(setup, 2, "16.00"), (laptop, 1, "9.00")], 4),
            ("Q-2026-0014", delta, rep2, Quotation.Stage.PAID,
             [(dock, 8, "5.00"), (backup, 4, "2.00")], 41),
            ("Q-2026-0015", everline, rep, Quotation.Stage.UNDER_NEGOTIATION,
             [(monitor, 5, "9.00"), (care, 2, "4.00")], 9),
        ]
        for number, customer, owner, stage, lines, idle in spec:
            self._build(number, customer, owner, stage, lines, days_idle=idle)

        # Sara's baseline: eight quiet deals at 2-4%, so her average is genuinely low.
        for index in range(8):
            self._build(
                f"Q-2026-01{index + 20}",
                [delta, everline, foxglove, granite][index % 4],
                sara,
                Quotation.Stage.PAID,
                [(headset, 4 + index, "2.00"), (dock, 2, "3.00")],
                days_idle=45 + index * 3,
            )

        # ...and the one that breaks the pattern. This is the anomaly the dashboard finds.
        self._build(
            "Q-2026-0130", harbour, sara, Quotation.Stage.PENDING_APPROVAL,
            [(laptop, 2, "34.00"), (monitor, 2, "4.00")], days_idle=1,
        )

        # A hybrid order with a live billing schedule, so B7 is populated on arrival.
        hybrid = self._build(
            "Q-2026-0140", harbour, rep, Quotation.Stage.CONFIRMED,
            [(laptop, 1, "5.00"), (care, 3, "4.00"), (analytics, 2, "0.00")], days_idle=2,
        )
        billing.on_order_confirmed(hybrid)

        # A confirmed order past its promise with stock still short — delivery slippage.
        late = self._build(
            "Q-2026-0150", granite, rep2, Quotation.Stage.CONFIRMED,
            [(camera, 9, "3.00")], days_idle=11,
        )
        late.promised_delivery_date = (self.now - timedelta(days=4)).date()
        late.save(update_fields=["promised_delivery_date"])
        try:
            fulfilment.accept_split(late, rep2)
        except Exception:  # pragma: no cover - seed is best-effort on the split
            pass

        # ADR-013. Assets, so "what does this customer own" and the renewals queue have
        # something true to show. Orders that were already closed when the asset model
        # arrived get theirs written directly; the terms are then spread across the next
        # few months so the queue is not either empty or entirely overdue.
        from core.models import Asset
        from core.services import assets as asset_service

        for quotation in Quotation.objects.filter(
            stage__in=[
                Quotation.Stage.CONFIRMED, Quotation.Stage.FULFILLED,
                Quotation.Stage.INVOICED, Quotation.Stage.PAID,
            ]
        ):
            asset_service.create_from_confirmation(quotation)

        # Stagger the terms: two already lapsed, the rest inside 20 to 200 days.
        offsets = [-18, -4, 12, 26, 45, 70, 110, 160, 200]
        recurring = list(
            Asset.objects.filter(end_date__isnull=False).order_by("id")
        )
        for index, asset in enumerate(recurring):
            asset.end_date = (self.now + timedelta(days=offsets[index % len(offsets)])).date()
            asset.save(update_fields=["end_date"])

    # ----------------------------------------------------------------- report

    def _report(self, quotations):
        out = self.stdout
        ok = self.style.SUCCESS
        out.write(ok("Demo data seeded."))
        out.write("")
        out.write(f"  Users            {User.objects.count()}  (password: {DEMO_PASSWORD})")
        out.write(f"  Tiers            {CustomerTier.objects.count()}")
        out.write(f"  Categories       {Category.objects.count()}")
        out.write(f"  Ceilings (Gold)  {CategoryDiscountCeiling.objects.count()}")
        out.write(f"  Chain rules      {ApprovalChainRule.objects.count()}")
        out.write(f"  Customers        {Customer.objects.count()}")
        out.write(f"  Products         {Product.objects.count()}")
        out.write(f"  Plans            {SubscriptionPlan.objects.count()}")
        out.write(f"  Warehouses       {Warehouse.objects.count()}")
        out.write(f"  Stock rows       {Stock.objects.count()}")
        out.write(f"  Quotations       {Quotation.objects.count()}")
        out.write(f"  Variants         {ProductVariant.objects.count()}")
        out.write(f"  Billing entries  {BillingScheduleEntry.objects.count()}")
        out.write(f"  Invoices         {Invoice.objects.count()}")
        out.write(f"  Assets           {Asset.objects.count()}")
        out.write("")

        laptop = Product.objects.get(name="Laptop Pro 14")
        out.write("  Laptop Pro 14 stock (the split trigger, demo order is 6):")
        for row in Stock.objects.filter(product=laptop).select_related("warehouse"):
            out.write(f"    {row.warehouse.name:<16} {row.qty_available}")
        out.write("")

        pending = quotations["pending"]
        out.write(f"  {pending.number} risk score: {pending.risk_score}  (ADR-005 predicts 8.00)")
        out.write(f"  Portal link: /portal/{quotations['portal'].portal_token}/")
