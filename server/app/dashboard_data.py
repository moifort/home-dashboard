"""Assemble the render data dict: Linky core + each enabled optional slice.

Thin orchestrator. The core consumption days/stats come from the Linky slice;
every optional integration contributes its own fields via attach().
"""
from datetime import datetime

from app import alerts as alerts_engine
from app.config import PARIS_TZ
from app.integrations import OPTIONAL, linky
from app.schedule import current_screen_refresh, next_screen_refresh


def build_dashboard_data(days: list[dict]) -> dict:
    data = linky.build_core(days)
    now = datetime.now(PARIS_TZ)
    data["last_updated"] = now.isoformat()
    # "Home" panel: the screen-refresh schedule (when the ESP shows this image and
    # when it will next refresh), rendered on one line. Both derive from the shared
    # boundary math so the displayed times match the firmware's wake schedule.
    this_refresh = current_screen_refresh(now)
    data["home"] = {
        "last_text": f"{this_refresh:%H:%M}",
        "next_text": f"{next_screen_refresh(this_refresh):%H:%M}",
    }
    for integration in OPTIONAL:
        if integration.enabled():
            integration.attach(data)
    # Alerts run last so every integration's trends are already attached.
    data["alert_board"] = alerts_engine.build_board(data)
    return data
