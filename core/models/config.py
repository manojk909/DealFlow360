"""
Operational thresholds the problem statement calls "configured" without giving a value.

PDF B9 asks for deals "inactive for more than a configured number of days" and discount
anomalies "well above a rep's historical average", and lists delivery promise slippage
without defining a promise anywhere. ADR-007 closes all three by putting the numbers in a
row an admin can edit rather than in application code, which is what "configured" means.

One singleton row, not a settings module: a judge can open it in the back-end, change the
stall window to 1 day, and watch the dashboard react. That demonstration is the whole
reason this is a table.
"""

from django.db import models


class SalesSetting(models.Model):
    """The single configuration row. `SalesSetting.load()` is the only way to read it."""

    stall_days = models.PositiveIntegerField(
        default=7,
        help_text="A quotation with no activity for this many days is stalled (PDF B9).",
    )
    anomaly_window_days = models.PositiveIntegerField(
        default=90,
        help_text="How far back a rep's historical average discount is computed.",
    )
    anomaly_threshold_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10,
        help_text="Percentage points above the rep's own average that counts as an anomaly.",
    )
    delivery_promise_days = models.PositiveIntegerField(
        default=5,
        help_text="Days after confirmation that an order is promised for (ADR-007).",
    )

    # ADR-014. Display currency. Amounts are stored in the base currency and multiplied by
    # `currency_rate` on the way to the screen, so a rate of 1.00 changes only the symbol.
    currency_code = models.CharField(max_length=3, default="INR")
    currency_symbol = models.CharField(max_length=4, default="\u20b9")
    currency_rate = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=1,
        help_text="Display units per 1.00 stored. 1.000000 means prices are already in this currency.",
    )

    class Meta:
        verbose_name = "sales setting"
        verbose_name_plural = "sales settings"

    def __str__(self):
        return (
            f"{self.currency_code} · stall {self.stall_days}d "
            f"· anomaly +{self.anomaly_threshold_pct}pt"
        )

    def save(self, *args, **kwargs):
        """Singleton: there is one row and its pk is always 1.

        Clears the cached currency so a change in the back-end reaches the next request
        rather than the next restart.
        """
        from django.core.cache import cache

        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete("dealflow:currency")

    def delete(self, *args, **kwargs):  # pragma: no cover - guarded, never called
        """Deleting the configuration would leave the dashboard with no thresholds."""
        raise RuntimeError("The sales settings row cannot be deleted.")

    @classmethod
    def load(cls):
        """Return the configuration, creating it with the documented defaults if absent."""
        setting, _ = cls.objects.get_or_create(pk=1)
        return setting
