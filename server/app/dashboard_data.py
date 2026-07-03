"""Assemble the render data dict: the core domain + each enabled optional domain.

Thin orchestrator. The core consumption days/stats come from the electricity
domain; every optional domain contributes its own fields via attach().
"""
from datetime import datetime

from app import alerts as alerts_engine
from app import battery
from app.system.config import DAYS_FR, MONTHS_FR, PARIS_TZ
from app.registry import CORE, OPTIONAL
from app.system.scheduler import current_screen_refresh, next_screen_refresh, next_screen_wake


def _date_text(now: datetime) -> str:
    """Today as 'mar. 2 juin' — French, lowercase (e-paper rule), no locale
    dependency (Docker images ship C.UTF-8 only)."""
    return f"{DAYS_FR[now.weekday()].lower()}. {now.day} {MONTHS_FR[now.month - 1]}"


def _attach_battery(home: dict, now: datetime) -> None:
    """Add the ESP32 autonomy line ('jours depuis la dernière charge') to the Home
    panel. Done here — not in battery.attach — because the live pull path rebuilds
    `home` from scratch, which would otherwise drop an attached key (like the
    tariff)."""
    if not battery.enabled():
        return
    view = battery.query.home_line(now)
    if view:
        home["battery"] = view


def _attach_tariff(home: dict) -> None:
    """All recently completed windows as 'HH:MM ► HH:MM' lines, grouped HC then HP
    (live PTEC only; each period's lines absent until its own windows have
    completed since startup, so the panel fills up over the day). The period label
    is shown only on the first line of each group; the rest are left blank."""
    tariff = CORE.current_tariff()
    if not tariff:
        return
    lines = []
    for key, label in (("hc", "HC"), ("hp", "HP")):
        for i, (start, end) in enumerate(tariff.get(key) or []):
            lines.append({"period": label if i == 0 else "",
                          "start_text": f"{start:%H:%M}",
                          "end_text": f"{end:%H:%M}"})
    if lines:
        home["tariff"] = lines


def build_home_live(now: datetime) -> dict:
    """Home panel dict for a live ESP32 pull: the actual pull time + the next
    firmware wake, plus the live tariff line (the pull path rebuilds `home`
    from scratch — without this the tariff attached by build_dashboard_data
    would be wiped and never reach the screen)."""
    home = {
        "date_text": _date_text(now),
        "last_text": f"{now:%H:%M}",
        "next_text": f"{next_screen_wake(now):%H:%M}",
    }
    _attach_tariff(home)
    _attach_battery(home, now)
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
        "date_text": _date_text(now),
        "last_text": f"{this_refresh:%H:%M}",
        "next_text": f"{next_screen_refresh(this_refresh):%H:%M}",
    }
    _attach_tariff(data["home"])
    _attach_battery(data["home"], now)
    for integration in OPTIONAL:
        if integration.enabled():
            integration.attach(data)
    # Alerts run last so every integration's trends are already attached.
    data["alert_board"] = alerts_engine.build_board(data)
    return data
