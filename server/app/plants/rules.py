"""Plants business rules — pure, no IO.

Builds the per-plant display card from its current reading and its recent daily
moisture history. The card's title line carries a red water-drop icon when the
device flags the plant for watering (its `water_warning`) and a red battery icon
when its battery is low; line 2 shows humidity, temperature and illuminance with
a 7-day moisture spark.
"""
from datetime import timedelta

# water_warning / battery_state enum values that mean "all good" (no alert).
_WATER_OK = ("none", "normal", "ok", "")
_BATTERY_LOW = ("low", "empty", "critical")


def moisture_spark(history: dict, today, days: int = 7) -> list:
    """The last `days` complete days' soil moisture (oldest→newest, ending
    yesterday); None for any day with no reading (keeps the spark's gap)."""
    return [history.get((today - timedelta(days=n)).strftime("%Y-%m-%d"))
            for n in range(days, 0, -1)]


def _int_text(value):
    """A metric rounded to a plain integer string, or an em dash when absent."""
    return str(round(value)) if value is not None else "—"


def build_plant_view(name: str, current: dict, history: dict, today) -> dict:
    """Assemble one plant's render dict. `current` is today's latest reading (or
    empty), `history` maps date→moisture over the recent window.

    needs_water comes from the device's `water_warning` enum (any value other
    than none/normal/ok); low_battery comes from `battery_state`."""
    moisture = current.get("moisture") if current else None
    fertility = current.get("fertility") if current else None
    illuminance = current.get("illuminance") if current else None
    temperature = current.get("temperature") if current else None

    warning = current.get("water_warning") if current else None
    needs_water = warning is not None and str(warning).strip().lower() not in _WATER_OK

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
        "spark": moisture_spark(history, today),
        # Raw current metrics kept for any later use.
        "temperature": temperature,
        "illuminance": illuminance,
        "fertility": fertility,
        "fertility_text": _int_text(fertility),
    }
