"""
Whole-chain tests: signal → FSM → MIDI, against a fake sink.

This module also owns `base_config()`, the ConfigModel other test modules build
on. Gate semantics (one note at a time, releases) live in test_voice_gate.py;
what is checked here is that the chain end to end produces the right notes for
the right phases.
"""

from __future__ import annotations

from breath_midi.config.model import (
    ConfigModel,
    ConsistentBreathsTriggerConfig,
    ExhaleOnsetTriggerConfig,
    HoldOnsetTriggerConfig,
    InhaleOnsetTriggerConfig,
    InputConfig,
    MidiConfig,
    SignalConfig,
    SustainTriggerConfig,
    TriggersConfig,
    UiConfig,
)
from breath_midi.every_breath.device_runtime import DeviceRuntime, make_device_config
from breath_midi.midi.voice import SILENT
from breath_midi.types import BreathSample

from .test_phase_fsm import DT, box, make_detection

INHALE_NOTE, EXHALE_NOTE = 54, 55
HOLD_NOTE = 70


class FakeSink:
    """Records everything sent, standing in for MidoMidiSink."""

    def __init__(self) -> None:
        self.notes: list[tuple[int, int, int]] = []
        self.offs: list[tuple[int, int]] = []
        self.ccs: list[tuple[int, int, int]] = []

    def send_note_on(self, channel: int, note: int, velocity: int) -> None:
        self.notes.append((channel, note, velocity))

    def send_note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        self.offs.append((channel, note))

    def send_cc(self, channel: int, cc: int, value: int) -> None:
        self.ccs.append((channel, cc, value))


def base_config() -> ConfigModel:
    velocity = 100
    return ConfigModel(
        version=1,
        controller_id="test",
        input=InputConfig(
            mode="osc", osc_port=8001, source_filter="all",
            ble_address="", ble_auto_connect=False,
        ),
        signal=SignalConfig(
            smoothing_kind="ema", smoothing_alpha=1.0, baseline_enabled=False,
            baseline_alpha=0.01, gain=1.0, deadzone=0.0,
        ),
        detection=make_detection(),
        midi=MidiConfig(out_port="", channel=0, default_velocity=velocity, cc_rate_hz=30),
        triggers=TriggersConfig(
            inhale_onset=InhaleOnsetTriggerConfig(True, INHALE_NOTE, velocity, 200),
            exhale_onset=ExhaleOnsetTriggerConfig(True, EXHALE_NOTE, velocity, 200),
            inhale_sustain=SustainTriggerConfig(False, 1, 0, 127, "gamma", 1.0),
            exhale_sustain=SustainTriggerConfig(False, 2, 0, 127, "gamma", 1.0),
            consistent_breaths=ConsistentBreathsTriggerConfig(
                False, 3, 3, "relative", 0.3, "absolute", 0.3, 64, velocity
            ),
            hold_onset=HoldOnsetTriggerConfig(True, HOLD_NOTE, velocity, 200),
        ),
        ui=UiConfig(),
    )


def drive(runtime: DeviceRuntime, samples: list[float]) -> None:
    for i, amp in enumerate(samples):
        runtime.on_sample(BreathSample(t=i * DT, amp=amp, source_id="test"))


def run_box(hold_note: int = HOLD_NOTE, cc_mode: bool = False) -> FakeSink:
    cfg = make_device_config(base_config(), INHALE_NOTE, EXHALE_NOTE, hold_note=hold_note)
    sink = FakeSink()
    runtime = DeviceRuntime(cfg, sink)  # type: ignore[arg-type]
    runtime.set_cons_n(0)  # bypass the consistency gate
    if cc_mode:
        runtime.set_output_mode(True)
        runtime.set_hold_cc(hold_note)
    drive(runtime, box(inhale_s=2.0, hold_s=2.0, cycles=3))
    return sink


def test_all_three_phases_reach_midi():
    played = {n for _, n, _ in run_box().notes}
    assert played == {INHALE_NOTE, EXHALE_NOTE, HOLD_NOTE}


def test_silent_hold_plays_only_inhale_and_exhale():
    """The default. The hold still happens; it just sounds nothing."""
    played = {n for _, n, _ in run_box(hold_note=SILENT).notes}
    assert played == {INHALE_NOTE, EXHALE_NOTE}


def test_every_note_on_is_matched_by_a_note_off():
    """Gate discipline: nothing may be left ringing at the end of a take."""
    sink = run_box()
    ons = [n for _, n, _ in sink.notes]
    offs = [n for _, n in sink.offs]
    # The last note may still be held when the take ends; everything else is paired.
    assert len(offs) >= len(ons) - 1
    for note in set(ons):
        assert offs.count(note) >= ons.count(note) - 1


def test_notes_follow_the_breath_cycle():
    """
    Box breathing visits the hold twice per cycle, top and bottom, and both are
    the same note. The first cycle has no holds at all — holds are suppressed
    until one full cycle has established the performer's range.
    """
    seq = [n for _, n, _ in run_box().notes]
    first_hold = seq.index(HOLD_NOTE)
    assert seq[first_hold - 1] == INHALE_NOTE, "a peak hold follows an inhale"
    assert seq[first_hold : first_hold + 3] == [HOLD_NOTE, EXHALE_NOTE, HOLD_NOTE]


def test_hold_is_one_press_not_a_stream():
    """A held key is pressed once, however long it is held."""
    seq = [n for _, n, _ in run_box().notes]
    repeats = [i for i in range(1, len(seq)) if seq[i] == seq[i - 1] == HOLD_NOTE]
    assert not repeats, f"hold re-pressed without an intervening phase at {repeats}"


def test_cc_mode_sends_cc_not_notes():
    sink = run_box(cc_mode=True)
    assert not sink.notes, "CC mode must not send notes"
    assert HOLD_NOTE in {cc for _, cc, _ in sink.ccs}
