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
    assert band(without) == [(1360 * (480 - arcade.ROW_C), (255, 255, 255))]
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
    img = render_arcade(data, "dark")  # black paper, so getbbox frames the ink
    assert {c for _, c in img.getcolors(maxcolors=1 << 16)} <= INKS
    row = img.crop((0, arcade.ROW_C, 1360, 480))
    left, top, right, bottom = row.getbbox()
    assert left >= arcade.XS[0] - 2 and right <= 1360 - arcade.XS[0] and bottom <= 480 - arcade.ROW_C - 4


def test_switch_routes_to_arcade_light_by_default(data, monkeypatch):
    monkeypatch.setattr(config, "DASHBOARD_UI", "arcade")
    monkeypatch.setattr(config, "DASHBOARD_THEME", "")
    assert renderer.render_dashboard(data).getpixel((0, 0)) == (255, 255, 255)
    monkeypatch.setattr(config, "DASHBOARD_THEME", "dark")
    assert renderer.render_dashboard(data).getpixel((0, 0)) == (0, 0, 0)


def test_last_24h_joins_yesterday_and_today():
    days = [{"intraday": list(range(100, 148))},
            {"today": True, "intraday": list(range(200, 210)) + [None] * 38}]
    slots = arcade._last_24h(days, now_slot=10)
    assert len(slots) == 48
    assert slots[0] == 110 and slots[37] == 147   # yesterday from the same clock time
    assert slots[38] == 200 and slots[-1] == 209  # today up to the refresh


def test_hourly_max_keeps_a_short_peak():
    assert arcade._hourly_max([300, 2900, None, 400, None, None]) == [2900, 400, None]


def test_closes_keep_the_last_price_of_each_window():
    points = [(0, 10.0), (1800, 11.0), (3600, 12.0), (9000, 15.0), (10800, 16.0)]
    assert arcade._closes(points, 3600, 4) == [10.0, 12.0, None, 16.0]


def test_hourly_sum_adds_the_two_halves():
    assert arcade._hourly_sum([3, 4, None, 5, None, None]) == [7, 5, None]


def test_off_peak_hours_follow_the_half_hour_holding_the_peak():
    """Columns start at now_slot: here 22:00, with off-peak from 23:30 (slot 47)."""
    slots = [100, 200, 300, 900, 500, 400, None, None]  # 22:00 .. 01:30
    hc = {47, 0, 1, 2, 3}
    assert arcade._off_peak_hours(slots, 44, hc) == {1, 2}
    assert arcade._off_peak_hours([100, 200, 900, 300], 44, hc) == set()  # 23:00 peaks before 23:30
    assert arcade._off_peak_hours(slots, None, hc) == set()


def _cell(img, x, y):
    """'filled', 'hollow' or 'dot' for the 5px chart cell whose top-left is (x, y)."""
    ink = (0, 0, 0)
    if img.getpixel((x, y)) != ink:
        return "dot"
    return "filled" if img.getpixel((x + 2, y + 2)) == ink else "hollow"


def test_days_chart_stacks_off_peak_hollow_over_peak_filled(data):
    """A day that is all off-peak is drawn in hollow squares, an all-peak one filled."""
    days = data["days"]
    days[0].update(hc_kwh=10.0, hp_kwh=0.0)
    days[1].update(hc_kwh=0.0, hp_kwh=10.0)
    img = render_arcade(data)
    x, bottom = arcade.XS[0], arcade.ROW_A + 126
    column = lambda i: {_cell(img, x + i * arcade.PITCH, bottom - (j + 1) * arcade.PITCH)
                        for j in range(arcade.CHART_ROWS)}
    assert column(0) == {"hollow"}
    assert column(1) == {"filled"}


def test_last_24h_chart_draws_off_peak_hours_hollow(data):
    """At 14:00 the last column is the 13:00 hour, off-peak in the fixture; the
    column of 11:00 is a peak hour."""
    img = render_arcade(data)
    x, y = arcade.XS[0] + arcade.X_24H, arcade.ROW_A + 126 - arcade.PITCH
    assert _cell(img, x + 23 * arcade.PITCH, y) == "hollow"
    assert _cell(img, x + 21 * arcade.PITCH, y) == "filled"


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
