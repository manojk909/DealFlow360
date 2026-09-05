"""
Customer portal URLs — mounted at /portal/ by config/urls.py.

**Reserved, not yet implemented.** T-14 and T-15 fill this in. It exists now so that
adding a portal route later is a change to this file only, never to config/urls.py.

The shape is fixed by ADR-004: `/portal/<token>/`, where the token is a signed
TimestampSigner value over one quotation's id. Views here must never sit behind
`login_required` and must never read `request.user` — a customer has no account.
A tampered or unknown token returns 403, never a redirect to the internal login.

The portal has no models of its own; it reads core's through the services layer.
"""

app_name = "portal"

urlpatterns = []
