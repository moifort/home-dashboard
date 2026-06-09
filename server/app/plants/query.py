"""Plants reads — attach the per-plant views to the render data dict.

Today's row gives each plant its current soil moisture; the last 8 days back the
7-day moisture spark. Reads the DB only (the MQTT listener is the sole writer).
"""
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.plants import rules
from app.plants.infrastructure import repository


def _history(slug: str, today) -> dict:
    """date→moisture over the last 8 days (the spark window), from the DB."""
    week_ago = (today - timedelta(days=8)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    return {r["date"]: r["moisture"]
            for r in repository.get_cached_plants(slug, week_ago, today_str)
            if r["moisture"] is not None}


def attach(data: dict, sensors):
    """Attach one render entry per plant, in declared order."""
    now = datetime.now(PARIS_TZ)
    today = now.date()
    today_str = today.strftime("%Y-%m-%d")
    data["plants"] = [
        rules.build_plant_view(
            s.name, repository.get_day(s.slug, today_str) or {},
            _history(s.slug, today), today, s.threshold)
        for s in sensors
    ]
