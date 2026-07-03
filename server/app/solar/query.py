"""Solar domain queries (read side): attach the production panel, report status."""
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.solar import command
from app.solar.infrastructure import repository
from app.solar.rules import build_production_panel, fetch_window


def attach(data: dict):
    """Add the solar production history + stats (last 9 days, ending today)."""
    from app.solar import PRICE_HP

    now = datetime.now(PARIS_TZ)
    start, end = fetch_window(now)
    prod_by_date = {p["date"]: p["pv_kwh"] for p in repository.get_cached_production(start, end)}
    # Intraday PV profiles over the chart's 9 shown days — feeds the mini
    # graph under each Solaire bar.
    profiles = repository.get_pv_profiles(
        (now - timedelta(days=8)).strftime("%Y-%m-%d"),
        (now + timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    data.update(build_production_panel(prod_by_date, now, data.get("days"), PRICE_HP,
                                       pv_profiles=profiles))


LIVE_MAX_AGE_S = 15 * 60  # a live figure older than this is stale — hide it


def live_power(now: datetime | None = None) -> dict | None:
    """The inverter's instantaneous PV watts for the Home panel, or None when no
    fresh heartbeat exists — the line disappears rather than showing stale watts."""
    if command.last_pv_watts is None or not command.last_solar_report:
        return None
    now = now or datetime.now(PARIS_TZ)
    seen = datetime.fromisoformat(command.last_solar_report)
    if (now - seen).total_seconds() > LIVE_MAX_AGE_S:
        return None
    return {"watts_text": f"{round(command.last_pv_watts)}"}


def status() -> dict:
    from app.solar import ENABLED

    return {
        "ecoflow_enabled": ENABLED,
        "last_solar_report": command.last_solar_report,
        "solar_wh_today": round(command._integrator.wh, 2),
        "solar_state_date": command._integrator.date,
        "solar_last_pv_watts": command.last_pv_watts,
        "solar_samples": command.sample_count,
    }
