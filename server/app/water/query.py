"""Water domain queries (read side): attach the chart + stats, report status."""
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.water import command
from app.water.infrastructure import repository
from app.water.rules import build_water_panel, fetch_window


def attach(data: dict):
    """Attach the water chart + stats from the meter's index history."""
    from app.water import PRICE_M3

    now = datetime.now(PARIS_TZ)
    start, end = fetch_window(now)
    rows = repository.get_cached_water(start, end)
    # Intraday litre profiles over the chart's 9 shown days — feeds the mini
    # graph under each Eau bar.
    profiles = repository.get_water_litre_profiles(
        (now - timedelta(days=8)).strftime("%Y-%m-%d"),
        (now + timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    data.update(build_water_panel(rows, now, PRICE_M3, litre_profiles=profiles))


def status() -> dict:
    from app.water import ENABLED

    return {"water_enabled": ENABLED, "last_water": command.last_report}
