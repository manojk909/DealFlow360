"""
People and organisations.

T-01 scope is the custom User only. CustomerTier and Customer land in T-02 alongside the
rest of the P0 schema — see docs/DATA_MODEL.md.
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class Role(models.TextChoices):
    """SPEC.md §3. The four roles, checked server-side in every view (ADR-003)."""

    REP = "REP", "Sales Rep"
    MANAGER = "MANAGER", "Sales Manager"
    FINANCE = "FINANCE", "Finance / Operations"
    ADMIN = "ADMIN", "Admin"


class UserManager(BaseUserManager):
    """Email is the login identifier — DATA_MODEL.md gives User no username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("role", Role.REP)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("role", Role.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra["is_staff"] is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra["is_superuser"] is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """
    DATA_MODEL.md: id, email (unique), password_hash, name, role, created_at.

    Customers are deliberately NOT Users — portal access is token-scoped (ADR-004).
    """

    email = models.EmailField("email address", unique=True)
    name = models.CharField("full name", max_length=150)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.REP)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        help_text="Can sign in to the backend configuration area at /admin/.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return f"{self.name} <{self.email}>"

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name.split(" ")[0] if self.name else self.email
