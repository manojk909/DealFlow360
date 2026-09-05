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
    path("workspace/pipeline/", views.pipeline, name="pipeline"),

    # T-37 — the signed-in user's own page
    path("workspace/profile/", views.profile, name="profile"),
    path(
        "workspace/profile/password/",
        auth_views.PasswordChangeView.as_view(
            template_name="core/password_change.html",
            success_url="/workspace/profile/?tab=preferences&changed=1",
        ),
        name="password_change",
    ),

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
    # T-41 — customers, assets and renewals (ADR-013)
    path("workspace/customers/", views.customer_list, name="customer_list"),
    path("workspace/customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("workspace/renewals/", views.renewal_list, name="renewal_list"),
    path("workspace/renewals/<int:pk>/create/", views.renewal_create, name="renewal_create"),

    # T-38 — warehouses (A4)
    path("workspace/warehouses/", views.warehouse_list, name="warehouse_list"),
    path("workspace/warehouses/<int:pk>/", views.warehouse_detail, name="warehouse_detail"),

    path("workspace/fulfilment/", views.fulfilment_list, name="fulfilment_list"),
    path("workspace/fulfilment/<int:pk>/", views.fulfilment_detail, name="fulfilment_detail"),
    path("workspace/fulfilment/<int:pk>/accept/", views.fulfilment_accept, name="fulfilment_accept"),
    path("workspace/fulfilment/<int:pk>/override/", views.fulfilment_override, name="fulfilment_override"),
    path(
        "workspace/fulfilment/<int:pk>/lines/<int:line_id>/consolidate/",
        views.fulfilment_consolidate, name="fulfilment_consolidate",
    ),

    # T-17 — invoicing and payment
    path("workspace/invoices/", views.billing_list, name="billing_list"),
    path("workspace/invoices/<int:pk>/", views.billing_detail, name="billing_detail"),
    path("workspace/invoices/<int:pk>/generate/", views.billing_generate, name="billing_generate"),
    path("workspace/invoices/<int:pk>/pay/", views.billing_pay, name="billing_pay"),

    # T-21 — deal health and anomaly dashboard (B9)
    path("workspace/health/", views.deal_health, name="deal_health"),
    path("workspace/health/<int:pk>/nudge/", views.deal_health_nudge, name="deal_health_nudge"),

    # T-20 — subscriptions and hybrid billing (B7)
    path("workspace/subscriptions/", views.subscription_list, name="subscription_list"),
    path(
        "workspace/invoices/<int:pk>/lines/<int:line_id>/prorate/",
        views.subscription_prorate, name="subscription_prorate",
    ),
    path(
        "workspace/invoices/<int:pk>/lines/<int:line_id>/cancel/",
        views.subscription_cancel, name="subscription_cancel",
    ),

    # T-23 — reporting with filters (A7)
    path("workspace/reports/", views.reports, name="reports"),
    path("workspace/reports/export.csv", views.reports_export, name="reports_export"),

    # T-13 — approval
    path("workspace/approvals/", views.approval_list, name="approval_list"),
    path("workspace/approvals/<int:pk>/", views.approval_detail, name="approval_detail"),
    path("workspace/approvals/<int:pk>/act/", views.approval_act, name="approval_act"),
]
