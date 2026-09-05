"""Context every workspace template needs, added once instead of in eleven views.

Only `approver` lives here. It gates the sidebar links for Approvals, Deal Health and
Reports so a Rep never sees a link that would answer 403 — the server still refuses those
URLs through `require_roles`, which is the check that matters; this only keeps the
navigation honest about what it offers.
"""

from core.views import APPROVER_ROLES


def roles(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"approver": False}
    return {"approver": user.role in APPROVER_ROLES}
