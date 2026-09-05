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
    path("signup/", views.signup, name="signup"),

    # T-11 — workspace landing page
    path("workspace/", views.quotation_list, name="quotation_list"),

    # T-12 — quotation builder, plus the HTMX endpoints that swap its live region
    path("workspace/quotations/<int:pk>/", views.quotation_builder, name="quotation_builder"),
    path("workspace/quotations/<int:pk>/lines/add/", views.line_add, name="line_add"),
    path("workspace/quotations/<int:pk>/lines/<int:line_id>/", views.line_update, name="line_update"),
    path("workspace/quotations/<int:pk>/lines/<int:line_id>/delete/", views.line_delete, name="line_delete"),
    path("workspace/quotations/<int:pk>/order-discount/", views.order_discount, name="order_discount"),
    path("workspace/quotations/<int:pk>/upsell/add/", views.upsell_add, name="upsell_add"),
    path("workspace/quotations/<int:pk>/upsell/dismiss/", views.upsell_dismiss, name="upsell_dismiss"),
    path("workspace/quotations/<int:pk>/submit/", views.quotation_submit, name="quotation_submit"),
    path("workspace/quotations/<int:pk>/share/", views.quotation_share, name="quotation_share"),

    # T-16 — fulfilment
    path("workspace/fulfilment/", views.fulfilment_list, name="fulfilment_list"),
    path("workspace/fulfilment/<int:pk>/", views.fulfilment_detail, name="fulfilment_detail"),
    path("workspace/fulfilment/<int:pk>/accept/", views.fulfilment_accept, name="fulfilment_accept"),
    path("workspace/fulfilment/<int:pk>/override/", views.fulfilment_override, name="fulfilment_override"),

    # T-17 — invoicing and payment
    path("workspace/invoices/", views.billing_list, name="billing_list"),
    path("workspace/invoices/<int:pk>/", views.billing_detail, name="billing_detail"),
    path("workspace/invoices/<int:pk>/generate/", views.billing_generate, name="billing_generate"),
    path("workspace/invoices/<int:pk>/pay/", views.billing_pay, name="billing_pay"),

    # T-13 — approval
    path("workspace/approvals/", views.approval_list, name="approval_list"),
    path("workspace/approvals/<int:pk>/", views.approval_detail, name="approval_detail"),
    path("workspace/approvals/<int:pk>/act/", views.approval_act, name="approval_act"),
]
