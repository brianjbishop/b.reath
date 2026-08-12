"""
Hold trigger tests: the FSM's hold phases must reach MIDI.

These run a DeviceRuntime against a fake MidiSink, so they cover the whole
signal → FSM → trigger → router → MIDI chain without a phone or a MIDI port.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

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
from breath_midi.types import BreathSample

from .test_phase_fsm import DT, box, make_detection

INHALE_NOTE, EXHALE_NOTE = 54, 58
HOLD_FULL_NOTE, HOLD_EMPTY_NOTE = 66, 70


class FakeSink:
    """Records everything sent, standing in for MidoMidiSink."""

    def __init__(self) -> None:
        self.notes: list[tuple[int, int, int]] = []
        self.ccs: list[tuple[int, int, int]] = []

    def send_note_on(self, channel: int, note: int, velocity: int) -> None:
        self.notes.append((channel, note, velocity))

    def send_note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        pass

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
            hold_full_onset=HoldOnsetTriggerConfig(False, HOLD_FULL_NOTE, velocity, 200),
            hold_empty_onset=HoldOnsetTriggerConfig(False, HOLD_EMPTY_NOTE, velocity, 200),
        ),
        ui=UiConfig(),
    )


def drive(runtime: DeviceRuntime, samples: list[float]) -> None:
    for i, amp in enumerate(samples):
        runtime.on_sample(BreathSample(t=i * DT, amp=amp, source_id="test"))


def run_box(*, holds_enabled: bool, cc_mode: bool = False) -> FakeSink:
    cfg = make_device_config(
        base_config(),
        INHALE_NOTE,
        EXHALE_NOTE,
        hold_full_note=HOLD_FULL_NOTE,
        hold_empty_note=HOLD_EMPTY_NOTE,
        hold_full_enabled=holds_enabled,
        hold_empty_enabled=holds_enabled,
    )
    sink = FakeSink()
    runtime = DeviceRuntime(cfg, sink)  # type: ignore[arg-type]
    runtime.set_cons_n(0)  # bypass the consistency gate
    if cc_mode:
        runtime.set_output_mode(True)
        runtime.set_hold_full_cc(HOLD_FULL_NOTE)
        runtime.set_hold_empty_cc(HOLD_EMPTY_NOTE)
    drive(runtime, box(inhale_s=2.0, hold_s=2.0, cycles=3))
    return sink


def test_holds_disabled_emits_only_inhale_and_exhale():
    """The default: existing output is bit-for-bit unchanged by hold support."""
    sink = run_box(holds_enabled=False)
    played = {n for _, n, _ in sink.notes}
    assert played == {INHALE_NOTE, EXHALE_NOTE}
    assert HOLD_FULL_NOTE not in played
    assert HOLD_EMPTY_NOTE not in played


def test_holds_enabled_emits_all_four_notes():
    sink = run_box(holds_enabled=True)
    played = {n for _, n, _ in sink.notes}
    assert played == {INHALE_NOTE, EXHALE_NOTE, HOLD_FULL_NOTE, HOLD_EMPTY_NOTE}


def test_hold_notes_fire_once_per_cycle():
    """A hold is one event on entry, not a stream while the breath is held."""
    sink = run_box(holds_enabled=True)
    hold_full_hits = [n for _, n, _ in sink.notes if n == HOLD_FULL_NOTE]
    # 3 cycles of box breathing — one hold-full note each.
    assert len(hold_full_hits) == 3


def test_note_order_walks_the_cycle():
    sink = run_box(holds_enabled=True)
    seq = [n for _, n, _ in sink.notes]
    first = seq.index(INHALE_NOTE)
    assert seq[first : first + 4] == [
        INHALE_NOTE,
        HOLD_FULL_NOTE,
        EXHALE_NOTE,
        HOLD_EMPTY_NOTE,
    ]


def test_cc_mode_sends_hold_ccs():
    sink = run_box(holds_enabled=True, cc_mode=True)
    assert not sink.notes, "CC mode must not send notes"
    cc_numbers = {cc for _, cc, _ in sink.ccs}
    assert HOLD_FULL_NOTE in cc_numbers
    assert HOLD_EMPTY_NOTE in cc_numbers


def test_muted_device_emits_nothing():
    cfg = make_device_config(
        base_config(), INHALE_NOTE, EXHALE_NOTE,
        hold_full_note=HOLD_FULL_NOTE, hold_empty_note=HOLD_EMPTY_NOTE,
        hold_full_enabled=True, hold_empty_enabled=True,
    )
    sink = FakeSink()
    runtime = DeviceRuntime(cfg, sink)  # type: ignore[arg-type]
    runtime.set_cons_n(0)
    for i, amp in enumerate(box(inhale_s=2.0, hold_s=2.0, cycles=3)):
        runtime.on_sample(BreathSample(t=i * DT, amp=amp, source_id="test"), muted=True)
    assert not sink.notes


@pytest.mark.parametrize("enabled", [True, False])
def test_set_hold_enabled_toggles_at_runtime(enabled: bool):
    cfg = make_device_config(
        base_config(), INHALE_NOTE, EXHALE_NOTE,
        hold_full_note=HOLD_FULL_NOTE, hold_empty_note=HOLD_EMPTY_NOTE,
        hold_full_enabled=not enabled, hold_empty_enabled=not enabled,
    )
    sink = FakeSink()
    runtime = DeviceRuntime(cfg, sink)  # type: ignore[arg-type]
    runtime.set_cons_n(0)
    runtime.set_hold_enabled(enabled, enabled)
    drive(runtime, box(inhale_s=2.0, hold_s=2.0, cycles=3))
    played = {n for _, n, _ in sink.notes}
    assert (HOLD_FULL_NOTE in played) is enabled
