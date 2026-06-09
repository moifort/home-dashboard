"""Electricity domain commands (write side): schema init + the ZLinky integrator.

The Linky teleinfo arrives over MQTT (zigbee2mqtt + Lixee ZLinky_TIC). The
meter gives exact cumulative HCHC/HCHP indexes, so the per-day kWh is the sum
of index deltas since midnight — no W×dt integration. Every 30 minutes the
running indexes + the slot's mean PAPP land in tic_samples (the fine-grained
history); every 30 seconds the day's totals + the night-percentile talon land
in daily_consumption.
"""
import logging
import time
from datetime import datetime, timedelta

from app.system.config import MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME, PARIS_TZ
from app.electricity.infrastructure import repository
from app.electricity.infrastructure.linky_client import (
    _is_off_peak,
    compute_talon_w,
)
from app.electricity.infrastructure.zlinky_mqtt import ZLinkyMqttListener

logger = logging.getLogger(__name__)

PERSIST_INTERVAL = 30   # seconds between daily_consumption writes (mirrors power)
SLOT_MIN = 30           # tic_samples granularity — one row per 30-min slot
MAX_INDEX_STEP_KWH = 15  # a single TIC step above this is implausible → re-baseline
PTEC_STALE_S = 900      # beyond this silence, fall back to the HC_WINDOWS clock

# Runtime state surfaced by query.status().
last_message_time = ""
last_error = ""
last_hchc = None
last_hphp = None

# Integration state — only the single linky-mqtt thread writes it, no lock.
# base_* = the last seen index (each frame's delta is added then re-baselined).
_state = {"date": None, "hc_kwh": 0.0, "hp_kwh": 0.0,
          "base_hchc": None, "base_hphp": None, "last_persist": 0.0}
# Current 30-min slot accumulator for tic_samples (mean PAPP of the slot).
_slot = {"start": None, "papp_sum": 0.0, "papp_n": 0}
# Last PTEC period seen ("HC"/"HP") and when (monotonic) — read by the power
# sub-domain threads; a tuple assignment is atomic under the GIL.
_period = (None, 0.0)
# Recent COMPLETED windows per period as (start, end) wall-clock, recorded at the
# transition that ends each. The day has two HC and two HP windows, so we keep the
# last MAX_TARIFF_WINDOWS of each (oldest first → chronological). _open_window =
# (period, start) of the in-progress window; _tariff_period = the period in effect
# now. In-memory only — a restart blanks them until real transitions complete
# windows again, so the panel fills up over the day (the first frame after startup
# only baselines _period; the first transition just opens a window with no prior to
# close).
MAX_TARIFF_WINDOWS = 2
_tariff_windows = {"HC": [], "HP": []}
_open_window = None
_tariff_period = None


def init_schema():
    """Create the daily_consumption + tic_samples tables (idempotent)."""
    repository.init_schema()


def _slot_start(now: datetime) -> str:
    """The ISO start of `now`'s 30-min slot (local time)."""
    return now.replace(minute=now.minute - now.minute % SLOT_MIN,
                       second=0, microsecond=0).isoformat()


def _flush_slot():
    """Persist the finished 30-min slot: index snapshot + mean PAPP (or NULL)."""
    if _slot["start"] is None or last_hchc is None:
        return
    papp = _slot["papp_sum"] / _slot["papp_n"] if _slot["papp_n"] else None
    repository.insert_sample(_slot["start"], last_hchc, last_hphp,
                             round(papp) if papp is not None else None)


def _persist_day(date: str):
    """Upsert the day's totals; talon = P20 of its night slots in tic_samples."""
    talon = compute_talon_w(repository.get_night_papp(date))
    repository.upsert_day(date, round(_state["hc_kwh"], 2),
                          round(_state["hp_kwh"], 2), talon)


def _reload_today(today: str):
    """Restart resilience: resume from today's partial row if one exists."""
    tomorrow = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = repository.get_cached_days(today, tomorrow)
    _state["hc_kwh"] = rows[0]["hc_kwh"] if rows else 0.0
    _state["hp_kwh"] = rows[0]["hp_kwh"] if rows else 0.0


def _on_tic(reading: dict, now: datetime | None = None):
    """Integrate one TIC frame (`now` injectable for tests)."""
    global last_message_time, last_error, last_hchc, last_hphp, _period, _tariff_period, _open_window
    now = now or datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    hchc, hphp, papp = reading["hchc_kwh"], reading["hchp_kwh"], reading["papp_va"]

    # Slot boundary first: flush the finished 30-min slot (still holds the
    # previous frames' indexes/PAPP), so a 23h30 slot lands in tic_samples
    # before the day flush below reads the night samples for the final talon.
    slot = _slot_start(now)
    if _slot["start"] != slot:
        _flush_slot()
        _slot["start"] = slot
        _slot["papp_sum"] = 0.0
        _slot["papp_n"] = 0

    # Day rollover: persist the finished day (final talon includes its full
    # 23h–midnight), then resume today from any partial row (restart resilience).
    if _state["date"] != today:
        if _state["date"] is not None:
            _persist_day(_state["date"])
        _state["date"] = today
        _state["base_hchc"] = None  # the frame straddling midnight yields no delta
        _state["base_hphp"] = None
        _state["last_persist"] = 0.0
        _reload_today(today)

    # Index deltas → today's kWh. First frame just baselines. A negative delta
    # (meter/index reset) or an implausible jump is dropped and re-baselined.
    if _state["base_hchc"] is not None:
        d_hc = hchc - _state["base_hchc"]
        d_hp = hphp - _state["base_hphp"]
        if d_hc < 0 or d_hp < 0 or d_hc > MAX_INDEX_STEP_KWH or d_hp > MAX_INDEX_STEP_KWH:
            logger.warning("Implausible index delta (hc=%.3f hp=%.3f kWh), re-baselining", d_hc, d_hp)
        else:
            _state["hc_kwh"] += d_hc
            _state["hp_kwh"] += d_hp
    _state["base_hchc"] = hchc
    _state["base_hphp"] = hphp

    if papp is not None:
        _slot["papp_sum"] += papp
        _slot["papp_n"] += 1

    if reading.get("period") is not None:
        prev = _period[0]
        new = reading["period"]
        if prev is not None and new != prev:
            if _open_window is not None and _open_window[0] == prev:
                _tariff_windows[prev].append((_open_window[1], now))  # close the ended window
                _tariff_windows[prev] = _tariff_windows[prev][-MAX_TARIFF_WINDOWS:]
            _open_window = (new, now)                            # open the new one
            _tariff_period = new
        _period = (new, time.monotonic())

    last_hchc, last_hphp = hchc, hphp
    last_message_time = now.isoformat()
    last_error = ""

    mono = time.monotonic()
    if mono - _state["last_persist"] >= PERSIST_INTERVAL:
        _persist_day(today)
        _state["last_persist"] = mono


def is_off_peak(now: datetime | None = None) -> bool:
    """Is the meter currently in an off-peak (HC) period?

    Trusts the live PTEC from the ZLinky when fresh; falls back to the
    HC_WINDOWS clock when the TIC stream has gone quiet (>15 min).
    """
    from app.electricity import HC_WINDOWS

    now = now or datetime.now(PARIS_TZ)
    period, ts = _period
    if period is not None and time.monotonic() - ts < PTEC_STALE_S:
        return period == "HC"
    return _is_off_peak(now.hour, now.minute, HC_WINDOWS)


def current_tariff() -> dict | None:
    """The recent completed HC and HP windows (up to MAX_TARIFF_WINDOWS each) as
    lists of (start, end) wall-clock, learned live from the meter's PTEC
    transitions: {"period", "hc", "hp"}. None until at least one window has
    completed since startup; a period's list stays empty until one of its own
    windows has completed (each period is independent). No freshness check — an
    observed window stays listed until trimmed out by newer ones of that period."""
    if not _tariff_windows["HC"] and not _tariff_windows["HP"]:
        return None
    return {"period": _tariff_period,
            "hc": _tariff_windows["HC"], "hp": _tariff_windows["HP"]}


def start():
    """Start the ZLinky MQTT listener, else log and do nothing."""
    from app.electricity import ENABLED, TOPIC

    if not ENABLED:
        logger.info("Linky MQTT disabled (set MQTT_HOST + LINKY_MQTT_TOPIC to enable)")
        return None
    listener = ZLinkyMqttListener(MQTT_HOST, MQTT_PORT, TOPIC,
                                  MQTT_USERNAME, MQTT_PASSWORD, _on_tic)
    listener.start()
    logger.info("Linky MQTT listener started on %s:%d (%s)", MQTT_HOST, MQTT_PORT, TOPIC)
    return listener


def load_days() -> list[dict]:
    """Read-only: the trailing 35-day cache for the render path."""
    now = datetime.now(PARIS_TZ)
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=35)).strftime("%Y-%m-%d")
    return repository.get_cached_days(start_date, end)
