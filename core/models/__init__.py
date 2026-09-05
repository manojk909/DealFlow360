"""
Model package, split by domain (ARCHITECTURE.md). Everything is re-exported here, so the
rest of the application imports from `core.models` and never from a submodule.

Cross-domain foreign keys are declared as strings (`"core.Product"`) rather than as
imports, so these modules can be loaded in any order and no import cycle is possible.
"""

from core.models.billing import (
    BillingScheduleEntry,
    Invoice,
    Payment,
    SubscriptionPlan,
)
from core.models.assets import Asset
from core.models.config import SalesSetting
from core.models.catalogue import (
    Category,
    PriceListEntry,
    Product,
    ProductPair,
    ProductVariant,
)
from core.models.inventory import FulfilmentAllocation, Stock, Warehouse
from core.models.parties import Customer, CustomerTier, Role, User
from core.models.sales import (
    ApprovalChainRule,
    ApprovalStep,
    AuditLog,
    CategoryDiscountCeiling,
    PortalMessage,
    Quotation,
    QuotationLine,
)

__all__ = [
    # parties
    "Role",
    "User",
    "CustomerTier",
    "Customer",
    # configuration (ADR-007)
    "SalesSetting",
    # assets (ADR-013)
    "Asset",
    # catalogue
    "Category",
    "Product",
    "ProductVariant",
    "PriceListEntry",
    "ProductPair",
    # sales / governance
    "CategoryDiscountCeiling",
    "ApprovalChainRule",
    "Quotation",
    "QuotationLine",
    "ApprovalStep",
    "AuditLog",
    "PortalMessage",
    # inventory
    "Warehouse",
    "Stock",
    "FulfilmentAllocation",
    # billing
    "SubscriptionPlan",
    "BillingScheduleEntry",
    "Invoice",
    "Payment",
]
