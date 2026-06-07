"""Assemble the render data dict: the core domain + each enabled optional domain.

Thin orchestrator. The core consumption days/stats come from the electricity
domain; every optional domain contributes its own fields via attach().
"""
from datetime import datetime

from app import alerts as alerts_engine
from app.system.config import PARIS_TZ
from app.registry import CORE, OPTIONAL
from app.system.scheduler import current_screen_refresh, next_screen_refresh, next_screen_wake


def _attach_tariff(home: dict) -> None:
    """Current tariff period + both periods' last switches (live PTEC only;
    absent until the first HC<->HP transition observed since startup, the
    other period's side absent until its own switch has been seen)."""
    tariff = CORE.current_tariff()
    if tariff:
        home["tariff"] = {
            "period": tariff["period"],
            "since_text": f"{tariff['since']:%H:%M}",
        }
        if tariff["other_since"] is not None:
            home["tariff"]["other_period"] = tariff["other_period"]
            home["tariff"]["other_since_text"] = f"{tariff['other_since']:%H:%M}"


def build_home_live(now: datetime) -> dict:
    """Home panel dict for a live ESP32 pull: the actual pull time + the next
    firmware wake, plus the live tariff line (the pull path rebuilds `home`
    from scratch — without this the tariff attached by build_dashboard_data
    would be wiped and never reach the screen)."""
    home = {
        "last_text": f"{now:%H:%M}",
        "next_text": f"{next_screen_wake(now):%H:%M}",
    }
    _attach_tariff(home)
    return home


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
    _attach_tariff(data["home"])
    for integration in OPTIONAL:
        if integration.enabled():
            integration.attach(data)
    # Alerts run last so every integration's trends are already attached.
    data["alert_board"] = alerts_engine.build_board(data)
    return data
