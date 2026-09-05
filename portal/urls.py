"""
Customer portal URLs — mounted at /portal/ by config/urls.py.

The shape is fixed by ADR-004: `/portal/<token>/`, where the token is a signed
TimestampSigner value over one quotation's id. Views here must never sit behind
`login_required` and must never read `request.user`.

The portal has no models of its own; it reads core's through the services layer.
"""

from django.urls import path

from portal import views

app_name = "portal"

urlpatterns = [
    path("<str:token>/", views.quotation_view, name="quotation"),
]
