"""GraphQL transport for the crypto-bot API: POST helper + stats/grid fetchers."""
import logging
from datetime import datetime, timezone

import requests

from .queries import GRID_QUERY, STATS_QUERY

logger = logging.getLogger(__name__)

USER_AGENT = "linky-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"

# A placement cycle older than this is considered stale and its skipped levels
# are dropped, so we never surface warnings about a state that may have changed
# (mirrors the iOS PlacementStatusData.isStale 5-minute guard).
PLACEMENT_MAX_AGE_S = 5 * 60


def _parse_iso(value) -> datetime | None:
    """Parse an ISO 8601 timestamp from the bot, or None when it is unusable."""
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Crypto timestamp unparseable: %s", value)
        return None
    # The bot always sends a zone; a bare timestamp is read as UTC rather than
    # as the container's local time (which would shift the plotted cycles).
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _parse_cycles(trades: list | None) -> list[dict]:
    """Validated cycles to plot on the grid: one point per completed trade.

    The point sits on the leg executed last — a cycle opened by an inventory
    sell closes on the buy-back, not on the sell (mirrors the iOS
    GridSnapshotCard). Times are epoch seconds, the same scale as the price-line
    points, so the renderer places both on one axis. A cycle whose legs carry no
    fill is dropped: without a fill price there is nothing to place.
    """
    cycles = []
    for trade in trades or []:
        if trade.get("status") != "completed":
            continue
        legs = []
        for leg in (trade.get("buyOrder"), trade.get("sellOrder")):
            filled = _parse_iso((leg or {}).get("filledAt"))
            price = (leg or {}).get("price")
            if filled is not None and price is not None:
                legs.append((filled.timestamp(), float(price)))
        if not legs:
            continue
        closed_at, price = max(legs)
        cycles.append({
            "time": closed_at,
            "price": price,
            "profit": float(trade.get("profitUsdc") or 0),
        })
    return cycles


def _parse_skips(placement: dict | None) -> list[dict]:
    """Extract the skipped-level warning markers from a placementStatus block.

    Returns a list of {"price", "side", "kind"} for each skipped level, or an
    empty list when there is no placement, it is stale, or it is malformed.
    """
    if not placement:
        return []

    ts = _parse_iso(placement.get("cycleAt"))
    if ts and (datetime.now(timezone.utc) - ts).total_seconds() > PLACEMENT_MAX_AGE_S:
        return []

    skips = []
    for lvl in placement.get("skippedLevels") or []:
        price = lvl.get("price")
        if price is None:
            continue
        skips.append({
            "price": float(price),
            "side": lvl.get("side", ""),
            "kind": ((lvl.get("reason") or {}).get("kind", "")),
        })
    return skips


def _grouped(value: float) -> str:
    """Integer with a plain-space thousands separator (Arial-safe on e-paper)."""
    return f"{value:,.0f}".replace(",", chr(32))


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


def fetch_crypto_grid(url: str, token: str = "", timeout: float = 5) -> dict | None:
    """Fetch the grid snapshot (config, current price, 7-day price line, cycles).

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
        "cycles": _parse_cycles(data.get("trades")),
        "skips": _parse_skips(data.get("placementStatus")),
    }
