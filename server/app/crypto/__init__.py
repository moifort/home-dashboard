"""Crypto domain — crypto-bot trading panel.

Optional, live-fetched on each /display pull (no DB table, no listener); mirrors
the iOS "small" widget. The point of entry exposes the uniform slice API
(enabled / init_schema / start / attach / status), delegating reads to query and
lifecycle to command. Drop the whole folder to remove the crypto panel.
"""
import os

API_URL = os.environ.get("CRYPTO_API_URL", "")
API_TOKEN = os.environ.get("CRYPTO_API_TOKEN", "")
ENABLED = bool(API_URL)


def enabled() -> bool:
    return ENABLED


from app.crypto.command import init_schema, start  # noqa: E402
from app.crypto.query import attach, status  # noqa: E402
from app.crypto.rules import build_crypto_panel  # noqa: E402

__all__ = [
    "enabled", "init_schema", "start", "attach", "status",
    "ENABLED", "API_URL", "API_TOKEN", "build_crypto_panel",
]
