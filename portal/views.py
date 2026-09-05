"""
Customer portal views — **a separate, restricted surface** (PDF §7, ADR-004).

Three rules hold in this module and are the reason it is a separate app:

* Nothing here is behind `login_required`, and **nothing here reads `request.user`**.
  A customer has no account. If a view in this file ever needs to know who is signed in,
  something has gone wrong.
* A token resolves to exactly one quotation. Any failure — missing, malformed, tampered,
  unknown, or not the token issued for that quotation — is a **403**, never the quotation
  and never a redirect to the internal login page.
* No internal navigation is reachable from these pages. The customer sees their quotation
  and nothing else in the system.
"""

from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import QuotationLine

from core.services import negotiation


def _resolve(token):
    """Token to quotation, or a 403. The single entry point for every view below."""
    try:
        return negotiation.resolve_token(token)
    except negotiation.PortalAccessDenied as exc:
        # One response for every failure mode: distinguishing "bad signature" from "no
        # such quotation" would tell an attacker which quotation ids exist.
        raise PermissionDenied(str(exc))


def quotation_view(request, token):
    """The customer's view of one quotation."""
    quotation = _resolve(token)
    return render(
        request,
        "portal/quotation.html",
        {
            "quotation": quotation,
            "token": token,
            "status": negotiation.portal_status(quotation),
            "error": request.GET.get("error"),
            "sent": request.GET.get("sent"),
            "can_act": quotation.stage
            in {"SENT", "UNDER_NEGOTIATION", "APPROVED"},
            "awaiting_approval": quotation.approval_steps.filter(
                status="PENDING"
            ).exists(),
            "lines": quotation.lines.select_related(
                "product", "subscription_plan"
            ).all(),
            # Append-only, oldest first: it reads as a conversation.
            "messages": quotation.portal_messages.select_related(
                "quotation_line__product"
            ).order_by("created_at"),
        },
    )


def _line_or_none(quotation, raw):
    """A line id from the form, scoped to this quotation. Anything else is order-level."""
    if not raw:
        return None
    return get_object_or_404(QuotationLine, pk=raw, quotation=quotation)


def _back(token, error=None, sent=None):
    url = f"/portal/{token}/"
    if error:
        return redirect(f"{url}?error={quote(error)}")
    if sent:
        return redirect(f"{url}?sent={quote(sent)}")
    return redirect(url)


@require_POST
def comment_view(request, token):
    """FR-22. A question or change request, optionally against one line."""
    quotation = _resolve(token)
    try:
        negotiation.add_comment(
            quotation,
            request.POST.get("body", ""),
            line=_line_or_none(quotation, request.POST.get("line_id")),
        )
    except ValueError as exc:
        return _back(token, error=str(exc))
    return _back(token, sent="Your message has been sent.")


@require_POST
def counter_view(request, token):
    """FR-23. A counter-discount, which re-scores and may re-enter approval on its own."""
    quotation = _resolve(token)
    try:
        counter = Decimal(str(request.POST.get("counter_discount_pct", "")).strip())
    except (InvalidOperation, TypeError):
        return _back(token, error="Enter a discount as a number, for example 15.")

    try:
        negotiation.submit_counter_offer(
            quotation,
            counter,
            line=_line_or_none(quotation, request.POST.get("line_id")),
            body=request.POST.get("body", ""),
        )
    except ValueError as exc:
        return _back(token, error=str(exc))
    return _back(token, sent="Your proposal has been sent to the account team.")


@require_POST
def confirm_view(request, token):
    """FR-24. The customer accepts the quotation as it stands."""
    quotation = _resolve(token)
    try:
        negotiation.confirm(quotation)
    except ValueError as exc:
        return _back(token, error=str(exc))
    return _back(token)
