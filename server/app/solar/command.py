"""Solar domain commands (write side): schema, PV-power integrator, MQTT listener.

The PowerStream only exposes instantaneous PV watts (no energy counter), so we
integrate the heartbeat power ourselves into daily kWh totals.
"""
import logging
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.module.integrator import DailyEnergyIntegrator
from app.module.slots import slot_start
from app.solar.infrastructure import repository
from app.solar.infrastructure.mqtt import EcoflowMqttListener

logger = logging.getLogger(__name__)

# Current 30-min slot accumulator (mean PV watts -> solar_samples), flushed at
# each slot boundary; a restart loses at most the in-progress slot.
_slot = {"start": None, "pv_sum": 0.0, "pv_n": 0}
last_solar_report = ""
last_pv_watts = None  # last PV power decoded from a heartbeat (diagnostics)
sample_count = 0  # heartbeats integrated since process start (diagnostics)


def init_schema():
    """Create the daily_production + solar_samples tables (idempotent)."""
    repository.init_schema()


def _reload_day(date: str) -> float:
    """Restart resilience: today's already-persisted Wh, if any."""
    tomorrow = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    existing = repository.get_cached_production(date, tomorrow)
    return existing[0]["pv_kwh"] * 1000 if existing else 0.0


# Reported PV power -> daily kWh. Only the MQTT listener thread feeds it.
_integrator = DailyEnergyIntegrator(repository.upsert_production, _reload_day)


def _flush_slot():
    """Persist the finished 30-min slot's mean PV watts."""
    if _slot["start"] is None or not _slot["pv_n"]:
        return
    repository.insert_solar_sample(_slot["start"], round(_slot["pv_sum"] / _slot["pv_n"]))


def _on_solar_power(pv_watts: float, now: datetime | None = None):
    """MQTT callback: integrate reported PV power into today's kWh total
    (`now` injectable for tests)."""
    global last_solar_report, last_pv_watts, sample_count
    now = now or datetime.now(PARIS_TZ)
    last_pv_watts = pv_watts
    sample_count += 1

    # Slot boundary: flush the finished 30-min slot (mean watts) to
    # solar_samples, then start accumulating the new one.
    slot = slot_start(now)
    if _slot["start"] != slot:
        _flush_slot()
        _slot["start"] = slot
        _slot["pv_sum"] = 0.0
        _slot["pv_n"] = 0
    _slot["pv_sum"] += pv_watts
    _slot["pv_n"] += 1

    _integrator.feed(pv_watts, now)
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
