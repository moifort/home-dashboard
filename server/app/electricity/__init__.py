"""Electricity domain — Linky consumption (core/mandatory) + power sensors.

The core (Linky HC/HP + talon baseline) is always on; the optional `power`
sub-domain (Cumulus, Lave-linge… generic Z2M power sensors) lives in
electricity/power/ and is iterated by the orchestrator as an optional slice.

The point of entry exposes the Linky core slice API (init_schema / fetch_and_cache
/ build_core / status), delegating reads to query, writes to command, the HC/HP +
talon math to rules, and transport (REST + the daily_consumption repository) to
infrastructure. Per-domain config (token, prices, HC windows) lives here.
"""
import os

from app.electricity.infrastructure.linky_client import parse_hc_windows

TOKEN = os.environ.get("LINKY_TOKEN", "")
PRM = os.environ.get("LINKY_PRM", "")
PRICE_HP = float(os.environ.get("PRICE_HP", "0.2065"))
PRICE_HC = float(os.environ.get("PRICE_HC", "0.1579"))
PRICE_ABO_MONTHLY = float(os.environ.get("PRICE_ABO_MONTHLY", "15.65"))
HC_WINDOWS_RAW = os.environ.get("HC_WINDOWS", "23:32-5:32,15:02-17:02")
HC_WINDOWS = parse_hc_windows(HC_WINDOWS_RAW)


from app.electricity.command import fetch_and_cache, init_schema  # noqa: E402
from app.electricity.query import build_core, status  # noqa: E402

__all__ = [
    "init_schema", "fetch_and_cache", "build_core", "status",
    "TOKEN", "PRM", "PRICE_HP", "PRICE_HC", "PRICE_ABO_MONTHLY",
    "HC_WINDOWS", "HC_WINDOWS_RAW",
]
