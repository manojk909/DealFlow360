"""
Model package, split by domain to reduce merge conflicts across four developers
(ARCHITECTURE.md). Everything is re-exported here, so import from `core.models`.

T-01 ships the custom User only. The remaining P0 entities arrive with T-02.
"""

from core.models.parties import Role, User

__all__ = ["Role", "User"]
