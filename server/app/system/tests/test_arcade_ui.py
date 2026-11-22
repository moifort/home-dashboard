"""The "arcade" renderer and its DASHBOARD_UI route.

The classic layout stays guarded by the render golden; here we check that arcade
renders a full-size frame in the panel's inks only (no anti-aliased grey that the
converter would re-threshold), that it survives missing domains, and the helpers
that turn the raw series into what the screen shows.
"""
import copy
import json

import pytest

from app.rendering import arcade, renderer
from app.rendering.arcade import render_arcade
from app.system import config
from app.system.tests.conftest import FIXTURES_DIR

INKS = {(0, 0, 0), (255, 255, 255), (255, 0, 0)}


@pytest.fixture
def data():
    return json.loads((FIXTURES_DIR / "dashboard_data.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_arcade_uses_only_panel_inks(data, theme):
    img = render_arcade(data, theme)
    assert img.size == (1360, 480)
    colors = {c for _, c in img.getcolors(maxcolors=1 << 16)}
    assert colors <= INKS
    assert (255, 0, 0) in colors  # the fixture has active alerts


def test_arcade_survives_a_minimal_payload():
    render_arcade({"days": [], "stats": {}})


def test_arcade_survives_each_missing_domain(data):
    for key in ("water_days", "production_days", "crypto", "crypto_grid", "unifi", "plants",
                "power_sensors", "homelab", "talon", "alert_board"):
        partial = copy.deepcopy(data)
        partial.pop(key)
        render_arcade(partial)


def test_home_lab_row_only_drawn_when_fed(data):
    """Without the home lab the bottom band stays empty paper."""
    def band(d):
        return render_arcade(d).crop((0, arcade.ROW_C, 1360, 480)).getcolors()
    without = copy.deepcopy(data)
    without.pop("homelab")
    assert band(without) == [(1360 * (480 - arcade.ROW_C), (0, 0, 0))]
    assert len(band(data)) > 1


def test_an_offline_pi_turns_the_counter_red(data):
    data["homelab"]["nodes"][1]["online"] = False
    data["homelab"]["online"] = 3
    img = render_arcade(data)
    x, y = arcade.XS[0], arcade.ROW_C + 26  # the "3/4" figure, top-left pixel of the 3
    assert img.getpixel((x, y)) == (255, 0, 0)


def test_six_servers_fit_the_row(data):
    """Five or six servers switch the row to narrow columns, inside the margins."""
    lab = data["homelab"]
    lab["nodes"] += [dict(lab["nodes"][0], name=f"pi-{i}") for i in (5, 6)]
    lab["online"] = lab["total"] = 6
    img = render_arcade(data)
    assert {c for _, c in img.getcolors(maxcolors=1 << 16)} <= INKS
    row = img.crop((0, arcade.ROW_C, 1360, 480))
    left, top, right, bottom = row.getbbox()
    assert left >= arcade.XS[0] - 2 and right <= 1360 - arcade.XS[0] and bottom <= 480 - arcade.ROW_C - 4


def test_switch_routes_to_arcade_dark_by_default(data, monkeypatch):
    monkeypatch.setattr(config, "DASHBOARD_UI", "arcade")
    monkeypatch.setattr(config, "DASHBOARD_THEME", "")
    assert renderer.render_dashboard(data).getpixel((0, 0)) == (0, 0, 0)
    monkeypatch.setattr(config, "DASHBOARD_THEME", "light")
    assert renderer.render_dashboard(data).getpixel((0, 0)) == (255, 255, 255)


def test_last_24h_joins_yesterday_and_today():
    days = [{"intraday": list(range(100, 148))},
            {"today": True, "intraday": list(range(200, 210)) + [None] * 38}]
    slots = arcade._last_24h(days, now_slot=10)
    assert len(slots) == 48
    assert slots[0] == 110 and slots[37] == 147   # yesterday from the same clock time
    assert slots[38] == 200 and slots[-1] == 209  # today up to the refresh


def test_hourly_max_keeps_a_short_peak():
    assert arcade._hourly_max([300, 2900, None, 400, None, None]) == [2900, 400, None]


@pytest.mark.parametrize("now, expected", [
    ("14:00", ("heures creuses, pleines à ", "15:00")),
    ("06:00", ("heures pleines, creuses à ", "13:00")),
    ("23:45", ("heures creuses, pleines à ", "05:32")),
    ("18:00", ("heures pleines, creuses à ", "23:32")),
])
def test_period_text_follows_the_tariff(data, now, expected):
    home = dict(data["home"], last_text=now)
    assert arcade._period_text(home) == expected


def test_unreadable_figure_falls_back(data):
    assert arcade._figure("N/A") == "--"
    assert arcade._figure(None) == "--"
    assert arcade._figure("+12") == "+12"
