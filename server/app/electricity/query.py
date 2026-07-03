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


LIVE_MAX_AGE_S = 15 * 60  # a live figure older than this is stale — hide it


def live_power(now: datetime | None = None) -> dict | None:
    """The meter's instantaneous draw for the Home panel: last PAPP (W) + the
    current tariff period, or None when no fresh frame exists (listener down,
    cold start) — the line simply disappears rather than showing stale watts."""
    if command.last_papp is None or not command.last_message_time:
        return None
    now = now or datetime.now(PARIS_TZ)
    seen = datetime.fromisoformat(command.last_message_time)
    if (now - seen).total_seconds() > LIVE_MAX_AGE_S:
        return None
    return {"watts_text": f"{round(command.last_papp)}", "period": command._period}


def status() -> dict:
    """Status fragment for the /status endpoint."""
    from app.electricity import TOPIC

    return {
        "linky_topic": TOPIC,
        "current_period": command._period,
        "last_linky_message": command.last_message_time,
        "last_hchc": command.last_hchc,
        "last_hphp": command.last_hphp,
        "last_error": command.last_error,
    }
