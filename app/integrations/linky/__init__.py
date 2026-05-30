"""Linky electricity meter slice (core / mandatory).

Self-contained vertical slice: the REST transport lives in api/, the HC/HP domain
logic in client.py, and below the orchestration — env config, daily_consumption
schema, fetch/cache, the consumption panel + stats and the status fragment.
"""
import logging
import os
from datetime import datetime, timedelta

from app import db
from app.config import DAYS_FR, PARIS_TZ

from .api.transport import fetch_load_curve
from .client import LinkyApiError, LinkyAuthError, compute_daily_hc_hp, parse_hc_windows

logger = logging.getLogger(__name__)

TOKEN = os.environ.get("LINKY_TOKEN", "")
PRM = os.environ.get("LINKY_PRM", "")
PRICE_HP = float(os.environ.get("PRICE_HP", "0.2065"))
PRICE_HC = float(os.environ.get("PRICE_HC", "0.1579"))
PRICE_ABO_MONTHLY = float(os.environ.get("PRICE_ABO_MONTHLY", "15.65"))
HC_WINDOWS_RAW = os.environ.get("HC_WINDOWS", "23:32-5:32,15:02-17:02")
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
    # Migration: the talon (daily P5 power, W) was added later — add the column
    # to existing databases. Backfilled by fetch_and_cache on the next refresh.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_consumption)")]
    if "talon_w" not in cols:
        conn.execute("ALTER TABLE daily_consumption ADD COLUMN talon_w REAL")
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
        cached = db.get_cached_days(s, e)
        # Skip cached chunks, but force a one-time backfill of older weeks whose
        # rows predate the talon column (talon_w still NULL).
        if cached and week_offset > 0 and all(d.get("talon_w") is not None for d in cached):
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
