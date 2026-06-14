"""Battery domain business rules: pure functions (no IO).

Turns the firmware's per-pull telemetry (RTC bootCount + esp_reset_reason) into
battery-cycle boundaries, and the recorded cycles into the "since last charge"
figure plus autonomy stats. A cycle = one run on a charge: it opens on a power-on
(alimentation rétablie après recharge / batterie vide) and ends at the last pull
before the next power-on.
"""
from datetime import datetime, timedelta

# esp_reset_reason() value for a timer wake from deep sleep (our normal 2h cycle).
# Any other reason (1 = POWERON, 9 = BROWNOUT, panic…) means the device actually
# restarted — the start of a fresh battery cycle.
DEEPSLEEP_REASON = 8


def is_power_on(reason: int | None, boot: int | None, last_boot: int | None) -> bool:
    """Whether this pull starts a new battery cycle.

    True when the reset reason is anything other than the deep-sleep timer (a real
    restart: power-on, brownout…), or — as a fallback when the reason is missing —
    when the RTC bootCount dropped back to/under the last seen value (the counter
    only resets when power was lost)."""
    if reason is not None and reason != DEEPSLEEP_REASON:
        return True
    if boot is not None and last_boot is not None and boot <= last_boot:
        return True
    return False


def _duration_text(td: timedelta) -> str:
    """A compact French duration: '6h', '18h', '4j', '4j 6h'."""
    total_hours = int(td.total_seconds() // 3600)
    days, hours = divmod(total_hours, 24)
    if days >= 1:
        return f"{days}j {hours}h" if hours else f"{days}j"
    return f"{hours}h"


def _single_unit(td: timedelta) -> tuple[str, str]:
    """The dominant (value, unit) for the gluable Home figure: days once past a
    day, else hours — e.g. timedelta(days=4, hours=6) -> ('4', 'j')."""
    total_hours = int(td.total_seconds() // 3600)
    days, hours = divmod(total_hours, 24)
    if days >= 1:
        return str(days), "j"
    return str(hours), "h"


def build_battery_view(cycles: list[dict], now: datetime) -> dict | None:
    """The battery panel view from the recorded cycles, or None if none yet.

    The last cycle is the current run: 'since last charge' = now - its start. The
    earlier cycles are completed runs whose duration (ended_at - started_at) feeds
    the average / record autonomy stats (surfaced on /status)."""
    if not cycles:
        return None

    current = cycles[-1]
    since = now - datetime.fromisoformat(current["started_at"])
    if since < timedelta(0):
        since = timedelta(0)
    value, unit = _single_unit(since)

    completed = [
        datetime.fromisoformat(c["ended_at"]) - datetime.fromisoformat(c["started_at"])
        for c in cycles[:-1]
    ]
    avg_text = record_text = None
    if completed:
        avg = sum(completed, timedelta()) / len(completed)
        avg_text = _duration_text(avg)
        record_text = _duration_text(max(completed))

    return {
        "since_value": value,
        "since_unit": unit,
        "since_text": _duration_text(since),
        "avg_text": avg_text,
        "record_text": record_text,
        "cycles": len(completed),
    }
