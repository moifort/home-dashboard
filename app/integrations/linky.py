"""Linky electricity meter slice: Conso API client, daily HC/HP storage and stats.

Core (non-optional) integration. Owns its env config, its `daily_consumption`
table accessors, the fetch/cache orchestration and the consumption panel + stats.
"""
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta

import requests

from app import db
from app.config import DAYS_FR, PARIS_TZ

logger = logging.getLogger(__name__)

TOKEN = os.environ.get("LINKY_TOKEN", "")
PRM = os.environ.get("LINKY_PRM", "")
PRICE_HP = float(os.environ.get("PRICE_HP", "0.2065"))
PRICE_HC = float(os.environ.get("PRICE_HC", "0.1579"))
PRICE_ABO_MONTHLY = float(os.environ.get("PRICE_ABO_MONTHLY", "15.65"))
HC_WINDOWS_RAW = os.environ.get("HC_WINDOWS", "23:32-5:32,15:02-17:02")

API_BASE = "https://conso.boris.sh/api"
USER_AGENT = "linky-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"
MAX_RETRIES = 3


class LinkyApiError(Exception):
    pass


class LinkyAuthError(LinkyApiError):
    pass


def fetch_load_curve(
    token: str, prm: str, start: str, end: str
) -> list[dict]:
    """Fetch consumption load curve (30-min intervals) from Conso API.

    Args:
        token: JWT bearer token
        prm: 14-digit meter identifier
        start: Start date YYYY-MM-DD (inclusive)
        end: End date YYYY-MM-DD (exclusive)

    Returns:
        Raw API response data (list of interval readings).
    """
    url = f"{API_BASE}/consumption_load_curve"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
    params = {"prm": prm, "start": start, "end": end}

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code in (401, 403):
                raise LinkyAuthError(f"Authentication failed: {resp.status_code}")
            if resp.status_code == 400:
                raise LinkyApiError(f"Bad request: {resp.text[:200]}")
            if resp.status_code == 429:
                logger.warning("Rate limited, backing off 60s")
                time.sleep(60)
                continue
            resp.raise_for_status()
            return resp.json()
        except LinkyAuthError:
            raise
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                delay = 2 ** (attempt + 1)
                logger.warning("API request failed (%s), retrying in %ds", e, delay)
                time.sleep(delay)
            else:
                raise LinkyApiError(f"API request failed after {MAX_RETRIES} attempts: {e}") from e

    raise LinkyApiError("Max retries exceeded")


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


def compute_daily_hc_hp(
    api_response: list | dict,
    hc_windows: list[tuple[int, int, int, int]] | None = None,
) -> list[dict]:
    """Aggregate load curve data into daily HC/HP totals.

    Each 30-min interval: energy_Wh = power_W * 0.5
    """
    if hc_windows is None:
        hc_windows = [(23, 32, 5, 32), (15, 2, 17, 2)]

    readings = _extract_readings(api_response)
    if not readings:
        return []

    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"hc_wh": 0.0, "hp_wh": 0.0})

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

    return sorted(
        [
            {
                "date": date,
                "hc_kwh": round(vals["hc_wh"] / 1000, 2),
                "hp_kwh": round(vals["hp_wh"] / 1000, 2),
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


# --- Slice orchestration: config, storage schema, fetch, panel, status ---

HC_WINDOWS = parse_hc_windows(HC_WINDOWS_RAW)

_last_fetch_time = ""
_last_error = ""


def init_schema():
    """Create the daily_consumption table (idempotent)."""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_consumption (
            date TEXT PRIMARY KEY,
            hc_kwh REAL NOT NULL,
            hp_kwh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def fetch_and_cache() -> list[dict]:
    """Fetch missing/stale daily HC/HP from the Conso API and return 35 days."""
    global _last_fetch_time, _last_error
    now = datetime.now(PARIS_TZ)
    end_date = now.strftime("%Y-%m-%d")
    full_start = (now - timedelta(days=35)).strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    if not db.needs_refresh(week_start, end_date):
        logger.info("Cache is fresh, skipping API call")
        return db.get_cached_days(full_start, end_date)

    for week_offset in range(5):
        chunk_end = now - timedelta(days=week_offset * 7)
        chunk_start = chunk_end - timedelta(days=7)
        s = chunk_start.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")
        if db.get_cached_days(s, e) and week_offset > 0:
            continue
        logger.info("Fetching load curve: %s to %s", s, e)
        try:
            raw = fetch_load_curve(TOKEN, PRM, s, e)
            days = compute_daily_hc_hp(raw, HC_WINDOWS)
            if days:
                db.upsert_days(days)
        except LinkyAuthError as exc:
            logger.critical("Auth error: %s", exc)
            _last_error = str(exc)
            break
        except LinkyApiError as exc:
            logger.warning("API error for %s-%s: %s", s, e, exc)
            _last_error = str(exc)
            continue

    _last_fetch_time = now.isoformat()
    if not _last_error:
        _last_error = ""
    return db.get_cached_days(full_start, end_date)


def build_core(days: list[dict]) -> dict:
    """Build the base render dict (the consumption days + stats)."""
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    complete_days = [d for d in days if d["date"] < today]

    current_week = complete_days[-9:]
    prev_weeks = complete_days[-37:-9]

    result = []
    for d in current_week:
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        result.append({
            "day": DAYS_FR[dt.weekday()],
            "date": d["date"],
            "hc_kwh": d["hc_kwh"],
            "hp_kwh": d["hp_kwh"],
        })

    return {"days": result, "stats": _compute_stats(current_week, prev_weeks)}


def _compute_stats(current: list[dict], previous: list[dict]) -> dict:
    daily_abo = PRICE_ABO_MONTHLY / 30.44
    na_threshold = 1.0

    def _filter_valid(days):
        return [d for d in days if d["hc_kwh"] + d["hp_kwh"] >= na_threshold]

    def _avg_and_ratios(days):
        if not days:
            return 0, 0, 0
        total_hc = sum(d["hc_kwh"] for d in days)
        total_hp = sum(d["hp_kwh"] for d in days)
        total = total_hc + total_hp
        n = len(days)
        avg_kwh = total / n
        hc_ratio = (total_hc / total * 100) if total > 0 else 0
        avg_price = ((total_hp * PRICE_HP + total_hc * PRICE_HC) / n) + daily_abo
        return avg_kwh, hc_ratio, avg_price

    avg_kwh, hc_ratio, avg_price = _avg_and_ratios(_filter_valid(current))
    has_prev = len(previous) > 0
    avg_kwh_prev, hc_ratio_prev, avg_price_prev = _avg_and_ratios(_filter_valid(previous))

    def _pct(cur, prev):
        if not has_prev or prev == 0:
            return 0
        return round((cur - prev) / prev * 100, 1)

    return {
        "avg_kwh": round(avg_kwh, 1),
        "avg_kwh_pct": _pct(avg_kwh, avg_kwh_prev),
        "hc_ratio": round(hc_ratio, 1),
        "hc_ratio_pct": round(hc_ratio - hc_ratio_prev, 1) if has_prev else 0,
        "avg_price": round(avg_price, 2),
        "avg_price_pct": _pct(avg_price, avg_price_prev),
    }


def status() -> dict:
    """Status fragment for the /status endpoint."""
    return {
        "prm": PRM,
        "hc_windows": HC_WINDOWS_RAW,
        "last_fetch": _last_fetch_time,
        "last_error": _last_error,
    }
