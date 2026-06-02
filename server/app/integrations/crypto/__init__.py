"""Crypto-bot trading slice.

Self-contained vertical slice: the GraphQL transport + queries live in graphql/,
and below the orchestration that builds the banner panel. Optional, live-fetched
on each /display pull (no DB table, no listener). Mirrors the iOS "small" widget.
Remove the whole folder to drop the crypto panel.
"""
import logging
import os
from datetime import datetime

from app.config import PARIS_TZ

from .graphql.transport import _grouped, fetch_crypto_grid, fetch_crypto_stats

logger = logging.getLogger(__name__)

API_URL = os.environ.get("CRYPTO_API_URL", "")
API_TOKEN = os.environ.get("CRYPTO_API_TOKEN", "")

ENABLED = bool(API_URL)
_last_crypto_time = ""


def enabled() -> bool:
    return ENABLED


def init_schema():
    """No persistent storage: crypto is fetched live on each pull."""


def start():
    """No background listener for crypto."""
    return None


def attach(data: dict):
    """Fetch crypto-bot stats and attach the rendered panel fields.

    On any failure the key is left unset, so the panel is simply omitted.
    """
    global _last_crypto_time
    stats = fetch_crypto_stats(API_URL, API_TOKEN)
    if not stats:
        return
    data["crypto"] = build_crypto_panel(stats)
    # Grid snapshot chart (independent: a failure just omits the chart, the
    # banner still shows).
    grid = fetch_crypto_grid(API_URL, API_TOKEN)
    if grid:
        data["crypto_grid"] = grid
    _last_crypto_time = datetime.now(PARIS_TZ).isoformat()


def build_crypto_panel(stats: dict) -> dict:
    """Derive the display fields used by the renderer from raw stats.

    Mirrors CryptoBotWidget.swift (small family): percentage return, signed
    profit, portfolio value and sandbox flag.
    """
    profit = stats.get("totalProfitUsdc", 0.0)
    somme_mise = stats.get("sommeMiseUsdc", 0.0)

    pct = (profit / somme_mise * 100) if somme_mise > 0 else 0.0
    sign = "+" if profit >= 0 else "-"
    portfolio = somme_mise + profit

    # Alpha = the bot's return minus the buy-and-hold return over the same
    # (all-time) period: how much the strategy beat just holding BTC.
    hold = ((stats.get("periodStats") or {}).get("alltime") or {}).get("holdReturnPercent")
    alpha = (pct - hold) if hold is not None else None

    return {
        "pct_text": f"{pct:+.0f}",
        "profit_positive": profit >= 0,
        "profit_text": f"{sign}${_grouped(abs(profit))}",
        "portfolio_text": f"${_grouped(portfolio)}",
        "alpha_text": f"{alpha:+.0f}" if alpha is not None else "",
        "alpha_positive": alpha is None or alpha >= 0,
        "sandbox": bool(stats.get("sandboxMode", False)),
    }


def status() -> dict:
    return {"crypto_enabled": ENABLED, "last_crypto": _last_crypto_time}
