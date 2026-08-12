"""
Breath FSM tests: inhale, hold, exhale.

These drive FeatureExtractor with synthetic breath signals rather than a
phone, so the cycle can be verified without hardware.  The waveform generators mirror the shapes in
stop-and-let-the-rose-smell-v2/rose_breath/dummy_data.js so that the app-level
dummy-data mode, when it lands, exercises the same cases.
"""

from __future__ import annotations

import math

import pytest

from breath_midi.config.model import DetectionConfig
from breath_midi.signal.features import FeatureExtractor
from breath_midi.types import Phase, ProcessedSample

SAMPLE_HZ = 50.0
DT = 1.0 / SAMPLE_HZ


def make_detection(**overrides) -> DetectionConfig:
    """Detection config matching breath-choir-aug-13/config.toml defaults."""
    base = dict(
        derivative_enabled=True,
        derivative_smoothing_alpha=0.2,
        inhale_enter_amp=0.08,
        exhale_enter_amp=0.08,
        rest_enter_amp=0.04,
        slope_enter_abs=0.08,
        slope_rest_abs=0.015,
        hysteresis=0.02,
        min_phase_ms=120,
        hold_enabled=True,
        min_hold_ms=1000,
        hold_peak_band=0.80,
        hold_valley_band=0.20,
        hold_still_tol=0.05,
        hold_exit_delta=0.15,
    )
    base.update(overrides)
    return DetectionConfig(**base)


def run(samples: list[float], cfg: DetectionConfig | None = None) -> list[Phase]:
    """Feed an amplitude series through the extractor, return the phase per sample."""
    fx = FeatureExtractor(cfg or make_detection())
    out: list[Phase] = []
    for i, amp in enumerate(samples):
        frame = fx.update(
            ProcessedSample(t=i * DT, amp_raw=amp, amp_proc=amp, source_id="test")
        )
        out.append(frame.phase)
    return out


def phase_order(phases: list[Phase]) -> list[Phase]:
    """Collapse a per-sample phase series into the sequence of distinct phases."""
    seq: list[Phase] = []
    for p in phases:
        if not seq or seq[-1] != p:
            seq.append(p)
    return seq


# ── waveform generators ───────────────────────────────────────────────────────


def ramp(start: float, end: float, seconds: float) -> list[float]:
    n = max(1, int(seconds * SAMPLE_HZ))
    return [start + (end - start) * (i / n) for i in range(n)]


def flat(level: float, seconds: float) -> list[float]:
    return [level] * max(1, int(seconds * SAMPLE_HZ))


def sine(period_s: float, cycles: int, lo: float = 0.1, hi: float = 0.9) -> list[float]:
    n = int(period_s * SAMPLE_HZ * cycles)
    mid, half = (hi + lo) / 2.0, (hi - lo) / 2.0
    # -cos so the cycle starts at the bottom and rises (an inhale first)
    return [mid - half * math.cos(2 * math.pi * i / (period_s * SAMPLE_HZ)) for i in range(n)]


def box(inhale_s: float, hold_s: float, cycles: int, lo: float = 0.05, hi: float = 0.9) -> list[float]:
    """Box breathing: inhale, hold full, exhale, hold empty — the 'box' dummy shape."""
    out: list[float] = []
    for _ in range(cycles):
        out += ramp(lo, hi, inhale_s)
        out += flat(hi, hold_s)
        out += ramp(hi, lo, inhale_s)
        out += flat(lo, hold_s)
    return out


# ── tests ─────────────────────────────────────────────────────────────────────


def test_box_breathing_produces_all_three_phases():
    phases = run(box(inhale_s=2.0, hold_s=2.0, cycles=4))
    seen = set(phases)
    assert Phase.INHALE in seen
    assert Phase.EXHALE in seen
    assert Phase.HOLD in seen, "a held breath was not detected"


def test_box_breathing_cycles_in_order():
    """
    Inhale, hold, exhale, hold — the cycle visits HOLD twice, and both are the
    same state. Holds are suppressed until one full cycle has been seen, so the
    ordering is checked from the first hold onward.
    """
    phases = run(box(inhale_s=2.0, hold_s=2.0, cycles=4))
    seq = [p for p in phase_order(phases) if p != Phase.REST]
    start = seq.index(Phase.HOLD)
    assert seq[start : start + 4] == [Phase.HOLD, Phase.EXHALE, Phase.HOLD, Phase.INHALE]


def test_hold_requires_sustained_stillness():
    """A brief flat spot at the top of a breath must NOT register as a hold."""
    # 200ms of flat — well under the 1000ms min_hold_ms threshold.
    phases = run(box(inhale_s=2.0, hold_s=0.2, cycles=4))
    assert Phase.HOLD not in set(phases), "a 200ms flat spot was misread as a hold"


def test_hold_detected_just_past_threshold():
    """Stillness longer than min_hold_ms does register."""
    phases = run(box(inhale_s=2.0, hold_s=1.4, cycles=4))
    assert Phase.HOLD in set(phases)


def test_smooth_sine_never_holds():
    """Continuous breathing has no sustained flat region — no holds at all."""
    phases = run(sine(period_s=5.0, cycles=4))
    assert Phase.HOLD not in set(phases)
    assert Phase.INHALE in set(phases)
    assert Phase.EXHALE in set(phases)


def test_min_hold_ms_is_the_knob_for_slow_breathers():
    """
    The unavoidable trade-off, recorded rather than wished away.

    A very slow breath is genuinely near-stationary at its turnaround, so at the
    default 1000ms dwell the 'Slow & Deep' performer (10s period) trips a hold.
    That is not a bug in the detector — over a 1s window the breath really has
    moved less than hold_still_tol. Raising min_hold_ms past the turnaround
    fixes it, which is exactly what the knob is for.
    """
    slow = sine(period_s=10.0, cycles=3)
    assert Phase.HOLD in set(run(slow)), "default dwell no longer catches slow breathing"
    assert Phase.HOLD not in set(run(slow, make_detection(min_hold_ms=1600))), (
        "raising min_hold_ms should stop slow breathing registering as a hold"
    )
    # A normal 5s breath is unaffected either way.
    assert Phase.HOLD not in set(run(sine(period_s=5.0, cycles=4)))


def test_hold_disabled_falls_back_to_two_phase():
    """With hold_enabled=False the FSM behaves as it did before hold support."""
    cfg = make_detection(hold_enabled=False)
    phases = run(box(inhale_s=2.0, hold_s=2.0, cycles=4), cfg)
    assert Phase.HOLD not in set(phases)
    assert Phase.INHALE in set(phases)
    assert Phase.EXHALE in set(phases)


def test_starts_in_rest_and_never_returns():
    """REST is the cold-start state only — once breathing starts it is gone."""
    phases = run(box(inhale_s=2.0, hold_s=2.0, cycles=3))
    assert phases[0] == Phase.REST
    first_breath = next(i for i, p in enumerate(phases) if p != Phase.REST)
    assert Phase.REST not in set(phases[first_breath:])


def test_hold_exits_on_exhale():
    """A hold must release into an exhale when the performer breathes out."""
    samples = (
        box(inhale_s=2.0, hold_s=2.0, cycles=2)
        + ramp(0.05, 0.9, 2.0)
        + flat(0.9, 2.0)
        + ramp(0.9, 0.05, 2.0)
    )
    phases = run(samples)
    assert phases[-1] == Phase.EXHALE


def test_cycle_metrics_still_complete_across_holds():
    """Cycle period is measured on inhale onset; holds must not break it."""
    fx = FeatureExtractor(make_detection())
    completed = 0
    samples = box(inhale_s=2.0, hold_s=2.0, cycles=5)
    for i, amp in enumerate(samples):
        frame = fx.update(
            ProcessedSample(t=i * DT, amp_raw=amp, amp_proc=amp, source_id="test")
        )
        if frame.cycle_completed:
            completed += 1
            assert frame.cycle is not None
            # 2s inhale + 2s hold + 2s exhale + 2s hold = 8s
            assert 6.0 < frame.cycle.period_s < 10.0
    assert completed >= 2, "no breath cycles completed"


@pytest.mark.parametrize("hold_s", [1.5, 2.0, 3.0])
def test_hold_detected_across_hold_lengths(hold_s: float):
    phases = run(box(inhale_s=2.0, hold_s=hold_s, cycles=4))
    assert Phase.HOLD in set(phases)
