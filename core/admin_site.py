"""
The admin site for DealFlow360.

Django's default index lists every registered model in one flat alphabetical column.
With twenty-two models that is unusable — "Approval chain rules" and "Audit logs" sit next
to each other despite one being configuration you edit and the other an append-only trail
you only read.

This subclass groups them into sections that match the domain boundaries in
ARCHITECTURE.md, and separates **configuration you change** from **transactional data the
system writes**. That distinction is the one an admin actually needs: everything in the
first three sections is safe to edit, and editing it changes system behaviour on the next
quotation with no code change.

Nothing here is a hand-written CRUD screen. It is the stock Django admin with its index
reordered and a stylesheet — ADR-001's decision to use the admin as the backend
configuration area is unchanged.
"""

from django.contrib import admin

# Section name -> the models it contains, in the order they should appear.
# Any registered model not named here still shows up, in a trailing "Other" section, so
# adding a model and forgetting this file loses nothing.
SECTIONS = [
    (
        "Pricing and discount governance",
        "Ceilings, tiers and approval bands. Editing these changes routing on the next "
        "quotation — no code change.",
        ["CustomerTier", "CategoryDiscountCeiling", "ApprovalChainRule", "PriceListEntry"],
    ),
    (
        "Catalogue",
        "What we sell, what it costs us, and what it is worth suggesting alongside.",
        ["Category", "Product", "ProductVariant", "SubscriptionPlan", "ProductPair"],
    ),
    (
        "Inventory",
        "Warehouses and live stock. Shipping weight drives the fulfilment split.",
        ["Warehouse", "Stock"],
    ),
    (
        "Customers",
        "Buying organisations and the tier that sets their discount ceiling.",
        ["Customer"],
    ),
    (
        "Quotations and approvals",
        "Transactional. Totals, margin and risk score are computed by the services layer "
        "and shown read-only.",
        ["Quotation", "QuotationLine", "ApprovalStep", "AuditLog", "PortalMessage"],
    ),
    (
        "Fulfilment and billing",
        "Transactional. Allocations and payments are written by their services, never by "
        "hand.",
        ["FulfilmentAllocation", "Invoice", "Payment", "BillingScheduleEntry"],
    ),
    (
        "People and access",
        "Internal users and their roles. Customers are deliberately not users — portal "
        "access is a signed token.",
        ["User", "Group"],
    ),
]


class DealFlowAdminSite(admin.AdminSite):
    site_header = "DealFlow360"
    site_title = "DealFlow360 admin"
    index_title = "Backend configuration"

    def get_app_list(self, request, app_label=None):
        """Regroup the flat model list into the sections above.

        Falls back to Django's own behaviour when a single app is being viewed, so the
        per-app pages and the sidebar breadcrumbs keep working normally.
        """
        app_list = super().get_app_list(request, app_label)
        if app_label:
            return app_list

        # Flatten every model Django would have shown, keyed by its class name.
        by_name = {}
        for app in app_list:
            for model in app["models"]:
                by_name[model["object_name"]] = model

        sections = []
        placed = set()
        for name, description, model_names in SECTIONS:
            models = [by_name[m] for m in model_names if m in by_name]
            if not models:
                continue
            placed.update(m["object_name"] for m in models)
            sections.append(
                {
                    "name": name,
                    "app_label": "dealflow",
                    "app_url": "",
                    "has_module_perms": True,
                    "models": models,
                    "description": description,
                }
            )

        # Anything registered but not listed in SECTIONS still appears, rather than
        # silently vanishing from the index.
        leftover = [m for object_name, m in by_name.items() if object_name not in placed]
        if leftover:
            sections.append(
                {
                    "name": "Other",
                    "app_label": "other",
                    "app_url": "",
                    "has_module_perms": True,
                    "models": sorted(leftover, key=lambda m: m["name"]),
                    "description": "Registered but not yet grouped in core/admin_site.py.",
                }
            )
        return sections
