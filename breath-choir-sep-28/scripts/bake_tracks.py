"""
Write the generated tracks.

The shapes are the ones already proven in tests/test_phase_fsm.py, and the cast
mirrors rose_breath/dummy_data.js — a deliberate spread: slow and deep, fast and
shallow, irregular, box breathing, and one performer who drops out to exercise
the device timeout.

The output is an ordinary track file.  Generated and recorded tracks load
through exactly one path, so there is no separate dummy-data mode to rot.

These are clean maths.  They will not reproduce the sensor noise that caused the
original inhale/exhale chatter, so they are good for exercising the feature and
useless for validating the detection dials.  Only a real recording does that.

Run:  .venv/bin/python -m scripts.bake_tracks
"""

from __future__ import annotations

import math
import random
from datetime import datetime
from pathlib import Path

from breath_midi.config.model import DetectionConfig
from breath_midi.tracks.file import Track, TrackDevice, write_track

HZ = 50.0
DT = 1.0 / HZ

# The shipped defaults, recorded as each track's provenance.
DEFAULT_DETECTION = DetectionConfig(
    derivative_enabled=True,
    derivative_smoothing_alpha=0.2,
    inhale_exit_delta=0.06,
    exhale_exit_delta=0.12,
    hold_exit_delta=0.15,
    hold_enabled=True,
    hold_still_tol=0.05,
    min_hold_ms=1500,
    hold_peak_band=0.80,
    hold_valley_band=0.20,
)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def gen_sine(period_s, seconds, lo=0.1, hi=0.9, jitter=0.0, seed=0) -> list[float]:
    """-cos, so the cycle starts at the bottom and rises: an inhale first."""
    rng = random.Random(seed)
    mid, half = (hi + lo) / 2.0, (hi - lo) / 2.0
    out = []
    for i in range(int(seconds * HZ)):
        v = mid - half * math.cos(2 * math.pi * i / (period_s * HZ))
        out.append(_clamp(v + (rng.gauss(0, jitter) if jitter else 0.0)))
    return out


def _smoothstep(x: float) -> float:
    x = _clamp(x)
    return x * x * (3.0 - 2.0 * x)


def _noise1d(seed: int):
    """
    Smooth value noise in 0..1, the way p5's noise() behaves.

    The point is *drift*, not hiss.  gen_sine adds a fresh Gaussian to every
    sample, which is what a noisy sensor looks like — it does not make a breath
    read as human.  What does is the rate and the depth wandering slowly from
    one cycle to the next, which is what this gives: a value that changes
    smoothly because neighbouring integers are interpolated rather than drawn
    independently.
    """
    rng = random.Random(seed)
    table = [rng.random() for _ in range(256)]

    def at(x: float) -> float:
        i = int(math.floor(x))
        f = x - i
        a, b = table[i % 256], table[(i + 1) % 256]
        return a + (b - a) * _smoothstep(f)

    return at


def gen_human(
    period_s: float,
    seconds: float,
    lo: float = 0.12,
    hi: float = 0.88,
    inhale_frac: float = 0.35,
    pause_frac: float = 0.12,
    period_jitter: float = 0.22,
    depth_jitter: float = 0.16,
    sigh_every: int = 0,
    sensor_noise: float = 0.004,
    seed: int = 0,
) -> list[float]:
    """
    A breath that reads as a person rather than an oscillator.

    Four things separate this from a sine, and all four come from watching real
    breathing rather than from making the maths prettier:

    * The rate wanders.  Nobody breathes on a metronome, and a fixed period is
      the single biggest tell.  period_jitter drifts it smoothly.
    * The depth wanders too, by its own slower noise, so some breaths are
      fuller than others without any of them looking like a mistake.
    * In and out are not equal.  At rest the exhale runs roughly twice the
      inhale, which is what inhale_frac sets.
    * There is a pause at the bottom.  Resting breathing rests after the
      exhale, not after the inhale, and that small flat patch at the valley is
      a large part of why a recording sounds alive.

    sigh_every adds a deeper breath every N cycles, which most people do
    without noticing.  sensor_noise is a touch of hiss on top — real phone data
    is never perfectly smooth, and the detector should not be tuned against
    something cleaner than it will ever see.
    """
    rate_noise = _noise1d(seed * 7919 + 1)
    depth_noise = _noise1d(seed * 7919 + 2)
    rng = random.Random(seed * 7919 + 3)

    out: list[float] = []
    t = 0.0
    cycle_index = 0
    n = int(seconds * HZ)

    while len(out) < n:
        # This cycle's length and depth, drifting slowly rather than jumping.
        drift = rate_noise(t * 0.06) - 0.5
        period = max(1.2, period_s * (1.0 + period_jitter * 2.0 * drift))
        depth = 1.0 + depth_jitter * 2.0 * (depth_noise(t * 0.05) - 0.5)
        if sigh_every and cycle_index % sigh_every == sigh_every - 1:
            depth *= 1.35                      # the breath you take without noticing

        span = (hi - lo) * min(1.0, depth)
        top = _clamp(lo + span)

        steps = max(2, int(period * HZ))
        rise = max(1, int(steps * inhale_frac))
        pause = max(0, int(steps * pause_frac))
        fall = max(1, steps - rise - pause)

        for i in range(steps):
            if len(out) >= n:
                break
            if i < rise:
                shaped = _smoothstep(i / rise)
            elif i < rise + fall:
                shaped = 1.0 - _smoothstep((i - rise) / fall)
            else:
                shaped = 0.0                   # the rest after the exhale
            v = lo + (top - lo) * shaped
            if sensor_noise:
                v += rng.gauss(0.0, sensor_noise)
            out.append(_clamp(v))

        t += period
        cycle_index += 1

    return out[:n]


def gen_box(inhale_s, hold_s, cycles, lo=0.05, hi=0.9) -> list[float]:
    """Inhale, hold full, exhale, hold empty."""
    def ramp(a, b, secs):
        n = max(1, int(secs * HZ))
        return [_clamp(a + (b - a) * (i / n)) for i in range(n)]

    def flat(v, secs):
        return [_clamp(v)] * max(1, int(secs * HZ))

    out: list[float] = []
    for _ in range(cycles):
        out += ramp(lo, hi, inhale_s) + flat(hi, hold_s)
        out += ramp(hi, lo, inhale_s) + flat(lo, hold_s)
    return out


def gen_speech(inhale_s, exhale_s, seconds, lo=0.25, hi=0.75) -> list[float]:
    """A quick rise and a long fall: the breath people take while talking."""
    cycle = inhale_s + exhale_s
    out = []
    for i in range(int(seconds * HZ)):
        phase = (i * DT) % cycle
        if phase < inhale_s:
            v = lo + (hi - lo) * (phase / inhale_s)
        else:
            v = hi - (hi - lo) * ((phase - inhale_s) / exhale_s)
        out.append(_clamp(v))
    return out


def gen_sigh(period_s, seconds, lo, hi, every=4, sigh_hi=0.95, seed=0) -> list[float]:
    """Ordinary cycles, with one deeper breath every `every` cycles."""
    base = gen_sine(period_s, seconds, lo, hi, seed=seed)
    span = hi - lo
    per = max(1, int(period_s * HZ))
    out = []
    for i, v in enumerate(base):
        if (i // per) % every == every - 1 and span > 0:
            out.append(_clamp(lo + (sigh_hi - lo) * ((v - lo) / span)))
        else:
            out.append(v)
    return out


def _dev(
    uuid, name, color, inhale=54, exhale=55, channel=1, *,
    breath_cc=74, cc_mode=False,
) -> TrackDevice:
    return TrackDevice(
        uuid, name, color, inhale, exhale, channel,
        breath_cc=breath_cc, cc_mode=cc_mode,
    )


def _numbered(devices: list[TrackDevice]) -> list[TrackDevice]:
    """
    First device on channel 1, each one after it a channel higher.

    Numbered within the track, not globally, so a track always behaves the same
    however many are loaded.  Load two at once and their channels overlap — that
    is the cost of tracks being self-contained, and the Ch field is there to
    move one out of the way.
    """
    from dataclasses import replace

    return [
        replace(d, midi_channel=min(16, i + 1)) for i, d in enumerate(devices)
    ]


def _track(name, devices, series) -> Track:
    """`series` is one amplitude list per device, index-aligned with `devices`."""
    samples: list[tuple[float, int, float]] = []
    for i, amps in enumerate(series):
        for n, amp in enumerate(amps):
            samples.append((n * DT, i, amp))
    # Interleave by time the way real arrivals would, and satisfy the
    # non-decreasing rule read_track enforces.
    samples.sort(key=lambda s: (s[0], s[1]))
    duration = max((len(a) for a in series), default=0) * DT
    return Track(
        name=name,
        created=datetime.now().isoformat(timespec="seconds"),
        duration_s=duration,
        source="generated",
        detection=DEFAULT_DETECTION,
        devices=devices,
        samples=samples,
    )


def bake_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    solos = [
        ("slow-and-deep", "Slow & Deep",
         _dev("slow", "Slow & Deep", (120, 170, 230)),
         gen_sine(10.0, 120, 0.10, 0.95, seed=0)),
        ("fast-and-shallow", "Fast & Shallow",
         _dev("fast", "Fast & Shallow", (230, 150, 90)),
         gen_sine(2.5, 120, 0.10, 0.45, seed=1)),
        ("irregular", "Irregular",
         _dev("irr", "Irregular", (200, 110, 180)),
         gen_sine(5.0, 120, 0.10, 0.80, jitter=0.02, seed=2)),
        ("box-breathing", "Box Breathing",
         _dev("box", "Box Breathing", (120, 210, 150)),
         gen_box(4.0, 4.0, cycles=8)),
    ]
    for fname, title, device, amps in solos:
        path = out_dir / f"{fname}.breath.json"
        write_track(path, _track(title, _numbered([device]), [amps]))
        written.append(path)

    # One performer stops early.  The gap is longer than the hub's 5s device
    # timeout, so loading this exercises the fade-out and the note release.
    path = out_dir / "dropout.breath.json"
    write_track(path, _track(
        "Dropout",
        _numbered([_dev("stayer", "Stayer", (150, 200, 120)),
                   _dev("leaver", "Leaver", (220, 120, 120), 56, 57)]),
        [gen_sine(5.0, 60, seed=3), gen_sine(5.0, 25, seed=4)],
    ))
    written.append(path)

    # A full group, for checking the panel and MIDI with several at once.
    path = out_dir / "group-of-four.breath.json"
    write_track(path, _track(
        "Group of four",
        _numbered([
            _dev("g1", "Ana", (220, 120, 90), 54, 55, breath_cc=70, cc_mode=True),
            _dev("g2", "Bo", (90, 160, 220), 56, 57, breath_cc=71, cc_mode=True),
            _dev("g3", "Cy", (200, 200, 110), 58, 59, breath_cc=72, cc_mode=True),
            _dev("g4", "Di", (150, 120, 220), 60, 61, breath_cc=73, cc_mode=True),
        ]),
        [gen_sine(5.0, 90, seed=5),
         gen_sine(6.0, 90, seed=6),
         gen_sine(4.5, 90, jitter=0.015, seed=7),
         gen_box(3.0, 2.0, cycles=12)],
    ))
    written.append(path)

    # Four ordinary ways of breathing, as opposed to the stylised group above.
    # Rest is tidal, Talk is a short inhale and a long exhale, Sigh deepens
    # every fourth cycle, Sleep is slower and shallower. Controllers 74–77 sit
    # just above the group of four, so both tracks can be loaded together.
    path = out_dir / "everyday-four.breath.json"
    write_track(path, _track(
        "Everyday four",
        _numbered([
            _dev("rest", "Rest", (140, 180, 160), 54, 55, breath_cc=74, cc_mode=True),
            _dev("talk", "Talk", (180, 150, 110), 56, 57, breath_cc=75, cc_mode=True),
            _dev("sigh", "Sigh", (170, 140, 180), 58, 59, breath_cc=76, cc_mode=True),
            _dev("sleep", "Sleep", (120, 150, 190), 60, 61, breath_cc=77, cc_mode=True),
        ]),
        [gen_sine(4.0, 90, 0.30, 0.70, seed=8),
         gen_speech(1.0, 3.0, 90, 0.28, 0.72),
         gen_sigh(4.5, 90, 0.28, 0.62, every=4, sigh_hi=0.95, seed=9),
         gen_sine(6.5, 90, 0.38, 0.62, jitter=0.004, seed=10)],
    ))
    written.append(path)

    # Four people breathing, rather than four oscillators.  This is the one to
    # tune detection against: every cycle differs in length and depth, the
    # exhale runs longer than the inhale, there is a rest at the bottom, and
    # there is enough sensor hiss that the dials are not being set against
    # something cleaner than a phone will ever send.
    path = out_dir / "four-breathing.breath.json"
    write_track(path, _track(
        "Four breathing",
        # CC mode by default: this track exists to be breathed into a dial, and
        # 70-73 leaves everyday-four's 74-77 free so both can be loaded at once
        # without two performers fighting over one controller.
        _numbered([
            _dev("b1", "Mara", (220, 120, 90), 54, 55, breath_cc=70, cc_mode=True),
            _dev("b2", "Ivo", (90, 160, 220), 56, 57, breath_cc=71, cc_mode=True),
            _dev("b3", "Nadia", (200, 200, 110), 58, 59, breath_cc=72, cc_mode=True),
            _dev("b4", "Tomas", (150, 120, 220), 60, 61, breath_cc=73, cc_mode=True),
        ]),
        [
            # Slow and settled, the way someone breathes once they have stopped
            # thinking about it.
            gen_human(6.4, 120, lo=0.10, hi=0.90, inhale_frac=0.34,
                      pause_frac=0.14, period_jitter=0.16, seed=11),
            # Quicker and shallower — nervous, or simply a smaller breath.
            gen_human(3.6, 120, lo=0.18, hi=0.62, inhale_frac=0.40,
                      pause_frac=0.08, period_jitter=0.26, seed=12),
            # Irregular: the rate wanders a long way, which is what the
            # consistency gate exists to notice.
            gen_human(5.0, 120, lo=0.12, hi=0.82, inhale_frac=0.32,
                      pause_frac=0.12, period_jitter=0.45, depth_jitter=0.30,
                      seed=13),
            # A deeper breath every fourth cycle, which most people do without
            # noticing they are doing it.
            gen_human(5.4, 120, lo=0.14, hi=0.80, inhale_frac=0.30,
                      pause_frac=0.16, period_jitter=0.20, sigh_every=4,
                      seed=14),
        ],
    ))
    written.append(path)

    return written


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    for p in bake_all(root / "tracks" / "generated"):
        print(f"wrote {p.relative_to(root)}")
