"""Electricity domain queries (read side): build the core panel, report status."""
from datetime import datetime

from app.system.config import PARIS_TZ
from app.electricity import command
from app.electricity.rules import build_core as _build_core


def build_core(days: list[dict]) -> dict:
    """Build the base render dict (the consumption days + stats + talon)."""
    from app.electricity import PRICE_ABO_MONTHLY, PRICE_HC, PRICE_HP

    now = datetime.now(PARIS_TZ)
    return _build_core(days, now, PRICE_HP, PRICE_HC, PRICE_ABO_MONTHLY)


def status() -> dict:
    """Status fragment for the /status endpoint."""
    from app.electricity import HC_WINDOWS_RAW, PRM

    return {
        "prm": PRM,
        "hc_windows": HC_WINDOWS_RAW,
        "last_fetch": command.last_fetch_time,
        "last_error": command.last_error,
    }
