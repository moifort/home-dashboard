"""Crypto grid chart: what the price line shows and where validated cycles land.

Two rules guard the top-right grid snapshot:
  * a price outside the grid bounds is **cut out**, never clamped — clamping
    flattened the line onto the axis, which read as a zero price for the whole
    stretch the price spent out of the grid;
  * a completed trade is a dot on the leg that closed it, so a cycle opened by
    an inventory sell lands on its buy-back, not on the sell.
"""
from datetime import datetime, timezone

from app.crypto.infrastructure.graphql.transport import _parse_cycles
from app.rendering.renderer import _clip_to_band

LOWER, UPPER = 96000.0, 104000.0


def _order(price, filled_at):
    return {"price": price, "filledAt": filled_at}


def test_series_inside_the_band_is_one_untouched_run():
    points = [(0, 98000.0), (1, 101000.0), (2, 99000.0)]
    assert _clip_to_band(points, LOWER, UPPER) == [points]


def test_excursion_below_the_grid_leaves_a_gap():
    # Down to 94000 between t=1 and t=3, back inside at t=4: two runs, each
    # ending exactly on the lower bound instead of a flat line on the axis.
    points = [(0, 98000.0), (1, 97000.0), (2, 94000.0), (3, 95000.0), (4, 97000.0)]
    runs = _clip_to_band(points, LOWER, UPPER)
    assert len(runs) == 2
    assert runs[0][0] == (0, 98000.0)
    assert runs[0][-1] == (1 + (LOWER - 97000.0) / (94000.0 - 97000.0), LOWER)
    assert runs[1][-1] == (4, 97000.0)
    assert all(LOWER <= p <= UPPER for run in runs for _, p in run)


def test_series_fully_outside_draws_nothing():
    assert _clip_to_band([(0, 90000.0), (1, 91000.0)], LOWER, UPPER) == []


def test_segment_crossing_the_whole_band_keeps_its_visible_part():
    runs = _clip_to_band([(0, 90000.0), (1, 110000.0)], LOWER, UPPER)
    assert len(runs) == 1
    assert [p for _, p in runs[0]] == [LOWER, UPPER]


def test_cycle_sits_on_the_leg_filled_last():
    # Opened by an inventory sell: the buy-back closes the cycle, so the dot
    # carries the buy price and the buy time.
    cycles = _parse_cycles([{
        "status": "completed", "profitUsdc": 12.5,
        "sellOrder": _order(101000.0, "2026-06-01T10:00:00Z"),
        "buyOrder": _order(99500.0, "2026-06-01T14:00:00Z"),
    }])
    assert len(cycles) == 1
    assert cycles[0]["price"] == 99500.0
    assert cycles[0]["profit"] == 12.5
    assert cycles[0]["time"] == datetime(2026, 6, 1, 14, tzinfo=timezone.utc).timestamp()


def test_only_completed_trades_with_a_fill_are_plotted():
    cycles = _parse_cycles([
        {"status": "holding", "buyOrder": _order(99000.0, "2026-06-01T10:00:00Z")},
        {"status": "completed", "buyOrder": _order(99000.0, None),
         "sellOrder": _order(101000.0, None)},
        {"status": "completed", "profitUsdc": -3.0,
         "buyOrder": _order(99000.0, "2026-06-01T10:00:00Z"), "sellOrder": None},
    ])
    assert [c["profit"] for c in cycles] == [-3.0]
