"""
django.contrib.admin is the backend configuration area (SPEC §4 A2-A7, ADR-001).

T-01 registers the custom User only. The catalogue, governance and warehouse models are
registered by T-05, T-06 and T-07.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
# Django >= 5.1: the admin's add form is AdminUserCreationForm — it carries the
# `usable_password` field that add_fieldsets below refers to. UserCreationForm does not.
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from core.models import User


class DealFlowUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email", "name", "role")


class DealFlowUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = DealFlowUserCreationForm
    form = DealFlowUserChangeForm
    model = User

    list_display = ("email", "name", "role", "is_active", "is_staff", "created_at")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "name")
    ordering = ("email",)
    readonly_fields = ("created_at", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identity", {"fields": ("name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "role", "usable_password", "password1", "password2"),
            },
        ),
    )
