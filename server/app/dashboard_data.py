"""Assemble the render data dict: the core domain + each enabled optional domain.

Thin orchestrator. The core consumption days/stats come from the electricity
domain; every optional domain contributes its own fields via attach().
"""
from datetime import datetime, timedelta

from app import alerts as alerts_engine
from app import battery, solar
from app.system.config import DAYS_FR, MONTHS_FR, PARIS_TZ
from app.registry import CORE, OPTIONAL
from app.system.scheduler import current_screen_refresh, next_screen_refresh, next_screen_wake


def _date_text(now: datetime) -> str:
    """Today as 'mar. 2 juin' — French, lowercase (e-paper rule), no locale
    dependency (Docker images ship C.UTF-8 only)."""
    return f"{DAYS_FR[now.weekday()].lower()}. {now.day} {MONTHS_FR[now.month - 1]}"


def _attach_live(home: dict, now: datetime) -> None:
    """The 'right now' lines of the Home panel: the meter's instantaneous draw
    (+ current HC/HP period) and the live PV watts. Each line simply stays absent
    when its source has no fresh sample (listener down, night for the inverter's
    keep-alive gaps, cold start)."""
    grid = CORE.live_power(now)
    if grid:
        home["live_grid"] = grid
    if solar.enabled():
        pv = solar.live_power(now)
        if pv:
            home["live_solar"] = pv


def _attach_net_cost(home: dict, data: dict, now: datetime) -> None:
    """The month's net home cost on one Home line: grid electricity + water
    − solar savings, month-to-date, with an end-of-month projection ('58 ► ~87€').
    Cross-domain by nature, so composed here from the month figures each enabled
    domain attached to its own stats; absent domains simply contribute nothing."""
    elec = (data.get("stats") or {}).get("month_cost_eur")
    if elec is None:
        return

    def _part(block, key):
        return (data.get(block) or {}).get(key) or 0.0

    net = elec + _part("water_stats", "month_cost_eur") \
        - _part("production_stats", "month_savings_eur")
    entry = {"mtd_text": f"{round(net)}"}
    # Projection: complete days only (a partial today would drag it down),
    # scaled to the month length. None on the 1st (no complete day yet).
    elapsed = now.day - 1
    if elapsed >= 1:
        net_complete = ((data.get("stats") or {}).get("month_cost_complete_eur") or 0.0) \
            + _part("water_stats", "month_cost_complete_eur") \
            - _part("production_stats", "month_savings_complete_eur")
        month_days = (now.replace(month=now.month % 12 + 1, day=1,
                                  year=now.year + (now.month == 12)) - timedelta(days=1)).day
        entry["proj_text"] = f"{round(net_complete / elapsed * month_days)}"
    home["net_cost"] = entry


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


def build_home_live(now: datetime, data: dict | None = None) -> dict:
    """Home panel dict for a live ESP32 pull: the actual pull time + the next
    firmware wake, plus the live tariff line (the pull path rebuilds `home`
    from scratch — without this the tariff attached by build_dashboard_data
    would be wiped and never reach the screen). Pass the freshly built render
    dict as `data` so the net-cost line is recomposed onto the new home."""
    home = {
        "date_text": _date_text(now),
        "last_text": f"{now:%H:%M}",
        "next_text": f"{next_screen_wake(now):%H:%M}",
    }
    _attach_tariff(home)
    _attach_battery(home, now)
    _attach_live(home, now)
    if data:
        _attach_net_cost(home, data, now)
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
    _attach_live(data["home"], now)
    for integration in OPTIONAL:
        if integration.enabled():
            integration.attach(data)
    # Net cost composes across domains, so it waits for every attach.
    _attach_net_cost(data["home"], data, now)
    # Alerts run last so every integration's trends are already attached.
    data["alert_board"] = alerts_engine.build_board(data)
    return data
