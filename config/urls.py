"""
Root URL configuration for DealFlow360.

**This file only mounts apps.** Every route belongs in an app's own `urls.py`, so adding
a screen never means editing this file. Keeping it stable matters because it is one of
the single-file bottlenecks CLAUDE.md names.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # django.contrib.admin IS the backend configuration area (SPEC 4 A2-A7, ADR-001).
    path("admin/", admin.site.urls),
    # Customer portal — separate app, separate templates, token-scoped access (ADR-004).
    path("portal/", include("portal.urls")),
    # Internal application: workspace, approval, fulfilment.
    path("", include("core.urls")),
]
