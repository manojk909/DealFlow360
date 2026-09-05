"""
Entry layer for the internal application.

T-01 ships the health check only. Per ARCHITECTURE.md, views authenticate, authorise,
validate and then call a service — they never hold business rules themselves.
"""

from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.shortcuts import render

from core.models import User


def health(request):
    """
    Prove the whole round trip: URL -> view -> ORM -> SQLite -> template.

    Every number on this page is read from db.sqlite3. None of it is a constant; if the
    database is missing or unmigrated this page fails loudly rather than rendering a
    reassuring lie.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT sqlite_version()")
        sqlite_version = cursor.fetchone()[0]

    applied = MigrationRecorder(connection).migration_qs
    users = User.objects.all()

    context = {
        "db_vendor": connection.vendor,
        "db_name": str(connection.settings_dict["NAME"]),
        "sqlite_version": sqlite_version,
        "applied_migrations": applied.count(),
        "latest_migration": applied.order_by("-applied").values_list("app", "name").first(),
        "user_count": users.count(),
        "users_by_role": list(
            users.values_list("role", flat=True).order_by("role").distinct()
        ),
        "auth_user_model": f"{User._meta.app_label}.{User.__name__}",
    }
    return render(request, "core/health.html", context)
