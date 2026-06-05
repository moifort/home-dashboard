"""Unit tests for the night-only talon helper `compute_talon_w`.

The talon must read the solar-free night window (23h–05h) only — its samples
are the per-slot mean PAPP collected by the TIC integrator — and P20 must skip
the deepest night dip. These are pinned here on synthetic night sample lists.
"""
from app.electricity.infrastructure.linky_client import compute_talon_w

NIGHT_FLOOR = 300  # stable standby at night


def test_talon_reads_night_floor():
    # Eleven stable night slots → the talon is the floor itself.
    assert compute_talon_w([NIGHT_FLOOR] * 11) == NIGHT_FLOOR


def test_p20_skips_the_single_deep_night_dip():
    # One 50W night sample among eleven 300W ones must not become the talon.
    assert compute_talon_w([50] + [NIGHT_FLOOR] * 11) == NIGHT_FLOOR


def test_no_samples_yields_none():
    # No night sample (partial boundary day) → None, not a bogus 0.
    assert compute_talon_w([]) is None
