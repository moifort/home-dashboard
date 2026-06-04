"""Shared display/parse helpers + the alert-rule descriptor (transverse).

Used by every domain's alerts.py: small parsers (display string -> float) and
money/figure formatters (French decimal comma, Arial-safe thousands), plus the
AlertRule namedtuple the aggregator (app.alerts) collects from each domain.
"""
from collections import namedtuple

# An alert rule contributed by a domain. `fn(data) -> (message, figure[, money])
# | None`; `board` is the status-board section label it belongs to; higher
# `severity` shows first; `good` marks a positive highlight (black, not red).
AlertRule = namedtuple("AlertRule", ["key", "fn", "board", "severity", "good", "enabled"])
AlertRule.__new__.__defaults__ = (True,)  # enabled defaults to True


def _to_float(text):
    """Parse a display string ('153', '18,0', 'N/A', None) to float, or None."""
    if isinstance(text, (int, float)):
        return float(text)
    if text is None:
        return None
    s = str(text).strip().replace(",", ".")
    if not s or s.upper() == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _eur(value):
    """Euro amount with a French decimal comma, e.g. 0.39 -> '0,39'."""
    return f"{abs(value):.2f}".replace(".", ",")


def _money(good, amount, unit="€/j"):
    """A money phrase: 'économie X€/j' (good) or 'dépense X€/j' (bad). The currency
    symbol is glued to the amount so it never wraps onto a line of its own."""
    return f"{'économie' if good else 'dépense'} {_eur(amount)}{unit}"


def _usd(text):
    """Parse a '$11 234' / '+$1 234' / '-$1 234' display amount to float, or None."""
    if not text:
        return None
    s = str(text).replace("$", "").replace("+", "").replace(" ", "").replace(" ", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _usd_fmt(value):
    """Whole-dollar amount with a plain-space thousands separator (Arial-safe)."""
    return f"{round(abs(value)):,}".replace(",", " ")
