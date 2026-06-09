"""The Home panel dict built at the ESP32 pull must keep the tariff line.

Regression: the /display pull rebuilt data["home"] from scratch (fresh pull
time), wiping the tariff key attached by the hourly build_dashboard_data —
the line never reached the screen.
"""
from datetime import datetime

from app.system.config import PARIS_TZ
from app import dashboard_data as dashboard
from app.electricity import command


NOW = datetime(2026, 6, 7, 16, 30, tzinfo=PARIS_TZ)


def _set_tariff(monkeypatch, period, windows):
    monkeypatch.setattr(command, "_tariff_period", period)
    monkeypatch.setattr(command, "_tariff_windows", windows)


def _dt(h, m):
    return datetime(2026, 6, 7, h, m, tzinfo=PARIS_TZ)


def test_build_home_live_includes_one_window(monkeypatch):
    # Only HP's window has completed so far → a single tariff line.
    _set_tariff(monkeypatch, "HC",
                {"HC": [], "HP": [(_dt(5, 32), _dt(13, 0))]})
    home = dashboard.build_home_live(NOW)
    assert home["last_text"] == "16:30"
    assert home["tariff"] == [{"period": "HP", "start_text": "05:32",
                               "end_text": "13:00"}]


def test_build_home_live_includes_both_windows(monkeypatch):
    _set_tariff(monkeypatch, "HC",
                {"HC": [(_dt(13, 0), _dt(15, 0))],
                 "HP": [(_dt(5, 32), _dt(13, 0))]})
    home = dashboard.build_home_live(NOW)
    assert home["tariff"] == [
        {"period": "HC", "start_text": "13:00", "end_text": "15:00"},
        {"period": "HP", "start_text": "05:32", "end_text": "13:00"},
    ]


def test_build_home_live_includes_all_windows_grouped(monkeypatch):
    # The full day: two HC and two HP windows → four lines, HC group then HP.
    # The label appears only on the first line of each group.
    _set_tariff(monkeypatch, "HP",
                {"HC": [(_dt(23, 32), _dt(5, 32)), (_dt(15, 2), _dt(17, 2))],
                 "HP": [(_dt(5, 32), _dt(15, 2)), (_dt(17, 2), _dt(23, 32))]})
    home = dashboard.build_home_live(NOW)
    assert home["tariff"] == [
        {"period": "HC", "start_text": "23:32", "end_text": "05:32"},
        {"period": "", "start_text": "15:02", "end_text": "17:02"},
        {"period": "HP", "start_text": "05:32", "end_text": "15:02"},
        {"period": "", "start_text": "17:02", "end_text": "23:32"},
    ]


def test_build_home_live_without_completed_window(monkeypatch):
    _set_tariff(monkeypatch, None, {"HC": [], "HP": []})
    home = dashboard.build_home_live(NOW)
    assert "tariff" not in home
    assert home["last_text"] == "16:30"
