"""Assemble the render data dict: Linky core + each enabled optional slice.

Thin orchestrator. The core consumption days/stats come from the Linky slice;
every optional integration contributes its own fields via attach().
"""
from datetime import datetime, timedelta

from app import alerts as alerts_engine
from app.config import DAYS_FR, PARIS_TZ, REFRESH_INTERVAL
from app.integrations import OPTIONAL, linky


def build_dashboard_data(days: list[dict]) -> dict:
    data = linky.build_core(days)
    now = datetime.now(PARIS_TZ)
    data["last_updated"] = now.isoformat()
    # "Home" panel: weekday + time of this refresh, and the time of the next one
    # (this cycle + the hourly refresh interval). Weekday lowercase per the
    # e-paper font rules.
    next_update = now + timedelta(seconds=REFRESH_INTERVAL)
    data["home"] = {
        "last_text": f"{DAYS_FR[now.weekday()].lower()} {now:%H:%M}",
        "next_text": f"{next_update:%H:%M}",
    }
    for integration in OPTIONAL:
        if integration.enabled():
            integration.attach(data)
    # Alerts run last so every integration's trends are already attached.
    data["alert_board"] = alerts_engine.build_board(data)
    return data
