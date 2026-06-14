"""Battery domain queries (read side): the autonomy view + status.

`home_line` is the reusable view-builder the orchestrator re-injects into the Home
panel on every pull (the live path rebuilds `home` from scratch); `attach` exposes
the same view at the top level for /api/data; `status` summarises it for /status.
"""
from datetime import datetime

from app.battery import command
from app.battery.infrastructure import repository
from app.battery.rules import build_battery_view
from app.system.config import PARIS_TZ


def home_line(now: datetime | None = None) -> dict | None:
    """The battery view (since-last-charge + autonomy stats), or None if no cycle
    has been recorded yet. Like the other live panels, it omits itself rather than
    breaking the render if the store can't be read."""
    now = now or datetime.now(PARIS_TZ)
    try:
        return build_battery_view(repository.get_cycles(), now)
    except Exception:
        return None


def attach(data: dict):
    """No-op: the battery line is injected into the Home panel by the orchestrator
    (`dashboard_data._attach_battery`), which owns `home` and the build's `now` —
    so it stays deterministic and survives the live pull's home rebuild. Kept for
    the uniform slice API the registry iterates."""
    return None


def status() -> dict:
    from app.battery import ENABLED

    view = home_line()
    return {
        "battery_enabled": ENABLED,
        "battery_last_report": command.last_report,
        "battery_since": view["since_text"] if view else None,
        "battery_avg": view["avg_text"] if view else None,
        "battery_record": view["record_text"] if view else None,
        "battery_cycles": view["cycles"] if view else 0,
    }
