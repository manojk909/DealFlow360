"""URLs for the internal application. The rep workspace arrives with T-11."""

from django.urls import path
from django.views.generic import RedirectView

from core import views

app_name = "core"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="core:health", permanent=False)),
    path("health/", views.health, name="health"),
]
