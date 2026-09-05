"""
`python manage.py seed_demo` — rebuild the exact demo state described in docs/DEMO.md.

Idempotent: it wipes every demo-owned row and recreates it, so running it twice gives the
same result. Users are updated in place rather than deleted, so a superuser created with
`createsuperuser` survives a reseed.

**The single most important number in this file** is the Laptop Pro 14 stock split:
Main Warehouse 4, East Depot 10, against a demo order of 6. Single-warehouse fulfilment is
therefore impossible and ADR-006's split is forced to run. Without it AC-5 cannot be
demonstrated at all. If you change one number here, change it knowing that.

Two pieces of arithmetic below are **temporary duplicates** of logic that belongs in the
services layer, marked `PROVISIONAL` where they appear:

* `_totals()` duplicates `core/services/pricing.py` (T-08).
* `_risk_score()` duplicates `core/services/risk.py` (T-09), and follows ADR-005 exactly.

They exist because the seed has to store totals and a risk score before either service is
written, and a quotation list showing 0.00 for every card is not a demo. When T-08 and T-09
land, both are deleted and replaced by calls into the services. If a service and one of
these ever disagree, **the service is right** — these are scaffolding, not a second
implementation. Tracked in BACKLOG under T-08 and T-09.
"""

from datetime import timedelta
from decimal import Decimal

from django.core import signing
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    ApprovalChainRule,
    ApprovalStep,
    AuditLog,
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


def _totals(lines, order_discount_pct=Decimal("0")):
    """
    PROVISIONAL — duplicates core/services/pricing.py (T-08). Delete when that lands.

    line_total = qty * unit_price * (1 - discount/100), then the order discount applies
    to the sum. Decimal throughout; never a float and never a SQLite Sum() (ADR-002).
    """
    subtotal = Decimal("0")
    cost = Decimal("0")
    for line in lines:
        gross = Decimal(line.qty) * line.unit_price
        line.line_total = _money(gross * (Decimal("1") - line.discount_pct / 100))
        line.line_cost = _money(Decimal(line.qty) * line.product.cost)
        subtotal += line.line_total
        cost += line.line_cost
    total = _money(subtotal * (Decimal("1") - order_discount_pct / 100))
    margin_amount = _money(total - cost)
    margin_pct = (
        _money(margin_amount / total * 100) if total > 0 else Decimal("0.00")
    )
    return _money(subtotal), total, margin_amount, margin_pct


def _risk_score(lines, tier, ceilings_by_category, order_discount_pct=Decimal("0")):
    """
    PROVISIONAL — duplicates core/services/risk.py (T-09). Delete when that lands.

    ADR-005 exactly: given = 100 * (1 - (1 - line/100) * (1 - order/100));
    allowed = min(tier ceiling, category ceiling); over = max(0, given - allowed);
    score = sum of over, quantised to 0.01.
    """
    score = Decimal("0")
    for line in lines:
        given = Decimal("100") * (
            Decimal("1")
            - (Decimal("1") - line.discount_pct / 100)
            * (Decimal("1") - order_discount_pct / 100)
        )
        category_ceiling = ceilings_by_category.get(line.product.category.name)
        allowed = tier.max_discount_pct
        if category_ceiling is not None:
            allowed = min(allowed, category_ceiling)
        score += max(Decimal("0"), given - allowed)
    return score.quantize(CENTS)


class Command(BaseCommand):
    help = "Reset the database to the exact demo state in docs/DEMO.md. Idempotent."

    @transaction.atomic
    def handle(self, *args, **options):
        self.now = timezone.now()

        self._wipe()

        users = self._seed_users()
        tiers = self._seed_tiers()
        categories = self._seed_categories()
        ceilings = self._seed_category_ceilings(tiers, categories)
        self._seed_chain_rules()
        customers = self._seed_customers(tiers)
        plans = self._seed_subscription_plans()
        products = self._seed_products(categories, plans)
        self._seed_variants(products)
        self._seed_price_lists(products, tiers)
        self._seed_product_pairs(products)
        warehouses = self._seed_warehouses()
        self._seed_stock(products, warehouses)
        quotations = self._seed_quotations(users, customers, products, tiers, ceilings)

        self._report(quotations)

    # ----------------------------------------------------------------- wipe

    def _wipe(self):
        """Children before parents — several relations are PROTECT."""
        Payment.objects.all().delete()
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
            ("rep@dealflow.test", "Rita Patel", Role.REP),
            ("manager@dealflow.test", "Marco Silva", Role.MANAGER),
            ("finance@dealflow.test", "Farah Ng", Role.FINANCE),
            ("admin@dealflow.test", "Alex Kim", Role.ADMIN),
            ("rep2@dealflow.test", "Ravi Desai", Role.REP),
            ("manager2@dealflow.test", "Mona Haddad", Role.MANAGER),
            ("finance2@dealflow.test", "Felix Braun", Role.FINANCE),
            ("admin2@dealflow.test", "Aisha Noor", Role.ADMIN),
        ]
        users = {}
        for email, name, role in spec:
            is_admin = role == Role.ADMIN
            user, _ = User.objects.update_or_create(
                email=email,
                defaults={
                    "name": name,
                    "role": role,
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
        ]
        return {
            name: Customer.objects.create(name=name, email=email, tier=tiers[tier])
            for name, email, tier in spec
        }

    def _seed_subscription_plans(self):
        """
        MUST as of the A5 split — AC-1 requires a subscription plan to persist.

        proration_method and cancellation_policy are left at UNDECIDED on purpose:
        ADR-008 is still open, and a made-up value here would read as a decision nobody
        took. T-20 fills them in.
        """
        return {
            "Monthly Care": SubscriptionPlan.objects.create(
                name="Monthly Care", interval=SubscriptionPlan.Interval.MONTHLY
            ),
            "Quarterly Support": SubscriptionPlan.objects.create(
                name="Quarterly Support", interval=SubscriptionPlan.Interval.QUARTERLY
            ),
            "Annual Platform": SubscriptionPlan.objects.create(
                name="Annual Platform", interval=SubscriptionPlan.Interval.YEARLY
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
                    currency="EUR",
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
        spec = [
            ("Laptop Pro 14", 4, 10),  # <- the split trigger. Do not "tidy" this.
            ("Docking Station X3", 25, 12),
            ('27" 4K Monitor', 18, 6),
            ("Wireless Headset Duo", 40, 15),
        ]
        for name, main_qty, east_qty in spec:
            Stock.objects.create(product=products[name], warehouse=main, qty_on_hand=main_qty)
            Stock.objects.create(product=products[name], warehouse=east, qty_on_hand=east_qty)

    # ----------------------------------------------------------------- quotations

    def _price_for(self, product, customer):
        entry = PriceListEntry.objects.filter(product=product, tier=customer.tier).first()
        return entry.price if entry else product.list_price

    def _build(self, number, customer, rep, stage, line_specs, tier, ceilings,
               order_discount_pct=Decimal("0"), days_idle=0):
        """Create one quotation with its lines, totals and risk score."""
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

        subtotal, total, margin_amount, margin_pct = _totals(lines, order_discount_pct)
        QuotationLine.objects.bulk_create(lines)

        quotation.subtotal = subtotal
        quotation.total = total
        quotation.margin_amount = margin_amount
        quotation.margin_pct = margin_pct
        quotation.risk_score = _risk_score(lines, tier, ceilings, order_discount_pct)
        quotation.save()
        return quotation

    def _seed_quotations(self, users, customers, products, tiers, gold_ceilings):
        rep = users["rep@dealflow.test"]
        acme, beta, cirrus = customers["Acme Corp"], customers["Beta Industries"], customers["Cirrus Ltd"]
        no_ceilings = {}  # Silver and Bronze have no category rows — see _seed_category_ceilings

        made = {}

        # --- Q-2026-0001: Flow A starts here. Draft, deliberately EMPTY.
        # DEMO.md step A2 expects "empty cart, margin indicator neutral" — the rep builds
        # the lines live on stage. Its risk score is therefore 0.00, which is correct.
        made["draft"] = self._build(
            "Q-2026-0001", acme, rep, Quotation.Stage.DRAFT, [], tiers["Gold"], gold_ceilings
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
            tiers["Silver"],
            no_ceilings,
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
            tiers["Gold"],
            gold_ceilings,
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
            tiers["Bronze"],
            no_ceilings,
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
            tiers["Silver"],
            no_ceilings,
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
        out.write("")

        laptop = Product.objects.get(name="Laptop Pro 14")
        out.write("  Laptop Pro 14 stock (the split trigger, demo order is 6):")
        for row in Stock.objects.filter(product=laptop).select_related("warehouse"):
            out.write(f"    {row.warehouse.name:<16} {row.qty_available}")
        out.write("")

        pending = quotations["pending"]
        out.write(f"  {pending.number} risk score: {pending.risk_score}  (ADR-005 predicts 8.00)")
        out.write(f"  Portal link: /portal/{quotations['portal'].portal_token}/")
