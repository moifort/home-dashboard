"""Water domain queries (read side): attach the chart + stats, report status."""
from datetime import datetime

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
    data.update(build_water_panel(rows, now, PRICE_M3))


def status() -> dict:
    from app.water import ENABLED

    return {"water_enabled": ENABLED, "last_water": command.last_report}
