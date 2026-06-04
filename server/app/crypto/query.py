"""Crypto domain queries (read side).

Live-fetches the bot stats on each pull and attaches the rendered panel fields.
On any failure the keys are left unset, so the panel is simply omitted.
"""
import logging
from datetime import datetime

from app.system.config import PARIS_TZ
from app.crypto.infrastructure.graphql.transport import fetch_crypto_grid, fetch_crypto_stats
from app.crypto.rules import build_crypto_panel

logger = logging.getLogger(__name__)

_last_crypto_time = ""


def attach(data: dict):
    """Fetch crypto-bot stats and attach the rendered panel fields.

    On any failure the key is left unset, so the panel is simply omitted.
    """
    global _last_crypto_time
    from app.crypto import API_TOKEN, API_URL

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
    from app.crypto import ENABLED

    return {"crypto_enabled": ENABLED, "last_crypto": _last_crypto_time}
