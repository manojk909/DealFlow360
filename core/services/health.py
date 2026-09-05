"""
Deal health and anomaly detection — BR-8. Implements FR-33 (B9). Owned by **T-21**.

**ADR-007 is closed.** The three thresholds the PDF leaves open now live on the
`SalesSetting` row rather than in this module, because the PDF calls them "configured".
Change the row in the back-end and every detector below moves with it.

* **Stalled** — no activity for more than `stall_days`, and still in an open stage.
* **Anomaly** — a line discounted more than `anomaly_threshold_pct` points above the
  rep's own mean discount over the last `anomaly_window_days`. Measured against the rep's
  own history, per the PDF's wording, not against a company-wide number.
* **Slippage** — a confirmed order past `promised_delivery_date` that has not shipped.
  The promise is set at confirmation (`delivery_promise_days`); orders confirmed before
  that field existed have none and are skipped rather than guessed at.

This module is **read-side only**. It never writes. The nudge action (FR-39, T-29) writes
an audit row through `approval.record`, not through here.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q
from django.utils import timezone

from core.models import Quotation, QuotationLine, SalesSetting

# Stages where a quotation is still someone's problem. PAID and REJECTED are finished, so
# they can be idle forever without being stalled.
OPEN_STAGES = [
    Quotation.Stage.DRAFT,
    Quotation.Stage.PENDING_APPROVAL,
    Quotation.Stage.APPROVED,
    Quotation.Stage.SENT,
    Quotation.Stage.UNDER_NEGOTIATION,
    Quotation.Stage.CONFIRMED,
    Quotation.Stage.FULFILLED,
    Quotation.Stage.INVOICED,
]

# A quotation counts towards a rep's discount history once it has left DRAFT: a half-built
# draft is not evidence of how that rep prices.
HISTORY_STAGES = [s for s in OPEN_STAGES if s != Quotation.Stage.DRAFT] + [
    Quotation.Stage.PAID,
    Quotation.Stage.REJECTED,
]


def stalled_deals(as_of=None, stall_days=None):
    """Open quotations with no activity for longer than the configured window.

    Reads `Quotation.last_activity_at`, which every state-changing action touches.
    """
    as_of = as_of or timezone.now()
    if stall_days is None:
        stall_days = SalesSetting.load().stall_days
    cutoff = as_of - timedelta(days=stall_days)

    rows = []
    for quotation in (
        Quotation.objects.filter(stage__in=OPEN_STAGES, last_activity_at__lt=cutoff)
        .select_related("customer", "rep")
        .order_by("last_activity_at")
    ):
        rows.append(
            {
                "quotation": quotation,
                "days_idle": (as_of - quotation.last_activity_at).days,
                "stall_days": stall_days,
            }
        )
    return rows


def rep_average_discount(rep, as_of=None, window_days=None):
    """The rep's mean line discount over the window. `None` when they have no history."""
    as_of = as_of or timezone.now()
    if window_days is None:
        window_days = SalesSetting.load().anomaly_window_days

    return QuotationLine.objects.filter(
        quotation__rep=rep,
        quotation__stage__in=HISTORY_STAGES,
        quotation__created_at__gte=as_of - timedelta(days=window_days),
    ).aggregate(avg=Avg("discount_pct"))["avg"]


def discount_anomalies(rep=None, as_of=None):
    """Lines discounted well above the rep whose quotation it is — their own average.

    A rep with no prior history has no average to be above, so their lines cannot be
    anomalies. That is deliberate: the alternative is flagging every line a new rep writes.
    """
    as_of = as_of or timezone.now()
    setting = SalesSetting.load()

    lines = QuotationLine.objects.filter(discount_pct__gt=0).select_related(
        "quotation", "quotation__customer", "quotation__rep", "product"
    )
    if rep is not None:
        lines = lines.filter(quotation__rep=rep)

    # One grouped query for every rep's average, not one per rep: the loop below touches
    # each line, and a per-rep AVG inside it made the dashboard cost grow with headcount.
    averages = {
        row["quotation__rep"]: row["avg"]
        for row in QuotationLine.objects.filter(
            quotation__stage__in=HISTORY_STAGES,
            quotation__created_at__gte=as_of - timedelta(days=setting.anomaly_window_days),
        )
        .values("quotation__rep")
        .annotate(avg=Avg("discount_pct"))
    }

    rows = []
    for line in lines:
        average = averages.get(line.quotation.rep_id)
        if average is None:
            continue
        over_by = Decimal(line.discount_pct) - Decimal(average)
        if over_by >= setting.anomaly_threshold_pct:
            rows.append(
                {
                    "line": line,
                    "quotation": line.quotation,
                    "rep_average_pct": Decimal(average).quantize(Decimal("0.01")),
                    "over_by_pct": over_by.quantize(Decimal("0.01")),
                    "threshold_pct": setting.anomaly_threshold_pct,
                }
            )
    rows.sort(key=lambda row: row["over_by_pct"], reverse=True)
    return rows


def delivery_slippage(as_of=None):
    """Confirmed orders past their delivery promise that have not fully shipped.

    "Not shipped" means no non-backorder allocation exists, which is what `fulfilment`
    writes when stock is actually reserved.
    """
    as_of = as_of or timezone.now()
    # The configured zone's date, not UTC's: see the note in billing.py.
    today = timezone.localdate(as_of)

    rows = []
    for quotation in (
        Quotation.objects.filter(
            promised_delivery_date__lt=today,
            stage__in=[
                Quotation.Stage.CONFIRMED,
                Quotation.Stage.FULFILLED,
                Quotation.Stage.INVOICED,
            ],
        )
        .select_related("customer", "rep")
        .annotate(
            shipped=Count("allocations", filter=Q(allocations__is_backorder=False)),
            backordered=Count("allocations", filter=Q(allocations__is_backorder=True)),
        )
        .order_by("promised_delivery_date")
    ):
        if quotation.shipped and not quotation.backordered:
            continue
        rows.append(
            {
                "quotation": quotation,
                "days_late": (today - quotation.promised_delivery_date).days,
                "backordered_lines": quotation.backordered,
            }
        )
    return rows


def dashboard(as_of=None):
    """Everything the deal health screen shows, in one call."""
    as_of = as_of or timezone.now()
    setting = SalesSetting.load()
    stalled = stalled_deals(as_of=as_of)
    anomalies = discount_anomalies(as_of=as_of)
    slippage = delivery_slippage(as_of=as_of)
    return {
        "setting": setting,
        "stalled": stalled,
        "anomalies": anomalies,
        "slippage": slippage,
        "alert_count": len(stalled) + len(anomalies) + len(slippage),
        "as_of": as_of,
    }
