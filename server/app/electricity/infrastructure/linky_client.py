"""Linky domain logic: HC/HP window parsing and the talon percentile.

The teleinfo transport lives in zlinky_mqtt.py; this module holds the pure
helpers shared by the core integrator and the power sub-domain (off-peak
windows, night-talon math).
"""
import logging

logger = logging.getLogger(__name__)


def parse_hc_windows(windows_str: str) -> list[tuple[int, int, int, int]]:
    """Parse HC windows string into list of (start_h, start_m, end_h, end_m) tuples.

    Example: "23:32-5:32,15:02-17:02" -> [(23, 32, 5, 32), (15, 2, 17, 2)]
    """
    windows = []
    for part in windows_str.split(","):
        start_str, end_str = part.strip().split("-")
        sh, sm = start_str.split(":")
        eh, em = end_str.split(":")
        windows.append((int(sh), int(sm), int(eh), int(em)))
    return windows


# Talon (baseline) = a low percentile of the day's NIGHT 30-min power samples, in W.
# Daytime grid draw is net of self-consumed solar, so daytime samples get
# crushed by PV injection and would drag the percentile down. We restrict to a
# solar-free night window (23h–05h) to read the true permanent floor. Over the
# ~12 night samples, P20 lands on the ~3rd lowest, skipping the deepest dips
# (e.g. fridge + everything off at once).
TALON_PCT = 20
TALON_NIGHT_START = 23  # hour, inclusive
TALON_NIGHT_END = 5     # hour, exclusive  → 23h–05h, dark year-round


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (nearest-rank fallback for tiny series)."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (pct / 100) * (len(s) - 1)
    lo = int(rank)
    frac = rank - lo
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * frac


def compute_talon_w(night_samples: list[float]) -> int | None:
    """Talon = P20 of the day's night power samples (W), or None without samples.

    No night sample (partial boundary day) → None, not a bogus 0;
    rules._compute_talon filters None out.
    """
    if not night_samples:
        return None
    return round(_percentile(night_samples, TALON_PCT))


def _is_off_peak(hour: int, minute: int, hc_windows: list[tuple[int, int, int, int]]) -> bool:
    t = hour * 60 + minute
    for sh, sm, eh, em in hc_windows:
        start = sh * 60 + sm
        end = eh * 60 + em
        if start > end:
            if t >= start or t < end:
                return True
        else:
            if start <= t < end:
                return True
    return False
