"""Solar domain queries (read side): attach the production panel, report status."""
from datetime import datetime

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
    data.update(build_production_panel(prod_by_date, now, data.get("talon"), PRICE_HP))


def status() -> dict:
    from app.solar import ENABLED

    return {
        "ecoflow_enabled": ENABLED,
        "last_solar_report": command.last_solar_report,
        "solar_wh_today": round(command._solar_state["wh"], 2),
        "solar_state_date": command._solar_state["date"],
        "solar_last_pv_watts": command.last_pv_watts,
        "solar_samples": command.sample_count,
    }
