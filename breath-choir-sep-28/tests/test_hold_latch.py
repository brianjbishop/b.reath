"""
The hold must survive upstream renormalisation.

TOTEM normalises breath as a rolling min/max of phone roll. Hold your breath
and the window gradually forgets the breathing that set its range, so the value
it reports *drifts* even though the performer has not moved. That drift has
slope, so a slope-based exit reads it as a fresh inhale or exhale and the hold
silently ends mid-hold — exactly the behaviour we are guarding against.

These replay the iOS algorithm (both app versions) and assert the hold stays
latched through it.
"""

from __future__ import annotations

import math
import random

import pytest

from breath_midi.signal.features import FeatureExtractor
from breath_midi.types import Phase, ProcessedSample

from .test_phase_fsm import DT, SAMPLE_HZ, flat, make_detection, ramp

# TOTEM (the older app): one window, ~6.7s at 60Hz.
TOTEM_WINDOW = int(6.67 * SAMPLE_HZ)
# TOTEM Live: falls back to a ~16.7s window when the narrow range collapses.
TOTEM_LIVE_NARROW = int(10.0 * SAMPLE_HZ)
TOTEM_LIVE_FULL = int(16.7 * SAMPLE_HZ)

NOISE = 0.002  # radians of attitude jitter
ROLL_AMP = 0.30  # radians of roll swing across a full breath


def totem_normalize(roll: list[float], window: int = TOTEM_WINDOW) -> list[float]:
    """BreathProcessor.normalizeBreath() — single rolling min/max."""
    out, buf = [], []
    for r in roll:
        buf.append(r)
        if len(buf) > window:
            buf = buf[-window:]
        lo, hi = min(buf), max(buf)
        rng = hi - lo
        out.append(0.0 if rng == 0 else (r - lo) / rng)
    return out


def totem_live_normalize(roll: list[float]) -> list[float]:
    """
    TOTEM Live's RangeTracker: narrow window, falling back to the full window
    when the narrow range collapses below 20% of it, recovering at 70%.
    """
    out, buf = [], []
    using_full = False
    for r in roll:
        buf.append(r)
        if len(buf) > TOTEM_LIVE_FULL:
            buf = buf[-TOTEM_LIVE_FULL:]
        narrow = buf[-TOTEM_LIVE_NARROW:]
        n_lo, n_hi = min(narrow), max(narrow)
        f_lo, f_hi = min(buf), max(buf)
        full_range = f_hi - f_lo
        narrow_range = n_hi - n_lo
        if narrow_range <= full_range * 0.2:
            using_full = True
        elif narrow_range >= full_range * 0.7 and using_full:
            using_full = False
        lo, hi = (f_lo, f_hi) if using_full else (n_lo, n_hi)
        rng = hi - lo
        out.append(0.0 if rng == 0 else max(0.0, min(1.0, (r - lo) / rng)))
    return out


def breath_then_long_hold(hold_s: float, warmup_cycles: int = 3) -> list[float]:
    """Normal breathing to establish a range, then hold at the top."""
    random.seed(11)
    s: list[float] = []
    for _ in range(warmup_cycles):
        s += ramp(0.0, ROLL_AMP, 2.0) + ramp(ROLL_AMP, 0.0, 2.0)
    s += ramp(0.0, ROLL_AMP, 2.0)  # inhale into the hold
    s += flat(ROLL_AMP, hold_s)  # ...and hold there, motionless
    return [v + random.gauss(0, NOISE) for v in s]


def phases(norm: list[float], cfg=None) -> list[Phase]:
    """
    Run the real chain, SignalProcessor then FeatureExtractor, exactly as
    DeviceRuntime does. Feeding the extractor directly would skip the smoothing
    the detector's thresholds are tuned against and make the test lie.
    """
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.signal.processor import SignalProcessor
    from breath_midi.types import BreathSample

    shipped = ConfigStore(Path(__file__).parent.parent / "config.toml").load()
    sp = SignalProcessor(shipped.signal)
    fx = FeatureExtractor(cfg or shipped.detection)
    return [
        fx.update(sp.process(BreathSample(t=i * DT, amp=a, source_id="p"))).phase
        for i, a in enumerate(norm)
    ]


def tail_phase(ph: list[Phase], seconds: float = 1.0) -> set[Phase]:
    """Phases seen in the last `seconds` of the run."""
    return set(ph[-int(seconds * SAMPLE_HZ) :])


# ── the core requirement ─────────────────────────────────────────────────────


@pytest.mark.parametrize("hold_s", [3.0, 8.0, 12.0, 16.0])
def test_hold_survives_totem_live_renormalisation(hold_s: float):
    """
    Still holding at the end of the take, for any hold up to the length of the
    normalisation window. Past that the signal itself is gone — see
    test_documents_the_hold_ceiling.
    """
    norm = totem_live_normalize(breath_then_long_hold(hold_s))
    ph = phases(norm)
    assert tail_phase(ph) == {Phase.HOLD}, (
        f"hold of {hold_s}s did not stay latched; ended in {tail_phase(ph)}"
    )


@pytest.mark.parametrize("hold_s", [3.0, 5.0])
def test_hold_survives_older_totem_renormalisation(hold_s: float):
    """
    Same on the older single-window app, whose window is only ~6.7s. This is
    the case that motivated latching on displacement rather than slope: before
    the latch, noise made the phase chatter and a hold never formed at all.
    """
    norm = totem_normalize(breath_then_long_hold(hold_s))
    ph = phases(norm)
    assert Phase.HOLD in tail_phase(ph, seconds=2.0), (
        f"hold of {hold_s}s was lost on the older app; ended in {tail_phase(ph)}"
    )


def test_hold_does_not_end_itself_without_a_breath():
    """Nothing but drift for 16s — the phase must not flip on its own."""
    norm = totem_live_normalize(breath_then_long_hold(16.0))
    ph = phases(norm)
    hold_start = next(i for i, p in enumerate(ph) if p is Phase.HOLD)
    after = ph[hold_start:]
    assert set(after) == {Phase.HOLD}, (
        f"hold broke by itself: {[p.value for p in after if p is not Phase.HOLD][:5]}"
    )


def test_documents_the_hold_ceiling():
    """
    The latch works right up to the normalisation window and no further. Past
    it the window contains only hold data, its range collapses, and the value
    stops meaning anything — no detector can recover that.

    This records where each app gives out so a regression in the latch is
    distinguishable from the signal simply running out.
    """
    def survives(norm_fn, hold_s: float) -> bool:
        return phases(norm_fn(breath_then_long_hold(hold_s)))[-1] is Phase.HOLD

    # TOTEM Live: ~16.7s window.
    assert survives(totem_live_normalize, 16.0)
    assert not survives(totem_live_normalize, 20.0)
    # TOTEM: ~6.7s window.
    assert survives(totem_normalize, 5.0)
    assert not survives(totem_normalize, 8.0)


# ── but a real breath must still break it ────────────────────────────────────


def test_real_exhale_breaks_the_hold():
    roll = breath_then_long_hold(10.0) + ramp(ROLL_AMP, 0.0, 2.0)
    ph = phases(totem_live_normalize(roll))
    assert ph[-1] is Phase.EXHALE, f"exhale did not break the hold; got {ph[-1]}"


def test_inhaling_further_from_a_peak_hold_is_invisible():
    """
    A known limitation, recorded rather than fixed.

    Min/max normalisation means the running maximum *is* 1.0 by definition. So
    a performer already at the top of their range who inhales deeper produces
    almost no change in the reported value — doubling the roll moves it about
    0.02 — and the hold cannot break on displacement.

    No threshold setting fixes this; it is a property of the upstream signal.
    Breaking a peak hold requires exhaling, which does move the value.
    """
    roll = breath_then_long_hold(8.0) + ramp(ROLL_AMP, ROLL_AMP * 2, 2.0)
    norm = totem_live_normalize(roll)
    at_hold = norm[-int(2 * SAMPLE_HZ)]
    after_topup = norm[-1]
    assert abs(after_topup - at_hold) < 0.05, (
        "normalisation no longer absorbs a top-up; this limitation may have changed"
    )
    assert phases(norm)[-1] is Phase.HOLD


def test_inhaling_from_a_valley_hold_does_break_it():
    """The valley end has headroom, so rising out of it is visible."""
    random.seed(11)
    roll = []
    for _ in range(3):
        roll += ramp(0.0, ROLL_AMP, 2.0) + ramp(ROLL_AMP, 0.0, 2.0)
    roll += flat(0.0, 5.0) + ramp(0.0, ROLL_AMP, 2.0)
    roll = [v + random.gauss(0, NOISE) for v in roll]
    ph = phases(totem_live_normalize(roll))
    assert ph[-1] is Phase.INHALE, f"expected INHALE out of a valley hold, got {ph[-1]}"


def test_hold_reenters_after_a_full_breath():
    """Hold, breathe out, breathe in, hold again — two distinct holds."""
    roll = (
        breath_then_long_hold(5.0)
        + ramp(ROLL_AMP, 0.0, 2.0)
        + ramp(0.0, ROLL_AMP, 2.0)
        + flat(ROLL_AMP, 5.0)
    )
    ph = phases(totem_live_normalize(roll))
    runs = [p for i, p in enumerate(ph) if i == 0 or ph[i - 1] != p]
    assert runs.count(Phase.HOLD) >= 2, f"expected two holds, saw {[p.value for p in runs]}"


# ── the band requirement, which is what makes a hold deliberate ──────────────


def test_mid_breath_hesitation_is_not_a_hold():
    """Pausing halfway up an inhale is a hesitation, not a hold."""
    random.seed(11)
    roll = []
    for _ in range(3):
        roll += ramp(0.0, ROLL_AMP, 2.0) + ramp(ROLL_AMP, 0.0, 2.0)
    roll += ramp(0.0, ROLL_AMP * 0.5, 1.0) + flat(ROLL_AMP * 0.5, 4.0)
    roll = [v + random.gauss(0, NOISE) for v in roll]
    ph = phases(totem_live_normalize(roll))
    assert Phase.HOLD not in tail_phase(ph, seconds=2.0), (
        "a pause at mid-range was treated as a hold"
    )


def test_hold_disabled_never_holds():
    cfg = make_detection(hold_enabled=False)
    ph = phases(totem_live_normalize(breath_then_long_hold(10.0)), cfg)
    assert Phase.HOLD not in set(ph)


def test_smooth_breathing_produces_no_holds():
    """A continuous sine never sits still in a band long enough."""
    random.seed(11)
    n = int(5.0 * SAMPLE_HZ * 5)
    roll = [
        ROLL_AMP * 0.5 * (1 - math.cos(2 * math.pi * i / (5.0 * SAMPLE_HZ)))
        + random.gauss(0, NOISE)
        for i in range(n)
    ]
    ph = phases(totem_live_normalize(roll))
    assert Phase.HOLD not in set(ph)
