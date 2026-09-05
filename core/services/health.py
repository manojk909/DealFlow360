"""
Deal health and anomaly detection — BR-8.

Implements FR-33 (B9). Owned by **T-21**.

**ADR-007 is still open**, deliberately. The PDF says stalled deals are those "inactive
for more than a configured number of days" without giving a default, and defines a
discount anomaly as one "well above a rep's historical average" without quantifying "well
above". Delivery promise slippage is listed with no promise date defined anywhere in the
data model.

What that means for this module:

* `stalled_deals()` can be implemented as soon as a stall window is configured — the
  detection itself is unambiguous, only the threshold is open.
* `discount_anomalies()` must not be implemented until ADR-007 fixes both the threshold
  and how a rep's historical average is computed — over what window, and which
  quotations count.
* `delivery_slippage()` has no data to read: there is no promise-date field anywhere in
  DATA_MODEL.md, because the PDF never names one. It stays unimplemented until ADR-007
  either defines one or drops the indicator.

BACKLOG T-21 says so explicitly: ship stalled-deal detection alone if ADR-007 is still
open, and label the rest incomplete rather than inventing a threshold. An honestly empty
panel costs less than a fabricated number a judge asks about.

This module is **read-side only**. It never writes. The nudge and escalation actions
(FR-39) are BONUS and belong to T-29.
"""


def stalled_deals(as_of=None, stall_days=None):
    """Quotations with no activity for longer than the configured window.

    Reads `Quotation.last_activity_at`, which every state-changing action touches — the
    dashboard is meaningless if that field is not maintained, which is why it is not an
    `auto_now` column.

    Only open stages count. A quotation sitting in PAID or REJECTED is finished, not
    stalled.

    Args:
        as_of: timezone-aware datetime to measure from; defaults to now.
        stall_days: the window. When `None`, read it from configuration — the PDF says
            this number is configured, so a literal here would be a bug.

    Returns:
        queryset of `core.models.Quotation`, most stale first, annotated with days idle.
    """
    raise NotImplementedError("T-21 — deal health dashboard (stall window from ADR-007)")


def discount_anomalies(rep=None, as_of=None):
    """Lines discounted well above the rep's historical average.

    **Blocked by ADR-007.** Both halves are undefined in the problem statement: how far
    above the average counts as an anomaly, and how the average is computed — over which
    window, counting which quotations, weighted by value or not.

    Do not pick numbers here to make the panel render. If ADR-007 is still open when the
    dashboard ships, this panel is absent or labelled incomplete, per CLAUDE.md's
    integrity rule.

    Returns:
        list of anomaly records, each carrying the line, the rep's average, and the
        margin by which it was exceeded, so the alert can explain itself.
    """
    raise NotImplementedError("T-21 — blocked by ADR-007 (anomaly threshold undefined)")


def delivery_slippage(as_of=None):
    """Orders whose delivery promise has slipped.

    **Blocked by ADR-007, and by the data model.** There is no promise-date field on any
    entity because the PDF never names one. Implementing this means first deciding what a
    delivery promise *is* here, adding the field, and recording that in ADR-007.

    Returns:
        list of slippage records.
    """
    raise NotImplementedError("T-21 — blocked by ADR-007 (no promise date is modelled)")


def dashboard(as_of=None):
    """Everything the deal health screen shows, in one call.

    Composes the detectors above. Sections whose detector is still blocked come back
    explicitly marked unavailable, with the reason, so the template renders an honest
    "not built yet" rather than an empty list that reads as "nothing wrong".

    Returns:
        dict with keys `stalled`, `anomalies`, `slippage`, each either a result list or a
        marker naming the ADR that blocks it.
    """
    raise NotImplementedError("T-21 — deal health dashboard")
