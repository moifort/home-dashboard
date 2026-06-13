"""Plants business rules — pure, no IO.

Builds the per-plant display card from its current reading and its recent daily
moisture history. The card's title line carries a red water-drop icon when soil
moisture falls below the plant's watering threshold and a red battery icon when
its battery is low; line 2 shows humidity, temperature and illuminance with a
7-day moisture spark.
"""
from datetime import datetime, timedelta

# battery_state enum values that mean "battery low" (red battery icon).
_BATTERY_LOW = ("low", "empty", "critical")

# Days shown by the moisture spark (the card's mini-graph). The renderer sizes the
# bars from the returned series, so this is the single source of truth.
SPARK_DAYS = 10


def latest_metrics(rows: list) -> dict:
    """Merge day rows (newest first, today first; None for absent days) into
    the freshest known value of each field. A soil reading is a slowly-moving
    instantaneous state, so yesterday's value beats an em dash right after the
    midnight rollover (the sensor reports only once or twice a day)."""
    merged = {}
    for row in rows:
        for key, value in (row or {}).items():
            if value is not None and key not in merged:
                merged[key] = value
    return merged


def moisture_spark(history: dict, today, days: int = SPARK_DAYS) -> list:
    """The last `days` complete days' soil moisture (oldest→newest, ending
    yesterday); None for any day with no reading (keeps the spark's gap)."""
    return [history.get((today - timedelta(days=n)).strftime("%Y-%m-%d"))
            for n in range(days, 0, -1)]


def relative_time(last_iso, now) -> str | None:
    """A compact "time since last reading" label from an ISO timestamp and the
    current instant, shown as a prefix left of the plant's name: "0min", "12min",
    "3h", "2j". None when there's no timestamp or it can't be parsed (the card
    then shows no last-seen). A clock skew (future timestamp) clamps to "0min"."""
    if not last_iso or now is None:
        return None
    try:
        last = datetime.fromisoformat(last_iso)
    except (TypeError, ValueError):
        return None
    minutes = int(max(0.0, (now - last).total_seconds()) // 60)
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}j"


def _int_text(value):
    """A metric rounded to a plain integer string, or an em dash when absent."""
    return str(round(value)) if value is not None else "—"


def build_plant_view(name: str, current: dict, history: dict, today,
                     threshold=None, last_seen=None, now=None) -> dict:
    """Assemble one plant's render dict. `current` is today's latest reading (or
    empty), `history` maps date→moisture over the recent window, `last_seen` is
    the ISO timestamp of the plant's last report (rendered as a relative
    "il y a …" label against `now`).

    needs_water is purely soil-moisture-vs-threshold (moisture < threshold); the
    device's own `water_warning` is ignored. With no threshold or no moisture
    reading there is no watering flag. low_battery comes from `battery_state`."""
    moisture = current.get("moisture") if current else None
    fertility = current.get("fertility") if current else None
    illuminance = current.get("illuminance") if current else None
    temperature = current.get("temperature") if current else None

    needs_water = (moisture is not None and threshold is not None
                   and moisture < threshold)

    battery = current.get("battery_state") if current else None
    low_battery = battery is not None and str(battery).strip().lower() in _BATTERY_LOW

    return {
        "name": name,
        "moisture_pct": round(moisture) if moisture is not None else None,
        "moisture_text": _int_text(moisture),
        "temperature_text": _int_text(temperature),
        "illuminance_text": _int_text(illuminance),
        "needs_water": needs_water,
        "low_battery": low_battery,
        "last_seen_text": relative_time(last_seen, now),
        "spark": moisture_spark(history, today),
        # Raw current metrics kept for any later use.
        "temperature": temperature,
        "illuminance": illuminance,
        "fertility": fertility,
        "fertility_text": _int_text(fertility),
    }
