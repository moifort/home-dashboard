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


def _set_tariff(monkeypatch, period, changes):
    monkeypatch.setattr(command, "_tariff_period", period)
    monkeypatch.setattr(command, "_tariff_changes", changes)


def test_build_home_live_includes_tariff(monkeypatch):
    _set_tariff(monkeypatch, "HP",
                {"HP": datetime(2026, 6, 7, 17, 2, tzinfo=PARIS_TZ), "HC": None})
    home = dashboard.build_home_live(NOW)
    assert home["last_text"] == "16:30"
    assert home["tariff"] == {"period": "HP", "since_text": "17:02"}


def test_build_home_live_includes_both_switches(monkeypatch):
    _set_tariff(monkeypatch, "HC",
                {"HC": datetime(2026, 6, 7, 15, 2, tzinfo=PARIS_TZ),
                 "HP": datetime(2026, 6, 7, 5, 32, tzinfo=PARIS_TZ)})
    home = dashboard.build_home_live(NOW)
    assert home["tariff"] == {"period": "HC", "since_text": "15:02",
                              "other_period": "HP", "other_since_text": "05:32"}


def test_build_home_live_without_transition(monkeypatch):
    _set_tariff(monkeypatch, None, {"HC": None, "HP": None})
    home = dashboard.build_home_live(NOW)
    assert "tariff" not in home
    assert home["last_text"] == "16:30"
