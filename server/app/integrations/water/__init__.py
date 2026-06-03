"""Water meter consumption slice.

Self-contained vertical slice: the MQTT transport lives in mqtt/, and below the
orchestration that turns the meter's cumulative index (m³) into a daily-litres
chart plus a monthly total and cost. Remove the whole folder to drop the water
reading.

The wM-Bus meter reports a *cumulative* index (m³), not a power, so — unlike the
Cumulus contactor — daily consumption is a *difference of index* between days
(like the Linky index), never a time integration.
"""
import logging
import os
from datetime import datetime, timedelta

from app import db
from app.config import DAYS_FR, MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME, PARIS_TZ

from .mqtt.listener import WaterMqttListener

logger = logging.getLogger(__name__)

# Broker host/port/credentials are shared (app.config); this slice only owns its topic.
TOPIC = os.environ.get("WATER_TOPIC", "")
PRICE_M3 = float(os.environ.get("WATER_PRICE_M3", "0") or 0)

ENABLED = bool(MQTT_HOST) and bool(TOPIC)
CHART_DAYS = 9  # daily bars shown in the dedicated water chart

_last_water_report = ""


def enabled() -> bool:
    return ENABLED


def init_schema():
    """Create the daily_water table (idempotent). Stores the latest index seen
    each day; daily consumption is derived as a diff at read time."""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_water (
            date TEXT PRIMARY KEY,
            index_m3 REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def _on_water_index(m3: float):
    """MQTT callback: store today's latest cumulative index (m³). INSERT OR
    REPLACE keeps the last value of the day, which is all the diff needs."""
    global _last_water_report
    now = datetime.now(PARIS_TZ)
    db.upsert_water(now.strftime("%Y-%m-%d"), m3)
    _last_water_report = now.isoformat()


def start():
    """Start the water MQTT listener if enabled, else log and do nothing."""
    if not ENABLED:
        logger.info("Water integration disabled (set MQTT_HOST + WATER_TOPIC to enable)")
        return None
    listener = WaterMqttListener(
        MQTT_HOST, MQTT_PORT, TOPIC, MQTT_USERNAME, MQTT_PASSWORD, _on_water_index,
    )
    listener.start()
    logger.info("Water MQTT listener started on %s:%d (%s)", MQTT_HOST, MQTT_PORT, TOPIC)
    return listener


def _index_asof(rows: list[dict], day: str) -> float | None:
    """Latest cumulative index recorded on or before `day` (carry-forward), or
    None when no reading exists that early yet."""
    found = None
    for r in rows:
        if r["date"] <= day:
            found = r["index_m3"]
        else:
            break
    return found


def attach(data: dict):
    """Attach the water chart + stats from the meter's index history.

    Daily litres are index diffs between consecutive days (carry-forward across
    days with no frame, so the jump lands on the next day that reports). History
    starts at first connection (no backfill).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    first_of_month = today.replace(day=1)

    # Fetch enough history for the chart (CHART_DAYS), its trend baseline (the
    # CHART_DAYS before) and the month-to-date total, whichever reaches furthest
    # back. +1 day for the diff against the day before the oldest shown.
    start = min(today - timedelta(days=2 * CHART_DAYS + 1), first_of_month - timedelta(days=2))
    end_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = db.get_cached_water(start.strftime("%Y-%m-%d"), end_str)

    # No reading recorded yet today → today's bar is N/A, not a carry-forward 0
    # (otherwise the diff against yesterday's carried-forward index reads as zero).
    today_str = today.strftime("%Y-%m-%d")
    has_today_reading = any(r["date"] == today_str for r in rows)

    # Per-day litres for the last 2*CHART_DAYS days (last CHART_DAYS shown; the
    # CHART_DAYS before feed the trend baseline).
    daily = []  # list of (date, litres|None) oldest->newest
    for i in range(2 * CHART_DAYS - 1, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        prev_str = (d - timedelta(days=1)).strftime("%Y-%m-%d")
        idx_d = _index_asof(rows, d_str)
        idx_prev = _index_asof(rows, prev_str)
        if idx_d is None or idx_prev is None or (i == 0 and not has_today_reading):
            litres = None
        else:
            litres = max(0.0, (idx_d - idx_prev) * 1000)
        daily.append((d, litres))

    shown = daily[-CHART_DAYS:]
    data["water_days"] = [
        {"day": DAYS_FR[d.weekday()], "liters": litres, "today": d == today}
        for d, litres in shown
    ]

    def avg(seq):
        vals = [v for v in seq if v is not None]
        return sum(vals) / len(vals) if vals else None

    avg_recent = avg(v for _, v in daily[-CHART_DAYS:])
    avg_prev = avg(v for _, v in daily[-2 * CHART_DAYS:-CHART_DAYS])
    trend_pct = round((avg_recent - avg_prev) / avg_prev * 100, 1) if avg_recent and avg_prev else 0

    # Month-to-date volume: index now minus the index at the end of last month.
    idx_now = _index_asof(rows, today.strftime("%Y-%m-%d"))
    idx_month_start = _index_asof(rows, (first_of_month - timedelta(days=1)).strftime("%Y-%m-%d"))
    if idx_now is not None and idx_month_start is not None:
        month_total_m3 = max(0.0, idx_now - idx_month_start)
    else:
        month_total_m3 = None

    data["water_stats"] = {
        "avg_text": f"{avg_recent:.0f}" if avg_recent is not None else "N/A",
        "avg_pct": trend_pct,
        "month_total_text": f"{month_total_m3:.2f}" if month_total_m3 is not None else "N/A",
        "cost_text": f"{month_total_m3 * PRICE_M3:.2f}"
        if (month_total_m3 is not None and PRICE_M3 > 0) else None,
    }


def status() -> dict:
    return {"water_enabled": ENABLED, "last_water": _last_water_report}
