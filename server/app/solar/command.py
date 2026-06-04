"""Solar domain commands (write side): schema, PV-power integrator, MQTT listener.

The PowerStream only exposes instantaneous PV watts (no energy counter), so we
integrate the heartbeat power ourselves into daily kWh totals.
"""
import logging
import time
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.solar.infrastructure import repository
from app.solar.infrastructure.mqtt import EcoflowMqttListener

logger = logging.getLogger(__name__)

# Integration state for reported PV power -> daily kWh. Only the MQTT listener
# thread touches it, so no lock is needed.
_solar_state = {"date": None, "wh": 0.0, "last_ts": None, "last_persist": 0.0}
MAX_SAMPLE_GAP_H = 5 / 60  # cap a sample's time weight at 5 min to avoid overcounting silence
PERSIST_INTERVAL = 30  # seconds between SQLite writes
last_solar_report = ""
last_pv_watts = None  # last PV power decoded from a heartbeat (diagnostics)
sample_count = 0  # heartbeats integrated since process start (diagnostics)


def init_schema():
    """Create the daily_production table (idempotent)."""
    repository.init_schema()


def _on_solar_power(pv_watts: float):
    """MQTT callback: integrate reported PV power into today's kWh total."""
    global last_solar_report, last_pv_watts, sample_count
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    st = _solar_state
    last_pv_watts = pv_watts
    sample_count += 1

    if st["date"] != today:
        if st["date"] is not None:
            repository.upsert_production(st["date"], st["wh"])  # flush the finished day
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        existing = repository.get_cached_production(today, tomorrow)
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
        repository.upsert_production(today, st["wh"])
        st["last_persist"] = mono
    last_solar_report = now.isoformat()


def start():
    """Start the EcoFlow MQTT listener if enabled, else log and do nothing."""
    from app.solar import API_HOST, DEVICE_SN, EMAIL, ENABLED, PASSWORD

    if not ENABLED:
        logger.info("EcoFlow integration disabled (set ECOFLOW_EMAIL/PASSWORD/DEVICE_SN to enable)")
        return None
    listener = EcoflowMqttListener(EMAIL, PASSWORD, DEVICE_SN, API_HOST, _on_solar_power)
    listener.start()
    logger.info("EcoFlow MQTT listener started for SN %s", DEVICE_SN)
    return listener
