"""Washing-machine (lave-linge) consumption slice.

Self-contained vertical slice: the MQTT transport lives in mqtt/, and below the
orchestration that integrates the smart-plug's reported power into daily kWh and
builds the bottom-table row. Remove the whole folder to drop the washer reading.

Like the Cumulus contactor, the plug exposes only instantaneous power (W), no
energy counter, so we integrate its reported power ourselves into daily totals.
"""
import logging
import os
import time
from datetime import datetime, timedelta

from app import db
from app.config import MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME, PARIS_TZ

from .mqtt.listener import WasherMqttListener

logger = logging.getLogger(__name__)

# Broker host/port/credentials are shared (app.config); this slice only owns its topic.
TOPIC = os.environ.get("WASHER_TOPIC", "")


# --- Slice orchestration: enable, integrate power -> daily kWh, panel, status ---

ENABLED = bool(MQTT_HOST) and bool(TOPIC)
NA_THRESHOLD_KWH = 0.05

# Integration state for the plug power -> daily kWh. Only the MQTT listener thread
# touches it, so no lock is needed. The plug has no energy counter, so we integrate
# its reported instantaneous power ourselves.
_washer_state = {"date": None, "wh": 0.0, "last_ts": None, "last_persist": 0.0}
MAX_SAMPLE_GAP_H = 5 / 60  # cap a sample's time weight at 5 min to avoid overcounting silence
PERSIST_INTERVAL = 30  # seconds between SQLite writes
_last_washer_report = ""


def enabled() -> bool:
    return ENABLED


def init_schema():
    """Create the daily_washer table (idempotent)."""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_washer (
            date TEXT PRIMARY KEY,
            cons_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def _on_washer_power(watts: float):
    """MQTT callback: integrate reported washer power into today's kWh total."""
    global _last_washer_report
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    st = _washer_state

    if st["date"] != today:
        if st["date"] is not None:
            db.upsert_washer(st["date"], st["wh"])  # flush the finished day
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        existing = db.get_cached_washer(today, tomorrow)
        st["date"] = today
        st["wh"] = existing[0]["cons_kwh"] * 1000 if existing else 0.0
        st["last_ts"] = None
        st["last_persist"] = 0.0

    if st["last_ts"] is not None:
        dt_h = (now - st["last_ts"]).total_seconds() / 3600
        if dt_h > 0:
            st["wh"] += watts * min(dt_h, MAX_SAMPLE_GAP_H)
    st["last_ts"] = now

    mono = time.monotonic()
    if mono - st["last_persist"] >= PERSIST_INTERVAL:
        db.upsert_washer(today, st["wh"])
        st["last_persist"] = mono
    _last_washer_report = now.isoformat()


def start():
    """Start the washer MQTT listener if enabled, else log and do nothing."""
    if not ENABLED:
        logger.info("Washer integration disabled (set MQTT_HOST + WASHER_TOPIC to enable)")
        return None
    listener = WasherMqttListener(
        MQTT_HOST, MQTT_PORT, TOPIC, MQTT_USERNAME, MQTT_PASSWORD, _on_washer_power,
    )
    listener.start()
    logger.info("Washer MQTT listener started on %s:%d (%s)", MQTT_HOST, MQTT_PORT, TOPIC)
    return listener


def attach(data: dict):
    """Attach the washer banner fields: yesterday's kWh and the recent daily average.

    Integrated from the plug's reported power (no energy counter); history starts
    at first connection (no backfill).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    nine_ago = (today - timedelta(days=9)).strftime("%Y-%m-%d")

    yesterday_rows = db.get_cached_washer(yesterday_str, today_str)
    yesterday_kwh = yesterday_rows[0]["cons_kwh"] if yesterday_rows else 0.0

    past = [r["cons_kwh"] for r in db.get_cached_washer(nine_ago, today_str)
            if r["cons_kwh"] >= NA_THRESHOLD_KWH]
    avg = sum(past) / len(past) if past else 0.0

    # Trend: last 9 days vs the 28 days before them (mirrors the cumulus stats).
    prev_start = (today - timedelta(days=37)).strftime("%Y-%m-%d")
    prev = [r["cons_kwh"] for r in db.get_cached_washer(prev_start, nine_ago)
            if r["cons_kwh"] >= NA_THRESHOLD_KWH]
    avg_prev = sum(prev) / len(prev) if prev else 0.0
    trend_pct = round((avg - avg_prev) / avg_prev * 100, 1) if avg_prev > 0 else 0

    data["washer"] = {
        "yesterday_text": f"{yesterday_kwh:.1f}",
        "avg_text": f"{avg:.1f}" if past else "N/A",
        "trend_pct": trend_pct,
    }


def status() -> dict:
    return {"washer_enabled": ENABLED, "last_washer": _last_washer_report}
