"""Linky domain logic: the night-talon percentile.

The teleinfo transport lives in zlinky_mqtt.py; this module holds the pure
night-talon math shared by the core integrator and the power sub-domain.
"""

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
