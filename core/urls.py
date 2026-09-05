"""URLs for the internal application — the rep workspace and the approval screen.

Everything internal lives under /workspace/. The customer portal is a separate app on its
own prefix with its own access rule (ADR-004), and nothing here is reachable from it.
"""

from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from core import views

app_name = "core"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="core:quotation_list", permanent=False)),
    path("health/", views.health, name="health"),

    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="core/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="core:login"), name="logout"),

    # T-11 — workspace landing page
    path("workspace/", views.quotation_list, name="quotation_list"),

    # T-12 — quotation builder, plus the HTMX endpoints that swap its live region
    path("workspace/quotations/<int:pk>/", views.quotation_builder, name="quotation_builder"),
    path("workspace/quotations/<int:pk>/lines/add/", views.line_add, name="line_add"),
    path("workspace/quotations/<int:pk>/lines/<int:line_id>/", views.line_update, name="line_update"),
    path("workspace/quotations/<int:pk>/lines/<int:line_id>/delete/", views.line_delete, name="line_delete"),
    path("workspace/quotations/<int:pk>/order-discount/", views.order_discount, name="order_discount"),
    path("workspace/quotations/<int:pk>/submit/", views.quotation_submit, name="quotation_submit"),

    # T-13 — approval
    path("workspace/approvals/", views.approval_list, name="approval_list"),
    path("workspace/approvals/<int:pk>/", views.approval_detail, name="approval_detail"),
    path("workspace/approvals/<int:pk>/act/", views.approval_act, name="approval_act"),
]
