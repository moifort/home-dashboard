"""EcoFlow PowerStream solar slice.

Self-contained vertical slice: API client (client.py), MQTT transport (mqtt/),
protobuf schema (proto/), and below the orchestration that integrates reported
PV power into daily kWh and builds the solar panel. Remove the whole folder to
drop solar.

The PowerStream only exposes instantaneous PV watts (no energy counter), so we
integrate the heartbeat power ourselves into daily totals.
"""
import logging
import os
import time
from datetime import datetime, timedelta

from app import db
from app.config import DAYS_FR, PARIS_TZ

from .mqtt.listener import EcoflowMqttListener

logger = logging.getLogger(__name__)

EMAIL = os.environ.get("ECOFLOW_EMAIL", "")
PASSWORD = os.environ.get("ECOFLOW_PASSWORD", "")
DEVICE_SN = os.environ.get("ECOFLOW_DEVICE_SN", "")
API_HOST = os.environ.get("ECOFLOW_API_HOST", "api-e.ecoflow.com")
# Electricity price used to value the produced solar energy (own copy so the
# slice stays self-contained and removable).
PRICE_HP = float(os.environ.get("PRICE_HP", "0.2065"))

ENABLED = bool(EMAIL and PASSWORD and DEVICE_SN)

# Integration state for reported PV power -> daily kWh. Only the MQTT listener
# thread touches it, so no lock is needed.
_solar_state = {"date": None, "wh": 0.0, "last_ts": None, "last_persist": 0.0}
MAX_SAMPLE_GAP_H = 5 / 60  # cap a sample's time weight at 5 min to avoid overcounting silence
PERSIST_INTERVAL = 30  # seconds between SQLite writes
_last_solar_report = ""


def enabled() -> bool:
    return ENABLED


def init_schema():
    """Create the daily_production table (idempotent)."""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_production (
            date TEXT PRIMARY KEY,
            pv_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def _on_solar_power(pv_watts: float):
    """MQTT callback: integrate reported PV power into today's kWh total."""
    global _last_solar_report
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    st = _solar_state

    if st["date"] != today:
        if st["date"] is not None:
            db.upsert_production(st["date"], st["wh"])  # flush the finished day
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        existing = db.get_cached_production(today, tomorrow)
        st["date"] = today
        st["wh"] = existing[0]["pv_kwh"] * 1000 if existing else 0.0
        st["last_ts"] = None
        st["last_persist"] = 0.0

    if st["last_ts"] is not None:
        dt_h = (now - st["last_ts"]).total_seconds() / 3600
        if dt_h > 0:
            st["wh"] += pv_watts * min(dt_h, MAX_SAMPLE_GAP_H)
    st["last_ts"] = now

    mono = time.monotonic()
    if mono - st["last_persist"] >= PERSIST_INTERVAL:
        db.upsert_production(today, st["wh"])
        st["last_persist"] = mono
    _last_solar_report = now.isoformat()


def start():
    """Start the EcoFlow MQTT listener if enabled, else log and do nothing."""
    if not ENABLED:
        logger.info("EcoFlow integration disabled (set ECOFLOW_EMAIL/PASSWORD/DEVICE_SN to enable)")
        return None
    listener = EcoflowMqttListener(EMAIL, PASSWORD, DEVICE_SN, API_HOST, _on_solar_power)
    listener.start()
    logger.info("EcoFlow MQTT listener started for SN %s", DEVICE_SN)
    return listener


def attach(data: dict):
    """Add the solar production history: always the last 9 completed days.

    Days without accumulated data show as N/A. Today is excluded (only complete
    days, whose total we are sure was fully accumulated).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    full_start = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    prod_by_date = {p["date"]: p["pv_kwh"]
                    for p in db.get_cached_production(full_start, today.strftime("%Y-%m-%d"))}

    production_days = []
    recent = []
    for i in range(9, 0, -1):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        pv = prod_by_date.get(ds, 0.0)
        production_days.append({"day": DAYS_FR[d.weekday()], "date": ds, "pv_kwh": pv})
        recent.append({"pv_kwh": pv})

    previous = [{"pv_kwh": prod_by_date[ds]}
                for i in range(37, 9, -1)
                if (ds := (today - timedelta(days=i)).strftime("%Y-%m-%d")) in prod_by_date]

    data["production_days"] = production_days
    stats = _compute_production_stats(recent, previous)
    # Share of the base load (talon) the solar covers: average daily PV energy
    # over the talon's average daily energy (W → kWh/day). Core Linky runs before
    # the optional slices, so data["talon"] is already populated.
    talon_w = (data.get("talon") or {}).get("avg_w")
    if talon_w and talon_w > 0:
        talon_kwh = talon_w * 24 / 1000
        stats["talon_cover_pct"] = round(stats["avg_kwh"] / talon_kwh * 100)
    data["production_stats"] = stats


def _compute_production_stats(current: list[dict], previous: list[dict]) -> dict:
    na_threshold = 0.1

    def _avg(days):
        valid = [d for d in days if d["pv_kwh"] >= na_threshold]
        if not valid:
            return 0
        return sum(d["pv_kwh"] for d in valid) / len(valid)

    avg_kwh = _avg(current)
    avg_kwh_prev = _avg(previous)
    has_prev = avg_kwh_prev > 0

    pct = round((avg_kwh - avg_kwh_prev) / avg_kwh_prev * 100, 1) if has_prev else 0
    total = sum(d["pv_kwh"] for d in current)
    return {
        "avg_kwh": round(avg_kwh, 1),
        "avg_kwh_pct": pct,
        "total_kwh": round(total, 1),
        "savings_eur": round(total * PRICE_HP, 1),
    }


def status() -> dict:
    return {"ecoflow_enabled": ENABLED, "last_solar_report": _last_solar_report}
