"""Render an amount in the configured display currency.

Every template used to hard-code `&euro;` beside a `floatformat`, which meant the currency
was a hundred literals rather than a setting. It is one filter now, reading the symbol,
the code and the conversion factor off `SalesSetting`.

**Amounts are stored in the base currency and converted on display.** `currency_rate` is
"display units per 1.00 stored", so leaving it at 1.00 changes nothing but the symbol,
and setting it converts every screen at once. That is the smallest thing that is honestly
a currency factor: no rate table, no historical rates, and no pretence of either.

The setting is cached — a page renders this filter fifty times and must not issue fifty
queries. `SalesSetting.save()` clears the entry, so a change in the back-end shows up on
the next request rather than after a restart.
"""

from decimal import Decimal, InvalidOperation

from django import template
from django.core.cache import cache

register = template.Library()

CACHE_KEY = "dealflow:currency"
CACHE_SECONDS = 300


def display_currency():
    """(symbol, code, rate) for the configured currency, cached between requests."""
    cached = cache.get(CACHE_KEY)
    if cached is None:
        from core.models import SalesSetting

        setting = SalesSetting.load()
        cached = (setting.currency_symbol, setting.currency_code, setting.currency_rate)
        cache.set(CACHE_KEY, cached, CACHE_SECONDS)
    return cached


def group_indian(digits):
    """Group the integer part the Indian way: last three, then pairs. 1234567 -> 12,34,567.

    The default market for this product is India, where 12,34,567 is what a number looks
    like and 1,234,567 reads as foreign. Western grouping is one `if` away if the display
    currency is ever changed to one that uses it.
    """
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


@register.filter
def money(value, places=2):
    """`{{ amount|money }}` -> ₹12,34,567.89 · `{{ amount|money:0 }}` -> ₹12,34,568."""
    try:
        amount = Decimal(str(value or 0)) * display_currency()[2]
    except (InvalidOperation, TypeError, ValueError):
        return value

    places = int(places)
    quantum = Decimal(1).scaleb(-places) if places else Decimal(1)
    amount = amount.quantize(quantum)

    sign = "-" if amount < 0 else ""
    text = f"{abs(amount):f}"
    whole, _, fraction = text.partition(".")
    grouped = group_indian(whole)
    return f"{sign}{display_currency()[0]}{grouped}" + (f".{fraction}" if fraction else "")


@register.simple_tag
def currency_code():
    """The ISO code, for column headers and exports where a symbol is not enough."""
    return display_currency()[1]
