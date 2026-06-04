"""Layer 2 — render golden.

A frozen, complete data dict (every panel, incl. crypto/UniFi) →
render_dashboard() → png_to_epd_buffer() → compared byte-for-byte to
display.golden.bin (the 163 200-byte buffer the ESP32 pulls).

The committed input is `dashboard_data.json`; under --update-golden it is rebuilt
from the seeded pipeline + the demo panels (mirroring scripts/gen_preview.py).
Font rendering depends on FreeType, which can differ across platforms, so the
buffer compare honours GOLDEN_TOLERANCE (fraction of differing bytes, default 0)
and writes /tmp diagnostics on any mismatch.
"""
import json
import os
import warnings
from datetime import timedelta
from io import BytesIO

from app.module import db
from app.dashboard_data import build_dashboard_data
from app.rendering.converter import png_to_epd_buffer
from app.rendering.renderer import render_dashboard
from tests._golden import buffer_diff, canonical_json, diff_image, epd_buffer_to_image
from tests.conftest import FIXTURES_DIR
from tests.fixtures.build_fixture import apply_demo_panels
from tests.fixtures.seed_db import TODAY

FIXTURE = FIXTURES_DIR / "dashboard_data.json"
GOLDEN = FIXTURES_DIR / "display.golden.bin"
EXPECTED_SIZE = 163_200  # 1360 × 480 ÷ 4 (2 bits/pixel)


def _render_buffer(data: dict) -> bytes:
    img = render_dashboard(data)
    png = BytesIO()
    img.save(png, format="PNG")
    return png_to_epd_buffer(png.getvalue(), mode="4color")


def test_render_golden(seeded_db, update_golden):
    if update_golden:
        start = (TODAY - timedelta(days=60)).strftime("%Y-%m-%d")
        end = (TODAY + timedelta(days=1)).strftime("%Y-%m-%d")
        data = apply_demo_panels(build_dashboard_data(db.get_cached_days(start, end)))
        FIXTURE.write_text(canonical_json(data), encoding="utf-8")
    else:
        assert FIXTURE.exists(), "Run `pytest --update-golden` once to create the fixture."

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    buf = _render_buffer(data)
    assert len(buf) == EXPECTED_SIZE, f"buffer is {len(buf)} bytes, expected {EXPECTED_SIZE}"

    if update_golden:
        GOLDEN.write_bytes(buf)
        return

    assert GOLDEN.exists(), "Run `pytest --update-golden` once to create the baseline."
    golden = GOLDEN.read_bytes()
    diff_count, frac = buffer_diff(buf, golden)
    tol = float(os.environ.get("GOLDEN_TOLERANCE", "0") or 0)

    if diff_count:
        # Always leave diagnostics behind so a mismatch can be eyeballed.
        epd_buffer_to_image(buf).save("/tmp/render_actual.png")
        epd_buffer_to_image(golden).save("/tmp/render_golden.png")
        diff_image(buf, golden).save("/tmp/render_diff.png")
        msg = (f"render buffer differs by {diff_count} bytes ({frac:.4%}); "
               f"see /tmp/render_actual.png, /tmp/render_golden.png, /tmp/render_diff.png")
        if frac > tol:
            raise AssertionError(msg + f" (tolerance {tol:.4%})")
        warnings.warn(msg + f" — within tolerance {tol:.4%}")
