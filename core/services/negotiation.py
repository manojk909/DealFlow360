"""
Portal negotiation and the re-approval loop — BR-6, ADR-004, ADR-010.

Implements FR-02, FR-21, FR-22, FR-23 and FR-24. Owned by **T-14** and **T-15**.

> After a customer counters: if the new terms exceed the approval thresholds, the
> quotation **automatically** re-enters the approval flow. Otherwise it goes straight to
> fulfilment.

This is AC-7 and the single best moment in the demo — a customer action, taken with no
user account, that moves an internal deal back into governance on its own.

Access rules, non-negotiable (ADR-004, DATA_MODEL.md invariant 12):

* A token grants access to **exactly one** quotation. Enforced server-side, here.
* Portal callers have no `User`. Nothing in this module may read `request.user`, and
  audit rows written on their behalf carry `actor=None`.
* A tampered, unsigned or unknown token raises `PortalAccessDenied`, which the view turns
  into a **403** — never the quotation, and never a redirect to the internal login page.

**A counter-discount replaces the targeted line's discount. It does not stack on top as a
second order-level discount.** This is load-bearing for DEMO Flow B: Beta's 15% counter
against a 10% Silver ceiling is 5 points over, inside the Manager-only band. Stacking it
onto the line's existing 8% would give roughly 21 points over, pull in Finance, and leave
the demo script one approval short.
"""

from decimal import Decimal


class PortalAccessDenied(Exception):
    """The token is missing, malformed, unsigned, tampered with, or unknown.

    One exception for every failure mode on purpose: distinguishing "bad signature" from
    "no such quotation" in the response would tell an attacker which quotation ids exist.
    """


def resolve_token(token):
    """Resolve a signed portal token to exactly one quotation.

    Verified with `django.core.signing.TimestampSigner`. `max_age` is deliberately **not**
    passed — ADR-004 records that tokens do not expire, because a link going stale
    mid-demo is pure downside. The property relied on is that the token is unforgeable,
    not that it is short-lived.

    Args:
        token: the signed string from the URL.

    Returns:
        The `core.models.Quotation`.

    Raises:
        PortalAccessDenied: for every failure mode.
    """
    raise NotImplementedError("T-14 — portal access and restricted view")


def portal_status(quotation):
    """The customer-facing status: a **display mapping over `stage`**, not a stored field.

    ADR-010's mapping, which is why there is no second status column to drift:

    * SENT to "Sent"
    * UNDER_NEGOTIATION, PENDING_APPROVAL, APPROVED to "Under Negotiation"
    * CONFIRMED, FULFILLED, INVOICED, PAID to "Confirmed"
    * REJECTED to "Closed"

    The customer therefore never sees an internal approval stage — they see that their
    quotation is being looked at, which is true and is all they are entitled to.

    Returns:
        One of the four strings above.
    """
    raise NotImplementedError("T-14 — portal access and restricted view")


def portal_link(quotation, request=None):
    """The absolute `/portal/<token>/` URL, minting the token if there is not one yet.

    Copied from the internal quotation screen by the rep. **No email is sent** — ADR-004
    closed that sub-question, because SMTP is a live network dependency in the middle of
    a demo and no acceptance criterion asks for it.
    """
    raise NotImplementedError("T-14 — portal access and restricted view")


def add_comment(quotation, body, line=None):
    """Append a customer comment to the negotiation thread. FR-22.

    Append-only: a negotiation history that can be edited is not a negotiation history.
    `line` is optional because order-level messages exist.

    Moves the quotation from SENT to UNDER_NEGOTIATION and touches `last_activity_at`.

    Returns:
        The created `core.models.PortalMessage`.
    """
    raise NotImplementedError("T-15 — portal negotiation and the re-approval loop")


def submit_counter_offer(quotation, counter_discount_pct, line=None, body=""):
    """Apply a counter-discount, re-score, and re-enter approval when required. FR-23.

    Sequence, in one transaction:
      1. Append the `PortalMessage` carrying `counter_discount_pct` (append-only).
      2. **Replace** the targeted line's `discount_pct` — see the module note; do not add
         an order-level discount on top. With no `line`, the counter applies to every
         line, again by replacement.
      3. `pricing.recompute_quotation()`.
      4. `risk.score_for_quotation()` and store the new snapshot.
      5. If the score requires any approver level, call `approval.submit(actor=None)`,
         which generates **fresh** ApprovalStep rows and moves the stage to
         PENDING_APPROVAL (invariant 13). Otherwise the stage becomes UNDER_NEGOTIATION
         and the customer may confirm straight through.
      6. Audit row with `actor=None`, attributed to the customer via the quotation.

    Args:
        quotation: resolved from a token, never from a user session.
        counter_discount_pct: Decimal between 0 and 100.
        line: optional `core.models.QuotationLine` belonging to this quotation.
        body: optional free text accompanying the counter.

    Returns:
        The updated `Quotation`.

    Raises:
        ValueError: if `line` belongs to a different quotation, or the percentage is out
            of range.
    """
    raise NotImplementedError("T-15 — portal negotiation and the re-approval loop")


def confirm(quotation):
    """Customer confirms the quotation. FR-24, BR-6's other branch.

    Permitted only when the current terms need no outstanding approval — ADR-010 allows
    CONFIRMED from APPROVED, SENT and UNDER_NEGOTIATION, and from UNDER_NEGOTIATION only
    while the live score still requires nothing. If a counter has pushed the score over a
    threshold, the re-approval edge fires first and confirm is refused until an approver
    has acted.

    Moves the stage to CONFIRMED, writes an audit row with `actor=None`, and hands the
    order on to fulfilment.

    Raises:
        ValueError: if the quotation is not in a stage that can be confirmed, or an
            approval is outstanding.
    """
    raise NotImplementedError("T-15 — portal negotiation and the re-approval loop")
