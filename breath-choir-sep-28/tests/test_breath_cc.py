"""
Breath as a continuous controller.

The inhale and exhale sustain triggers are phase-gated: two dials that hand off
at the turnaround and go quiet during a hold. This one is not, so a single dial
follows the breath all the way round.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from breath_midi.triggers.base import TriggerContext
from breath_midi.triggers.v1.sustain_cc import BreathCcTrigger
from breath_midi.types import FeatureFrame, Phase, RollingStats, TriggerKind

from .test_hold_triggers import base_config


def ctx(**cc_overrides) -> TriggerContext:
    cfg = base_config()
    if cc_overrides:
        cfg = replace(cfg, cc=replace(cfg.cc, **cc_overrides))
    return TriggerContext(config=cfg)


def frame(t: float, amp: float, phase: Phase = Phase.INHALE) -> FeatureFrame:
    return FeatureFrame(
        t=t, amp=amp, d_amp=0.0, phase=phase,
        phase_changed=False, phase_entered=None,
        cycle_completed=False, cycle=None,
        rolling=RollingStats(avg_period_s=None, avg_peak_amp=None),
        source_id="test",
    )


def test_sends_a_cc_from_the_breath_amplitude():
    trig = BreathCcTrigger(cc_number=8)
    events = trig.on_frame(frame(0.0, 1.0), ctx())
    assert len(events) == 1
    assert events[0].kind == TriggerKind.CC
    assert events[0].meta["cc"] == 8
    assert events[0].value == 127


def test_zero_is_off():
    """Same sentinel as a silent note."""
    assert BreathCcTrigger(cc_number=0).on_frame(frame(0.0, 1.0), ctx()) == []


def test_fires_in_every_phase_including_a_hold():
    """The whole point: not phase-gated, so the dial never goes quiet."""
    for phase in (Phase.INHALE, Phase.EXHALE, Phase.HOLD, Phase.REST):
        trig = BreathCcTrigger(cc_number=8)
        assert trig.on_frame(frame(0.0, 0.5, phase), ctx()), phase


def test_a_still_breath_holds_the_dial_still():
    """A hold needs no special rule — the amplitude is not moving."""
    trig, c = BreathCcTrigger(cc_number=8), ctx()
    values = [
        trig.on_frame(frame(i * 0.5, 0.62, Phase.HOLD), c)[0].value
        for i in range(4)
    ]
    assert len(set(values)) == 1


def test_range_is_respected():
    # A context per call: the rate limiter keys its state on the strategy id
    # inside the context, so two triggers sharing one would throttle each other.
    # Each DeviceRuntime has its own context, so that cannot happen in the app.
    low = BreathCcTrigger(cc_number=8).on_frame(
        frame(0.0, 0.0), ctx(min_value=40, max_value=90)
    )
    high = BreathCcTrigger(cc_number=8).on_frame(
        frame(0.0, 1.0), ctx(min_value=40, max_value=90)
    )
    assert low[0].value == 40
    assert high[0].value == 90


def test_rate_limit_state_is_per_context():
    """Two devices must not throttle each other; each owns its context."""
    a, b = BreathCcTrigger(cc_number=8), BreathCcTrigger(cc_number=9)
    ctx_a, ctx_b = ctx(), ctx()
    assert a.on_frame(frame(0.0, 0.5), ctx_a)
    assert b.on_frame(frame(0.0, 0.5), ctx_b), "second device was rate limited"


def test_gamma_curve_bends_the_response():
    """Breath is perceptually non-linear; the curve is how you compensate."""
    linear = BreathCcTrigger(cc_number=8).on_frame(
        frame(0.0, 0.5), ctx(curve_kind="linear")
    )[0].value
    squashed = BreathCcTrigger(cc_number=8).on_frame(
        frame(0.0, 0.5), ctx(curve_kind="gamma", curve_gamma=2.0)
    )[0].value
    assert squashed < linear


def test_rate_limited_to_cc_rate_hz():
    """30Hz configured; a burst of frames must not flood the port."""
    trig, c = BreathCcTrigger(cc_number=8), ctx()
    fired = sum(
        1 for i in range(100) if trig.on_frame(frame(i * 0.001, 0.5), c)
    )
    assert fired < 10, f"sent {fired} messages in 0.1s"


def test_values_stay_inside_midi_range():
    trig, c = BreathCcTrigger(cc_number=8), ctx(min_value=0, max_value=127)
    for amp in (-0.5, 0.0, 0.5, 1.0, 1.5):
        events = trig.on_frame(frame(amp + 10.0, amp), c)
        if events:
            assert 0 <= events[0].value <= 127


def test_cc_number_can_be_changed_live():
    trig = BreathCcTrigger(cc_number=8)
    trig.set_cc(21)
    assert trig.cc_number == 21
    assert trig.on_frame(frame(0.0, 0.5), ctx())[0].meta["cc"] == 21


# ── through the hub ──────────────────────────────────────────────────────────


class SpySink:
    def __init__(self):
        self.cc = []
        self.notes = []

    def send_note_on(self, c, n, v):
        self.notes.append((c, n))

    def send_note_off(self, c, n, v=0):
        pass

    def send_cc(self, c, cc, val):
        self.cc.append((c, cc, val))

    def set_activity_source_id(self, s):
        pass

    def open(self, p=None):
        pass

    def close(self):
        pass

    def all_notes_off(self):
        pass


def breathing_hub(channel=3, breath_cc=74):
    import math

    from breath_midi.every_breath.hub import EveryBreathHub
    from breath_midi.types import BreathSample

    hub = EveryBreathHub(config=base_config(), osc_port=8819)
    sink = SpySink()
    hub._midi_sink = sink
    hub._on_new_device("phone-a")
    hub.set_midi_channel("phone-a", channel)
    hub.set_hold_number("phone-a", breath_cc)
    hub.set_cc_mode("phone-a", True)
    for i in range(250):
        amp = 0.5 - 0.45 * math.cos(2 * math.pi * i / 250)
        hub._on_sample(BreathSample(t=i * 0.02, amp=amp, source_id="phone-a"))
    return hub, sink


def test_cc_goes_out_on_the_devices_channel():
    """
    Notes routed per device and CC did not — the router reads cfg.midi.channel,
    which was the global one. A dial landing on the wrong Ableton track is the
    kind of thing you would chase for an hour.
    """
    _hub, sink = breathing_hub(channel=3)
    assert {c for c, _cc, _v in sink.cc} == {2}, "CC ignored the device channel"


def test_cc_mode_sends_no_notes():
    _hub, sink = breathing_hub()
    assert sink.notes == []


def test_the_breath_dial_sweeps_its_range():
    _hub, sink = breathing_hub(breath_cc=74)
    values = [v for _c, cc, v in sink.cc if cc == 74]
    assert max(values) - min(values) > 80, "the dial barely moved"
