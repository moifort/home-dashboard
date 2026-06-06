"""Electricity domain queries (read side): build the core panel, report status."""
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.electricity import command
from app.electricity.infrastructure import repository
from app.electricity.rules import build_core as _build_core


def build_core(days: list[dict]) -> dict:
    """Build the base render dict (the consumption days + stats + talon)."""
    from app.electricity import PRICE_ABO_MONTHLY, PRICE_HC, PRICE_HP

    now = datetime.now(PARIS_TZ)
    # Intraday PAPP profiles over the same calendar window as the chart's 9
    # shown days — feeds the mini graph under each EDF bar.
    profiles = repository.get_papp_profiles(
        (now - timedelta(days=8)).strftime("%Y-%m-%d"),
        (now + timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    return _build_core(days, now, PRICE_HP, PRICE_HC, PRICE_ABO_MONTHLY,
                       papp_profiles=profiles)


def status() -> dict:
    """Status fragment for the /status endpoint."""
    from app.electricity import HC_WINDOWS_RAW, TOPIC

    period, _ = command._period
    return {
        "linky_topic": TOPIC,
        "hc_windows": HC_WINDOWS_RAW,
        "current_period": period,
        "last_linky_message": command.last_message_time,
        "last_hchc": command.last_hchc,
        "last_hphp": command.last_hphp,
        "last_error": command.last_error,
    }
