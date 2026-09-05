"""
Asset lifecycle — ADR-013. What a customer owns, and what happens when it runs out.

Three questions this module exists to answer, none of which quotations alone can:

* **What does this customer own right now?** `for_customer()`
* **What is that worth per month?** `mrr_summary()` — normalised to a month, so monthly,
  quarterly and annual plans are comparable without a conversion at every call site.
* **What is about to lapse, and can we quote the renewal in one click?**
  `due_for_renewal()` and `create_renewal_quotation()`.

Assets are written by `create_from_confirmation()` and by nothing else. It runs from the
same hook that builds the billing schedule, so an asset cannot exist for something nobody
confirmed. Idempotent: a line already owning an asset is skipped, because both the rep's
warehouse-split confirmation and the customer's portal confirmation reach that hook.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

# One term is twelve billing periods, matching the schedule `build_billing_schedule`
# writes. Keeping the two in step is what makes an asset's end date mean "the schedule
# runs out here" rather than a number picked separately.
PERIODS_PER_TERM = 12

MONTHS_PER_INTERVAL = {"MONTHLY": 1, "QUARTERLY": 3, "YEARLY": 12}


def _months(line):
    plan = line.subscription_plan
    return MONTHS_PER_INTERVAL.get(plan.interval, 1) if plan else 1


def monthly_value(line):
    """A recurring line's contribution to MRR, normalised to one month.

    A quarterly plan billed 900 contributes 300 a month; an annual plan billed 1,200
    contributes 100. Without this every dashboard has to know the interval, and one of
    them eventually forgets.
    """
    return (Decimal(line.line_total) / Decimal(_months(line))).quantize(Decimal("0.01"))


@transaction.atomic
def create_from_confirmation(quotation):
    """Create the assets a confirmed order implies. Idempotent.

    One-time lines become assets with no end date — owning a laptop does not expire.
    Recurring lines get a term of `PERIODS_PER_TERM` periods and an MRR contribution.
    """
    from core.models import Asset, QuotationLine

    existing = set(quotation.assets.values_list("source_line_id", flat=True))
    start = timezone.localdate()
    created = []

    for line in quotation.lines.select_related("product", "subscription_plan"):
        if line.pk in existing:
            continue

        recurring = line.line_type != QuotationLine.LineType.ONE_TIME
        months = _months(line) * PERIODS_PER_TERM if recurring else 0
        created.append(
            Asset(
                customer=quotation.customer,
                product=line.product,
                source_line=line,
                quotation=quotation,
                qty=line.qty,
                unit_price=line.unit_price,
                start_date=start,
                end_date=_add_months(start, months) if recurring else None,
                mrr=monthly_value(line) if recurring else Decimal("0.00"),
            )
        )

    return Asset.objects.bulk_create(created)


def _add_months(date, months):
    """Same month arithmetic the billing schedule uses; clamped to the month's length."""
    from core.services.billing import _add_months as shared

    return shared(date, months)


def for_customer(customer, include_closed=False):
    """Everything this customer owns, newest first."""
    from core.models import Asset

    rows = Asset.objects.filter(customer=customer).select_related(
        "product", "product__category", "quotation"
    )
    if not include_closed:
        rows = rows.filter(status=Asset.Status.ACTIVE)
    return rows.order_by("-start_date", "product__name")


def mrr_summary(customer=None):
    """Recurring revenue across active assets: MRR, ARR, and the contract count.

    Aggregated in the database. This is the number both Salesforce Revenue Cloud and Odoo
    Subscriptions lead their analytics with, so it is worth being exactly right.
    """
    from core.models import Asset

    rows = Asset.objects.filter(status=Asset.Status.ACTIVE, end_date__isnull=False)
    if customer is not None:
        rows = rows.filter(customer=customer)

    totals = rows.aggregate(
        mrr=Sum("mrr"),
        contracts=Count("id"),
        customers=Count("customer", distinct=True),
    )
    mrr = totals["mrr"] or Decimal("0.00")
    return {
        "mrr": mrr,
        "arr": (mrr * 12).quantize(Decimal("0.01")),
        "contracts": totals["contracts"],
        "customers": totals["customers"],
    }


def due_for_renewal(within_days=90, as_of=None):
    """Active recurring assets whose term ends inside the window, soonest first.

    Includes assets that have already lapsed — an expired contract nobody renewed is more
    urgent than one expiring next month, not less, so it belongs at the top of the queue
    rather than filtered out of it.
    """
    from core.models import Asset

    as_of = as_of or timezone.localdate()
    return list(
        Asset.objects.filter(
            status=Asset.Status.ACTIVE,
            end_date__isnull=False,
            end_date__lte=as_of + timedelta(days=within_days),
            renewed_into__isnull=True,
        )
        .select_related("customer", "customer__tier", "product", "quotation__rep")
        .order_by("end_date")
    )


@transaction.atomic
def create_renewal_quotation(assets, rep):
    """Raise one draft quotation that renews every asset given. FR — the point of assets.

    The renewal is priced through `pricing.resolve_unit_price` at today's price list, not
    at the price on the original order: a renewal is a new agreement, and quietly carrying
    an old price forward is how margin leaks. The difference is visible on the quotation
    because the rep can see both.

    Every asset is marked `RENEWED` and pointed at the new quotation, so the same asset
    cannot be renewed twice and the chain is auditable end to end.

    Raises:
        ValueError: if the assets belong to more than one customer, or none were given.
    """
    from core.models import Asset, Quotation, QuotationLine
    from core.services import approval, pricing

    assets = list(assets)
    if not assets:
        raise ValueError("Nothing to renew.")
    customers = {asset.customer_id for asset in assets}
    if len(customers) > 1:
        raise ValueError("A renewal quotation covers one customer at a time.")

    customer = assets[0].customer
    today = timezone.localdate()
    quotation = Quotation.objects.create(
        number=f"Q-{today.year}-R{Quotation.objects.count() + 1:04d}",
        customer=customer,
        rep=rep,
        stage=Quotation.Stage.DRAFT,
        kind=Quotation.Kind.RENEWAL,
        last_activity_at=timezone.now(),
    )

    for asset in assets:
        product = asset.product
        recurring = product.subscription_plan is not None
        QuotationLine.objects.create(
            quotation=quotation,
            product=product,
            qty=asset.qty,
            unit_price=pricing.resolve_unit_price(product, customer),
            discount_pct=Decimal("0"),
            line_type=(
                QuotationLine.LineType.RECURRING
                if recurring
                else QuotationLine.LineType.ONE_TIME
            ),
            subscription_plan=product.subscription_plan if recurring else None,
        )

    pricing.recompute_quotation(quotation)
    Asset.objects.filter(pk__in=[asset.pk for asset in assets]).update(
        status=Asset.Status.RENEWED, renewed_into=quotation
    )
    approval.record(
        quotation,
        action="RENEWAL_RAISED",
        actor=rep,
        reason=(
            f"Renewal of {len(assets)} asset(s) for {customer.name}, priced at today's "
            f"price list rather than the original order."
        ),
    )
    return quotation


def expire_lapsed(as_of=None):
    """Mark active assets whose term ended and which nobody renewed as EXPIRED.

    Read by nothing automatically — it is a maintenance action, exposed so the renewals
    queue can be honest about what has actually lapsed rather than silently ageing.
    """
    from core.models import Asset

    as_of = as_of or timezone.localdate()
    return Asset.objects.filter(
        status=Asset.Status.ACTIVE, end_date__lt=as_of, renewed_into__isnull=True
    ).update(status=Asset.Status.EXPIRED)


# ------------------------------------------------------------------ amendments (ADR-015)


@transaction.atomic
def create_amendment_quotation(asset, new_qty, rep):
    """Raise a draft amendment that changes the quantity of something already owned.

    An amendment is not a second contract. It edits the asset in place, keeps the existing
    end date — **co-terming** — and charges only for the days remaining in the current
    billing period. Selling ten more seats in month four should not restart the customer's
    term or bill them for a period they are already halfway through.

    Nothing is applied here. This raises the paperwork; `apply_amendment()` runs on
    confirmation, so an amendment goes through the same approval governance as any other
    quotation. A rep cannot change what a customer owns by filling in a form.

    Raises:
        ValueError: if the asset is not an active recurring contract, or the quantity is
            unchanged or below one.
    """
    from core.models import Quotation, QuotationLine
    from core.services import approval, pricing

    if asset.status != asset.Status.ACTIVE:
        raise ValueError("Only an active contract can be amended.")
    if not asset.is_recurring:
        raise ValueError(
            "Only a recurring contract can be amended. A one-time purchase is not a term."
        )
    if new_qty < 1:
        raise ValueError("Quantity must be at least 1.")
    if new_qty == asset.qty:
        raise ValueError("That is the quantity they already have.")

    today = timezone.localdate()
    quotation = Quotation.objects.create(
        number=f"Q-{today.year}-A{Quotation.objects.count() + 1:04d}",
        customer=asset.customer,
        rep=rep,
        stage=Quotation.Stage.DRAFT,
        kind=Quotation.Kind.AMENDMENT,
        amends_asset=asset,
        last_activity_at=timezone.now(),
    )
    product = asset.product
    QuotationLine.objects.create(
        quotation=quotation,
        product=product,
        qty=new_qty,
        unit_price=pricing.resolve_unit_price(product, asset.customer),
        discount_pct=Decimal("0"),
        line_type=QuotationLine.LineType.RECURRING,
        subscription_plan=product.subscription_plan,
    )
    pricing.recompute_quotation(quotation)

    direction = "increase" if new_qty > asset.qty else "reduction"
    approval.record(
        quotation,
        action="AMENDMENT_RAISED",
        actor=rep,
        reason=(
            f"Amendment to {product.name} for {asset.customer.name}: {direction} from "
            f"{asset.qty} to {new_qty}, co-termed to {asset.end_date}. Prorated on "
            f"confirmation for the days left in the current period."
        ),
    )
    return quotation


def amendment_preview(asset, new_qty, as_of=None):
    """What the amendment will cost, before anybody commits to it. Reads only.

    Shown on the amendment quotation so the rep and the approver see the same arithmetic
    the service will perform: how many days remain, what the prorated charge is, and what
    the contract bills from the next period onward.
    """
    from core.services import billing

    as_of = as_of or timezone.localdate()
    line = asset.source_line
    period_start, period_end = billing.current_period(line, as_of)
    days_in_period = (period_end - period_start).days
    days_remaining = max(0, (period_end - as_of).days)

    unit_period_price = (Decimal(line.line_total) / Decimal(asset.qty)).quantize(
        Decimal("0.01")
    )
    delta = Decimal(new_qty - asset.qty)
    prorated = (
        (unit_period_price * delta * Decimal(days_remaining) / Decimal(days_in_period))
        .quantize(Decimal("0.01"))
        if days_in_period
        else Decimal("0.00")
    )
    return {
        "asset": asset,
        "current_qty": asset.qty,
        "new_qty": new_qty,
        "period_start": period_start,
        "period_end": period_end,
        "days_in_period": days_in_period,
        "days_remaining": days_remaining,
        "unit_period_price": unit_period_price,
        "prorated_now": prorated,
        "next_period_amount": (unit_period_price * Decimal(new_qty)).quantize(Decimal("0.01")),
        "co_term_date": asset.end_date,
    }


@transaction.atomic
def apply_amendment(quotation):
    """Apply a confirmed amendment to the asset it references. Idempotent.

    Three things happen, and the order matters:

    1. The **original** line's quantity changes, and `billing.prorate_quantity_change()`
       writes the adjustment for the days remaining and rewrites every future scheduled
       entry at the new quantity. The original line owns the billing schedule, so the
       amendment's own line is paperwork — it is never billed.
    2. The asset's quantity and MRR follow the line.
    3. **`end_date` is not touched.** That is the co-term, and it is the whole point: the
       customer's term does not restart because they bought more seats.
    """
    from core.models import Quotation
    from core.services import approval, billing

    asset = quotation.amends_asset
    if quotation.kind != Quotation.Kind.AMENDMENT or asset is None:
        return None
    if quotation.audit_log.filter(action="AMENDMENT_APPLIED").exists():
        return None  # already applied; both confirmation paths reach this hook

    new_qty = quotation.lines.first().qty
    previous_qty = asset.qty

    entry = billing.prorate_quantity_change(asset.source_line, new_qty)
    asset.source_line.refresh_from_db()
    asset.qty = new_qty
    asset.mrr = monthly_value(asset.source_line)
    asset.save(update_fields=["qty", "mrr"])

    approval.record(
        quotation,
        action="AMENDMENT_APPLIED",
        reason=(
            f"{asset.product.name} moved from {previous_qty} to {new_qty} for "
            f"{asset.customer.name}. Term unchanged \u2014 still ends {asset.end_date}. "
            + (
                f"Prorated adjustment of {entry.amount} for the days remaining."
                if entry
                else "No days remained in the period, so nothing was prorated."
            )
        ),
    )
    return entry

