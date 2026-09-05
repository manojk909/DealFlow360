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

from django.core.exceptions import PermissionDenied
from django.shortcuts import render

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
            "lines": quotation.lines.select_related("product").all(),
        },
    )
