"""Shared display/parse helpers + the alert-rule descriptor (transverse).

Used by every domain's alerts.py: small parsers (display string -> float) and
money/figure formatters (French decimal comma, Arial-safe thousands), plus the
AlertRule namedtuple the aggregator (app.alerts) collects from each domain.
"""
import logging
import os
from collections import namedtuple

logger = logging.getLogger(__name__)


def env_float(name: str, default: float) -> float:
    """A float env var, falling back to `default` when unset, empty or
    malformed (with a warning) — a bad value must not crash the import."""
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default %s", name, raw, default)
        return default

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


def format_energy_kwh(kwh, period):
    """Adaptive (value, unit) for a daily energy figure on the bottom table:
    whole Wh below 1 kWh, 1-decimal kWh above, so a tiny but real plug
    consumption never collapses to '0.0'. `period` is the unit suffix glued
    after the value ('', '/j') — e.g. 0.028 kWh -> ('28', 'Wh')."""
    wh = round(kwh * 1000)
    if wh < 1000:  # decided on the rounded Wh so 0.9996 kWh reads "1.0 kWh", not "1000 Wh"
        return f"{wh}", f"Wh{period}"
    return f"{kwh:.1f}", f"kWh{period}"


def format_cost_eur(eur):
    """Adaptive text for a monthly cost on the bottom table: one decimal (French
    comma) below 10 €, whole euros above — a cheap plug reads '2,4' instead of
    collapsing to '2', while a heavy one stays uncluttered ('16')."""
    return f"{eur:.1f}".replace(".", ",") if eur < 10 else f"{round(eur)}"


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
