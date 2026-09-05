"""Root URL configuration for DealFlow360."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # django.contrib.admin IS the backend configuration area (SPEC §4 A2-A7, ADR-001).
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]
