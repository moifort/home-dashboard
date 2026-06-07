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


def test_build_home_live_includes_tariff(monkeypatch):
    monkeypatch.setattr(command, "_tariff_change",
                        ("HP", datetime(2026, 6, 7, 17, 2, tzinfo=PARIS_TZ)))
    home = dashboard.build_home_live(NOW)
    assert home["last_text"] == "16:30"
    assert home["tariff"] == {"period": "HP", "since_text": "17:02"}


def test_build_home_live_without_transition(monkeypatch):
    monkeypatch.setattr(command, "_tariff_change", (None, None))
    home = dashboard.build_home_live(NOW)
    assert "tariff" not in home
    assert home["last_text"] == "16:30"
