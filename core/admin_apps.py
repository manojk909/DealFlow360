"""
Installs DealFlowAdminSite as the default admin site.

This is Django's documented way to replace it: INSTALLED_APPS lists
`core.admin_apps.DealFlowAdminConfig` **instead of** `django.contrib.admin`. Every
`@admin.register(...)` in core/admin.py then registers against our site with no further
change.

It lives in its own module rather than in core/apps.py because two AppConfig subclasses
in one module makes Django's app-config autodetection ambiguous — it cannot tell which is
the default for the `core` app.
"""

from django.contrib.admin import apps as admin_apps


class DealFlowAdminConfig(admin_apps.AdminConfig):
    default_site = "core.admin_site.DealFlowAdminSite"
