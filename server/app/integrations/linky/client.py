"""Linky domain logic: HC/HP window parsing and daily aggregation.

The REST transport lives in api/; this module turns raw interval readings into
daily HC/HP kWh totals and holds the shared exceptions.
"""
import logging
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


class LinkyApiError(Exception):
    pass


class LinkyAuthError(LinkyApiError):
    pass


def parse_hc_windows(windows_str: str) -> list[tuple[int, int, int, int]]:
    """Parse HC windows string into list of (start_h, start_m, end_h, end_m) tuples.

    Example: "23:32-5:32,15:02-17:02" -> [(23, 32, 5, 32), (15, 2, 17, 2)]
    """
    windows = []
    for part in windows_str.split(","):
        start_str, end_str = part.strip().split("-")
        sh, sm = start_str.split(":")
        eh, em = end_str.split(":")
        windows.append((int(sh), int(sm), int(eh), int(em)))
    return windows


# Talon (baseline) = a low percentile of the day's 30-min power samples, in W.
# The strict minimum would catch the single step where everything (fridge
# included) happened to be off at once; P5 gives the true permanent floor.
TALON_PCT = 5


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (nearest-rank fallback for tiny series)."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (pct / 100) * (len(s) - 1)
    lo = int(rank)
    frac = rank - lo
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * frac


def compute_daily_hc_hp(
    api_response: list | dict,
    hc_windows: list[tuple[int, int, int, int]] | None = None,
) -> list[dict]:
    """Aggregate load curve data into daily HC/HP totals and the daily talon.

    Each 30-min interval: energy_Wh = power_W * 0.5. The talon is the P5 of the
    day's power samples (W) — the house's permanent baseline load.
    """
    if hc_windows is None:
        hc_windows = [(23, 32, 5, 32), (15, 2, 17, 2)]

    readings = _extract_readings(api_response)
    if not readings:
        return []

    daily: dict[str, dict] = defaultdict(
        lambda: {"hc_wh": 0.0, "hp_wh": 0.0, "watts": []}
    )

    for reading in readings:
        ts = reading["timestamp"]
        watts = reading["watts"]
        wh = watts * 0.5
        is_hc = _is_off_peak(ts.hour, ts.minute, hc_windows)
        date_key = ts.strftime("%Y-%m-%d")

        if is_hc:
            daily[date_key]["hc_wh"] += wh
        else:
            daily[date_key]["hp_wh"] += wh
        daily[date_key]["watts"].append(watts)

    return sorted(
        [
            {
                "date": date,
                "hc_kwh": round(vals["hc_wh"] / 1000, 2),
                "hp_kwh": round(vals["hp_wh"] / 1000, 2),
                "talon_w": round(_percentile(vals["watts"], TALON_PCT)),
            }
            for date, vals in daily.items()
        ],
        key=lambda x: x["date"],
    )


def _is_off_peak(hour: int, minute: int, hc_windows: list[tuple[int, int, int, int]]) -> bool:
    t = hour * 60 + minute
    for sh, sm, eh, em in hc_windows:
        start = sh * 60 + sm
        end = eh * 60 + em
        if start > end:
            if t >= start or t < end:
                return True
        else:
            if start <= t < end:
                return True
    return False


def _extract_readings(api_response) -> list[dict]:
    """Normalize various Conso API response formats into a flat list.

    Known formats:
    - {"interval_reading": [{"date": "...", "value": "..."}, ...]}
    - [{"date": "...", "value": "..."}, ...]
    - {"data": [{"date": "...", "value": "..."}, ...]}
    """
    raw_list = []
    if isinstance(api_response, list):
        raw_list = api_response
    elif isinstance(api_response, dict):
        if "interval_reading" in api_response:
            raw_list = api_response["interval_reading"]
        elif "data" in api_response:
            raw_list = api_response["data"]
        else:
            for key in api_response:
                if isinstance(api_response[key], list):
                    raw_list = api_response[key]
                    break

    readings = []
    for entry in raw_list:
        ts = _parse_timestamp(entry)
        watts = _parse_value(entry)
        if ts is not None and watts is not None:
            readings.append({"timestamp": ts, "watts": watts})

    return readings


def _parse_timestamp(entry: dict) -> datetime | None:
    for key in ("date", "timestamp", "dateTime", "start"):
        if key in entry:
            val = entry[key]
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
                try:
                    return datetime.strptime(val, fmt)
                except (ValueError, TypeError):
                    continue
    return None


def _parse_value(entry: dict) -> float | None:
    for key in ("value", "watts", "w", "power"):
        if key in entry:
            try:
                return float(entry[key])
            except (ValueError, TypeError):
                continue
    return None
