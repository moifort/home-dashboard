"""Plants reads — attach the per-plant views to the render data dict.

Each plant's current values are the freshest stored reading within a short
lookback (the sensor reports only 1-2x/day, so today's row alone would dash out
every morning); the last 8 days back the 7-day moisture spark. Reads the DB
only (the MQTT listener is the sole writer).
"""
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.plants import rules
from app.plants.infrastructure import repository


# Fallback window for the card's current values: today plus this many previous
# days. The sensor reports only once or twice a day, so right after midnight
# today's row doesn't exist yet; beyond the window a dead sensor dashes out.
_LOOKBACK_DAYS = 2


def _current(slug: str, today) -> dict:
    """The freshest known value of each metric within the lookback window."""
    rows = [repository.get_day(slug, (today - timedelta(days=n)).strftime("%Y-%m-%d"))
            for n in range(_LOOKBACK_DAYS + 1)]
    return rules.latest_metrics(rows)


def _history(slug: str, today) -> dict:
    """date→moisture over the last 8 days (the spark window), from the DB."""
    week_ago = (today - timedelta(days=8)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    return {r["date"]: r["moisture"]
            for r in repository.get_cached_plants(slug, week_ago, today_str)
            if r["moisture"] is not None}


def attach(data: dict, sensors):
    """Attach one render entry per plant, in declared order."""
    today = datetime.now(PARIS_TZ).date()
    data["plants"] = [
        rules.build_plant_view(
            s.name, _current(s.slug, today),
            _history(s.slug, today), today, s.threshold)
        for s in sensors
    ]
