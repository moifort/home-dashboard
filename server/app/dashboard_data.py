"""Assemble the render data dict: the core domain + each enabled optional domain.

Thin orchestrator. The core consumption days/stats come from the electricity
domain; every optional domain contributes its own fields via attach().
"""
from datetime import datetime

from app import alerts as alerts_engine
from app.system.config import PARIS_TZ
from app.registry import CORE, OPTIONAL
from app.system.scheduler import current_screen_refresh, next_screen_refresh


def build_dashboard_data(days: list[dict]) -> dict:
    data = CORE.build_core(days)
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
