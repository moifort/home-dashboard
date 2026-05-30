"""Crypto-bot trading slice: GraphQL stats + grid snapshot and its render panel.

Optional, live-fetched on each /display pull (no DB table, no listener). Mirrors
the iOS "small" widget.
"""
import logging
import os
from datetime import datetime

import requests

from app.config import PARIS_TZ

logger = logging.getLogger(__name__)

USER_AGENT = "linky-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"

API_URL = os.environ.get("CRYPTO_API_URL", "")
API_TOKEN = os.environ.get("CRYPTO_API_TOKEN", "")

STATS_QUERY = (
    "query { stats { totalProfitUsdc sommeMiseUsdc sandboxMode"
    " periodStats { alltime { holdReturnPercent } } } }"
)

# Grid snapshot: bounds + level count + current price (Stats), plus the 7-day
# price line (PriceHistory). Mirrors the iOS GridSnapshotCard inputs.
GRID_QUERY = (
    "query {"
    " stats { currentPrice gridConfig { lowerPrice upperPrice levels } }"
    " priceHistory { time price }"
    " }"
)


def _post(url: str, query: str, token: str, timeout: float) -> dict | None:
    """POST a GraphQL query, returning the `data` object or None on any error."""
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.post(url, json={"query": query}, headers=headers, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Crypto GraphQL request failed: %s", e)
        return None
    if body.get("errors"):
        logger.warning("Crypto GraphQL errors: %s", body["errors"])
        return None
    return body.get("data") or None


def fetch_crypto_stats(url: str, token: str = "", timeout: float = 5) -> dict | None:
    """Fetch the crypto-bot stats block via GraphQL.

    Returns the `stats` object, or None on any network/HTTP/GraphQL error
    (the panel is simply omitted when data is unavailable).
    """
    data = _post(url, STATS_QUERY, token, timeout)
    if not data:
        return None
    stats = data.get("stats")
    if not stats:
        logger.warning("Crypto stats missing in response")
        return None
    return stats


def _grouped(value: float) -> str:
    """Integer with a plain-space thousands separator (Arial-safe on e-paper)."""
    return f"{value:,.0f}".replace(",", chr(32))


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


def fetch_crypto_grid(url: str, token: str = "", timeout: float = 5) -> dict | None:
    """Fetch the grid snapshot (config + current price + 7-day price line).

    Returns a render-ready dict, or None on any error (the grid is omitted).
    """
    data = _post(url, GRID_QUERY, token, timeout)
    if not data:
        return None

    stats = data.get("stats") or {}
    cfg = stats.get("gridConfig") or {}
    lower = cfg.get("lowerPrice")
    upper = cfg.get("upperPrice")
    levels = cfg.get("levels")
    if lower is None or upper is None or not levels or upper <= lower:
        logger.warning("Crypto grid config incomplete: %s", cfg)
        return None

    points = [
        (p["time"], p["price"])
        for p in (data.get("priceHistory") or [])
        if p.get("time") is not None and p.get("price") is not None
    ]
    points.sort(key=lambda tp: tp[0])

    current = stats.get("currentPrice")
    if current is None and points:
        current = points[-1][1]

    return {
        "lower": float(lower),
        "upper": float(upper),
        "levels": int(levels),
        "current_price": float(current) if current is not None else None,
        "current_price_text": f"${_grouped(current)}" if current is not None else "",
        "points": points,
    }


# --- Slice orchestration: enable, panel, status (no DB, no listener) ---

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


def status() -> dict:
    return {"crypto_enabled": ENABLED, "last_crypto": _last_crypto_time}
