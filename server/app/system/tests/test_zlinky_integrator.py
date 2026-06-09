"""Unit tests for the ZLinky TIC path: payload parsing and the index integrator.

Pure logic, no MQTT: the parser is fed raw payload bytes, the integrator is fed
parsed readings with an injected `now` against a temp SQLite database.
"""
import json
from datetime import datetime

import pytest

from app.module import db
from app.system.config import PARIS_TZ
from app.electricity import command
from app.electricity.infrastructure import repository
from app.electricity.infrastructure.zlinky_mqtt import _parse_tic, _to_kwh


# --- Parser ---

def test_parse_real_z2m_payload():
    # Zigbee2MQTT translates the TIC labels to snake_case property names —
    # captured from a live ZLinky_TIC (mode historique, HC/HP contract).
    raw = json.dumps({
        "active_register_tier_delivered": "HP..",
        "apparent_power": 319,
        "available_power": 30,
        "current_price": "HP..",
        "current_tarif": "HC..",  # OPTARIF (contract option) — NOT the live period
        "current_tier1_summ_delivered": 12594.68,
        "current_tier2_summ_delivered": 1632.55,
        "linkquality": 99,
        "tariff_period": "HP..",
    }).encode()
    r = _parse_tic(raw)
    assert r == {"hchc_kwh": 12594.68, "hchp_kwh": 1632.55, "papp_va": 319.0, "period": "HP"}


def test_parse_kwh_payload():
    raw = json.dumps({"HCHC": 12594.67, "HCHP": 1632.48, "PAPP": 331, "PTEC": "HC.."}).encode()
    r = _parse_tic(raw)
    assert r == {"hchc_kwh": 12594.67, "hchp_kwh": 1632.48, "papp_va": 331.0, "period": "HC"}


def test_parse_wh_payload_normalizes_to_kwh():
    # The Z2M lixee converter historically publishes the indexes in Wh.
    raw = json.dumps({"HCHC": 12594670, "HCHP": 1632480, "PTEC": "HP.."}).encode()
    r = _parse_tic(raw)
    assert r["hchc_kwh"] == pytest.approx(12594.67)
    assert r["hchp_kwh"] == pytest.approx(1632.48)
    assert r["papp_va"] is None  # frame without PAPP is fine
    assert r["period"] == "HP"


def test_parse_missing_index_yields_none():
    assert _parse_tic(json.dumps({"PAPP": 100}).encode()) is None


def test_parse_garbage_yields_none():
    assert _parse_tic(b"\x00\xffnot json") is None
    assert _parse_tic(json.dumps([1, 2]).encode()) is None


def test_parse_unknown_ptec_yields_no_period():
    raw = json.dumps({"HCHC": 1.0, "HCHP": 2.0, "PTEC": "TH.."}).encode()
    assert _parse_tic(raw)["period"] is None


def test_to_kwh_threshold():
    assert _to_kwh(12594.67) == 12594.67       # already kWh
    assert _to_kwh(12594670) == 12594.67       # Wh → kWh


# --- Integrator ---

def _now(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=PARIS_TZ)


def _reading(hchc: float, hchp: float, papp=None, period=None) -> dict:
    return {"hchc_kwh": hchc, "hchp_kwh": hchp, "papp_va": papp, "period": period}


@pytest.fixture
def tic_db(tmp_path, monkeypatch):
    """Temp DB + pristine integrator state for each test."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    repository.init_schema()
    monkeypatch.setattr(command, "_state", {"date": None, "hc_kwh": 0.0, "hp_kwh": 0.0,
                                            "base_hchc": None, "base_hphp": None,
                                            "last_persist": 0.0})
    monkeypatch.setattr(command, "_slot", {"start": None, "papp_sum": 0.0, "papp_n": 0})
    monkeypatch.setattr(command, "_period", None)
    monkeypatch.setattr(command, "_tariff_windows", {"HC": [], "HP": []})
    monkeypatch.setattr(command, "_open_window", None)
    monkeypatch.setattr(command, "_tariff_period", None)
    monkeypatch.setattr(command, "last_hchc", None)
    monkeypatch.setattr(command, "last_hphp", None)


def _today_row(date: str):
    rows = repository.get_cached_days(date, "2026-12-31")
    return rows[0] if rows else None


def test_first_frame_baselines_without_delta(tic_db):
    command._on_tic(_reading(100.0, 50.0), now=_now(5, 12, 0))
    assert command._state["hc_kwh"] == 0.0
    assert command._state["hp_kwh"] == 0.0
    assert command._state["base_hchc"] == 100.0


def test_index_deltas_accumulate(tic_db):
    command._on_tic(_reading(100.0, 50.0), now=_now(5, 12, 0))
    command._on_tic(_reading(101.2, 50.5), now=_now(5, 12, 1))
    assert command._state["hc_kwh"] == pytest.approx(1.2)
    assert command._state["hp_kwh"] == pytest.approx(0.5)
    # Persisted on the first frame (last_persist started at 0).
    assert _today_row("2026-06-05")["hc_kwh"] == 0.0


def test_negative_delta_rebaselines_without_adding(tic_db):
    command._on_tic(_reading(100.0, 50.0), now=_now(5, 12, 0))
    command._on_tic(_reading(90.0, 40.0), now=_now(5, 12, 1))  # index reset
    assert command._state["hc_kwh"] == 0.0
    assert command._state["base_hchc"] == 90.0
    command._on_tic(_reading(90.5, 40.0), now=_now(5, 12, 2))
    assert command._state["hc_kwh"] == pytest.approx(0.5)


def test_absurd_jump_rebaselines_without_adding(tic_db):
    command._on_tic(_reading(100.0, 50.0), now=_now(5, 12, 0))
    command._on_tic(_reading(100.0 + command.MAX_INDEX_STEP_KWH + 1, 50.0), now=_now(5, 12, 1))
    assert command._state["hc_kwh"] == 0.0


def test_slot_flush_writes_mean_papp_and_index_snapshot(tic_db):
    command._on_tic(_reading(100.0, 50.0, papp=300), now=_now(5, 12, 5))
    command._on_tic(_reading(100.1, 50.0, papp=500), now=_now(5, 12, 20))
    command._on_tic(_reading(100.2, 50.1, papp=100), now=_now(5, 12, 35))  # new slot
    conn = db.connect()
    rows = conn.execute("SELECT ts, hchc_kwh, hchp_kwh, papp_va FROM tic_samples ORDER BY ts").fetchall()
    conn.close()
    assert len(rows) == 1
    ts, hchc, hphp, papp = rows[0]
    assert ts.startswith("2026-06-05T12:00")
    assert hchc == pytest.approx(100.1)  # last indexes seen within the slot
    assert papp == 400                   # mean of 300 and 500


def test_slot_without_papp_stores_null(tic_db):
    command._on_tic(_reading(100.0, 50.0), now=_now(5, 12, 5))
    command._on_tic(_reading(100.1, 50.0), now=_now(5, 12, 35))
    conn = db.connect()
    papp = conn.execute("SELECT papp_va FROM tic_samples").fetchone()[0]
    conn.close()
    assert papp is None


def test_talon_uses_night_slots_only(tic_db):
    # A midday slot and two night slots (23h30 + 00h00 next day).
    command._on_tic(_reading(100.0, 50.0, papp=800), now=_now(5, 12, 5))
    command._on_tic(_reading(100.1, 50.0, papp=300), now=_now(5, 23, 35))  # flushes 12h slot
    command._on_tic(_reading(100.2, 50.0, papp=320), now=_now(6, 0, 1))    # flushes 23h30 slot + rollover
    assert repository.get_night_papp("2026-06-05") == [300]
    # The 800 W midday sample never reaches the talon.
    row = _today_row("2026-06-05")
    assert row["talon_w"] == 300


def test_rollover_persists_final_day_and_resets(tic_db):
    command._on_tic(_reading(100.0, 50.0, papp=300), now=_now(5, 23, 35))
    command._on_tic(_reading(100.5, 50.2, papp=300), now=_now(5, 23, 50))
    command._on_tic(_reading(100.6, 50.3, papp=320), now=_now(6, 0, 5))
    # Yesterday flushed with its accumulated deltas and its 23h30 night talon.
    row = _today_row("2026-06-05")
    assert row["hc_kwh"] == pytest.approx(0.5)
    assert row["hp_kwh"] == pytest.approx(0.2)
    assert row["talon_w"] == 300
    # New day: state reset, the midnight-straddling frame yields no delta.
    assert command._state["date"] == "2026-06-06"
    assert command._state["hc_kwh"] == 0.0
    assert command._state["base_hchc"] == 100.6


def test_restart_resumes_from_partial_row(tic_db):
    repository.upsert_day("2026-06-05", 3.0, 2.0, None)
    command._on_tic(_reading(100.0, 50.0), now=_now(5, 12, 0))
    command._on_tic(_reading(100.4, 50.1), now=_now(5, 12, 1))
    assert command._state["hc_kwh"] == pytest.approx(3.4)
    assert command._state["hp_kwh"] == pytest.approx(2.1)


def test_wh_scale_payload_through_full_path(tic_db):
    r1 = _parse_tic(json.dumps({"HCHC": 12594670, "HCHP": 1632480}).encode())
    r2 = _parse_tic(json.dumps({"HCHC": 12595170, "HCHP": 1632580}).encode())
    command._on_tic(r1, now=_now(5, 12, 0))
    command._on_tic(r2, now=_now(5, 12, 1))
    assert command._state["hc_kwh"] == pytest.approx(0.5)
    assert command._state["hp_kwh"] == pytest.approx(0.1)


# --- is_off_peak (the meter's live PTEC, trusted regardless of age) ---

def test_is_off_peak_follows_the_last_ptec(tic_db):
    command._on_tic(_reading(1.0, 2.0, period="HC"), now=_now(5, 12, 0))
    assert command.is_off_peak() is True   # the meter says HC
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 0, 30))
    assert command.is_off_peak() is False  # the meter then says HP


def test_is_off_peak_is_peak_before_any_ptec(tic_db):
    # No PTEC seen yet → reports peak (False), so the off-peak split never
    # over-counts on a cold start (no clock guess anymore).
    assert command.is_off_peak() is False


# --- current_tariff (last completed window per period) ---

def test_current_tariff_none_until_a_window_completes(tic_db):
    assert command.current_tariff() is None
    # The first frame only baselines the period — not a switch.
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 12, 0))
    assert command.current_tariff() is None
    # The first transition only opens a window (nothing to close yet).
    command._on_tic(_reading(1.0, 2.0, period="HC"), now=_now(5, 15, 2))
    assert command.current_tariff() is None


def test_current_tariff_after_first_window_completes(tic_db):
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 12, 0))
    command._on_tic(_reading(1.0, 2.0, period="HC"), now=_now(5, 15, 2))
    # The second transition closes the HC window (15:02 → 17:02).
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 17, 2))
    tariff = command.current_tariff()
    assert tariff["period"] == "HP"
    assert tariff["hc"] == [(_now(5, 15, 2), _now(5, 17, 2))]
    # HP's own window hasn't completed yet.
    assert tariff["hp"] == []


def test_current_tariff_keeps_both_periods(tic_db):
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 12, 0))
    command._on_tic(_reading(1.0, 2.0, period="HC"), now=_now(5, 15, 2))
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 17, 2))
    # The third transition closes the HP window (17:02 → 18:00).
    command._on_tic(_reading(1.0, 2.0, period="HC"), now=_now(5, 18, 0))
    tariff = command.current_tariff()
    assert tariff["period"] == "HC"
    assert tariff["hc"] == [(_now(5, 15, 2), _now(5, 17, 2))]
    assert tariff["hp"] == [(_now(5, 17, 2), _now(5, 18, 0))]


def test_current_tariff_keeps_last_two_windows_per_period(tic_db):
    # Each HC→HP→HC… cycle completes one window per period. Drive enough
    # transitions to accumulate three HC windows and assert only the last two
    # are kept (oldest first → chronological).
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 0, 0))
    command._on_tic(_reading(1.0, 2.0, period="HC"), now=_now(5, 1, 0))
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 2, 0))  # HC #1: 1→2
    command._on_tic(_reading(1.0, 2.0, period="HC"), now=_now(5, 3, 0))
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 4, 0))  # HC #2: 3→4
    command._on_tic(_reading(1.0, 2.0, period="HC"), now=_now(5, 5, 0))
    command._on_tic(_reading(1.0, 2.0, period="HP"), now=_now(5, 6, 0))  # HC #3: 5→6
    tariff = command.current_tariff()
    assert tariff["hc"] == [(_now(5, 3, 0), _now(5, 4, 0)),
                            (_now(5, 5, 0), _now(5, 6, 0))]
