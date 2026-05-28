"""GraphQL client for the crypto-bot trading stats (mirrors the iOS "small" widget)."""
import logging

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "linky-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"

STATS_QUERY = "query { stats { totalProfitUsdc sommeMiseUsdc sandboxMode } }"


def fetch_crypto_stats(url: str, token: str = "", timeout: float = 5) -> dict | None:
    """Fetch the crypto-bot stats block via GraphQL.

    Returns the `stats` object, or None on any network/HTTP/GraphQL error
    (the panel is simply omitted when data is unavailable).
    """
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.post(url, json={"query": STATS_QUERY}, headers=headers, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Crypto stats fetch failed: %s", e)
        return None

    if body.get("errors"):
        logger.warning("Crypto GraphQL errors: %s", body["errors"])
        return None
    stats = (body.get("data") or {}).get("stats")
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

    return {
        "pct_text": f"{abs(pct):.0f}",
        "profit_positive": profit >= 0,
        "profit_text": f"{sign}${_grouped(abs(profit))}",
        "portfolio_text": f"${_grouped(portfolio)}",
        "sandbox": bool(stats.get("sandboxMode", False)),
    }
