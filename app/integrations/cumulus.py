"""Zigbee2MQTT client — reads the cumulus (Legrand 412171 contactor) power.

The contactor exposes only instantaneous power (W), no energy counter, so the
caller integrates the reported power into daily kWh. Z2M publishes power on
change; we also re-request it periodically (a `get`) so samples keep flowing
during long, steady heating periods.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt

from app import db
from app.config import PARIS_TZ

logger = logging.getLogger(__name__)

MQTT_HOST = os.environ.get("CUMULUS_MQTT_HOST", "")
MQTT_PORT = int(os.environ.get("CUMULUS_MQTT_PORT", "1883"))
TOPIC = os.environ.get("CUMULUS_TOPIC", "zigbee2mqtt/cumulus")
MQTT_USERNAME = os.environ.get("CUMULUS_MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("CUMULUS_MQTT_PASSWORD", "")

# Re-request power on this cadence (seconds) so integration keeps getting
# samples even when the load is steady and Z2M would otherwise stay quiet.
GET_INTERVAL = 60


def _parse_power(payload: bytes) -> float | None:
    """Extract the numeric `power` (W) from a Z2M JSON device message."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    power = data.get("power")
    if isinstance(power, (int, float)):
        return float(power)
    return None


class CumulusMqttListener:
    """Background thread reading `power` from a Zigbee2MQTT device topic.

    Calls on_power(watts) on each reported value. Reconnects automatically.
    """

    def __init__(self, host, port, topic, username, password, on_power):
        self._host = host
        self._port = port
        self._topic = topic
        self._username = username
        self._password = password
        self._on_power = on_power
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="cumulus-mqtt", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as exc:
                logger.warning("Cumulus MQTT session ended (%s), retrying in 60s", exc)
                self._stop.wait(60)

    def _connect_and_listen(self):
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if self._username:
            client.username_pw_set(self._username, self._password)
        get_topic = f"{self._topic}/get"

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("Cumulus MQTT connect failed: %s", reason_code)
                return
            c.subscribe(self._topic, qos=0)
            c.publish(get_topic, json.dumps({"power": ""}), qos=0)
            logger.info("Cumulus MQTT connected, subscribed to %s", self._topic)

        def on_message(c, userdata, msg):
            watts = _parse_power(msg.payload)
            if watts is not None:
                try:
                    self._on_power(watts)
                except Exception:
                    logger.exception("on_power callback failed")

        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        client.connect(self._host, self._port, keepalive=30)

        last_poll = time.monotonic()
        while not self._stop.is_set():
            client.loop(timeout=1.0)
            if time.monotonic() - last_poll >= GET_INTERVAL:
                client.publish(get_topic, json.dumps({"power": ""}), qos=0)
                last_poll = time.monotonic()
        client.disconnect()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


# --- Slice orchestration: enable, integrate power -> daily kWh, panel, status ---

ENABLED = bool(MQTT_HOST)
NA_THRESHOLD_KWH = 0.05

# Integration state for the contactor power -> daily kWh. Only the MQTT listener
# thread touches it, so no lock is needed. The contactor has no energy counter,
# so we integrate its reported instantaneous power ourselves.
_cumulus_state = {"date": None, "wh": 0.0, "last_ts": None, "last_persist": 0.0}
MAX_SAMPLE_GAP_H = 5 / 60  # cap a sample's time weight at 5 min to avoid overcounting silence
PERSIST_INTERVAL = 30  # seconds between SQLite writes
_last_cumulus_report = ""


def enabled() -> bool:
    return ENABLED


def init_schema():
    """Create the daily_cumulus table (idempotent)."""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_cumulus (
            date TEXT PRIMARY KEY,
            cons_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def _on_cumulus_power(watts: float):
    """MQTT callback: integrate reported cumulus power into today's kWh total."""
    global _last_cumulus_report
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    st = _cumulus_state

    if st["date"] != today:
        if st["date"] is not None:
            db.upsert_cumulus(st["date"], st["wh"])  # flush the finished day
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        existing = db.get_cached_cumulus(today, tomorrow)
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
        db.upsert_cumulus(today, st["wh"])
        st["last_persist"] = mono
    _last_cumulus_report = now.isoformat()


def start():
    """Start the Cumulus MQTT listener if enabled, else log and do nothing."""
    if not ENABLED:
        logger.info("Cumulus integration disabled (set CUMULUS_MQTT_HOST to enable)")
        return None
    listener = CumulusMqttListener(
        MQTT_HOST, MQTT_PORT, TOPIC, MQTT_USERNAME, MQTT_PASSWORD, _on_cumulus_power,
    )
    listener.start()
    logger.info("Cumulus MQTT listener started on %s:%d (%s)", MQTT_HOST, MQTT_PORT, TOPIC)
    return listener


def attach(data: dict):
    """Attach the cumulus banner fields: yesterday's kWh and the recent daily average.

    Integrated from the contactor's reported power (no energy counter); history
    starts at first connection (no backfill).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    nine_ago = (today - timedelta(days=9)).strftime("%Y-%m-%d")

    yesterday_rows = db.get_cached_cumulus(yesterday_str, today_str)
    yesterday_kwh = yesterday_rows[0]["cons_kwh"] if yesterday_rows else 0.0

    past = [r["cons_kwh"] for r in db.get_cached_cumulus(nine_ago, today_str)
            if r["cons_kwh"] >= NA_THRESHOLD_KWH]
    avg = sum(past) / len(past) if past else 0.0

    # Trend: last 9 days vs the 28 days before them (mirrors the solar stats).
    prev_start = (today - timedelta(days=37)).strftime("%Y-%m-%d")
    prev = [r["cons_kwh"] for r in db.get_cached_cumulus(prev_start, nine_ago)
            if r["cons_kwh"] >= NA_THRESHOLD_KWH]
    avg_prev = sum(prev) / len(prev) if prev else 0.0
    trend_pct = round((avg - avg_prev) / avg_prev * 100, 1) if avg_prev > 0 else 0

    data["cumulus"] = {
        "yesterday_text": f"{yesterday_kwh:.1f}",
        "avg_text": f"{avg:.1f}" if past else "N/A",
        "trend_pct": trend_pct,
    }


def status() -> dict:
    return {"cumulus_enabled": ENABLED, "last_cumulus": _last_cumulus_report}
