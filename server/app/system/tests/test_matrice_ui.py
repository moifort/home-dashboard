"""The DASHBOARD_UI switch and the "matrice" renderer.

The classic layout stays guarded by the render golden; here we only check that
the switch routes correctly and that matrice renders a full-size frame in the
panel's inks only (no anti-aliased grey that the converter would re-threshold).
"""
import json

import pytest

from app.rendering import renderer
from app.rendering.matrice import render_matrice
from app.system import config
from app.system.tests.conftest import FIXTURES_DIR

INKS = {(0, 0, 0), (255, 255, 255), (255, 0, 0)}


@pytest.fixture
def data():
    return json.loads((FIXTURES_DIR / "dashboard_data.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_matrice_uses_only_panel_inks(data, theme):
    img = render_matrice(data, theme)
    assert img.size == (1360, 480)
    colors = {c for _, c in img.getcolors(maxcolors=1 << 16)}
    assert colors <= INKS
    assert (255, 0, 0) in colors  # the fixture has active alerts


def test_matrice_survives_a_minimal_payload():
    render_matrice({"days": [], "stats": {}}, "light")


def test_switch_defaults_to_classic(data, monkeypatch):
    monkeypatch.setattr(config, "DASHBOARD_UI", "classic")
    called = []
    monkeypatch.setattr(renderer, "_render_classic", lambda d: called.append("classic"))
    renderer.render_dashboard(data)
    assert called == ["classic"]


def test_switch_routes_to_matrice_with_theme(data, monkeypatch):
    monkeypatch.setattr(config, "DASHBOARD_UI", "matrice")
    monkeypatch.setattr(config, "DASHBOARD_THEME", "dark")
    img = renderer.render_dashboard(data)
    assert img.getpixel((0, 0)) == (0, 0, 0)  # dark theme paper
