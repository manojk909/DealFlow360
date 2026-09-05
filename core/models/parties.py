"""
People and organisations — internal users, customer tiers and customers.

Customers are deliberately **not** Users: portal access is a signed quotation-scoped
token, not an account (ADR-004).
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import MaxValueValidator, MinValueValidator
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
    # ADR-009 item 2. PDF A7 filters reports by "Sales Team / Rep" but describes no team
    # entity, membership or hierarchy, so a team is a label on the user, not a table.
    team = models.CharField(max_length=60, blank=True, default="")

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


class CustomerTier(models.Model):
    """
    Bronze / Silver / Gold, with the tier-level discount ceiling.

    PDF example: Bronze <= 5%, Silver <= 10%, Gold <= 15%. This is one half of a line's
    effective ceiling; the other half is CategoryDiscountCeiling, and the **stricter of
    the two wins** (DATA_MODEL.md invariant 14, ADR-005).
    """

    name = models.CharField(max_length=40, unique=True)
    max_discount_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Tier-level discount ceiling, in percentage points.",
    )

    class Meta:
        ordering = ["max_discount_pct", "name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_discount_pct__gte=0) & models.Q(max_discount_pct__lte=100),
                name="customer_tier_max_discount_in_range",
            )
        ]

    def __str__(self):
        return f"{self.name} (<= {self.max_discount_pct}%)"


class Customer(models.Model):
    """The buying organisation. Has no login — see ADR-004."""

    name = models.CharField(max_length=160, unique=True)
    email = models.EmailField()
    tier = models.ForeignKey(CustomerTier, on_delete=models.PROTECT, related_name="customers")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.tier.name})"
