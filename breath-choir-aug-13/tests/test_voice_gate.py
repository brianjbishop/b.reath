"""
One key down at a time, and never a stuck one.

The invariant these defend: at any instant a device has at most one note
sounding, and every way a phase can end releases it. A stuck note in a live set
means a tone that will not stop until someone kills the port.

`Recorder` tracks the note stack the way a synth would, so "two notes at once"
and "note left ringing" are both directly observable rather than inferred.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from breath_midi.every_breath.device_runtime import DeviceRuntime, make_device_config
from breath_midi.midi.voice import SILENT, BreathVoice
from breath_midi.types import BreathSample, Phase

from .test_hold_triggers import base_config

INHALE, EXHALE, HOLD = 54, 55, 70


class Recorder:
    """A fake sink that models what a synth would actually be sounding."""

    def __init__(self) -> None:
        self.down: set[int] = set()
        self.events: list[tuple[str, int]] = []
        self.max_simultaneous = 0
        self.double_on: list[int] = []

    def send_note_on(self, channel: int, note: int, velocity: int) -> None:
        if note in self.down:
            self.double_on.append(note)
        self.down.add(note)
        self.events.append(("on", note))
        self.max_simultaneous = max(self.max_simultaneous, len(self.down))

    def send_note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        self.down.discard(note)
        self.events.append(("off", note))

    def send_cc(self, channel: int, cc: int, value: int) -> None:
        self.events.append(("cc", cc))


@pytest.fixture
def voice() -> tuple[BreathVoice, Recorder]:
    rec = Recorder()
    v = BreathVoice(rec, channel=0, velocity=100)  # type: ignore[arg-type]
    v.set_notes(inhale=INHALE, hold=HOLD, exhale=EXHALE)
    return v, rec


# ── the invariant ────────────────────────────────────────────────────────────


def test_only_one_note_sounds_at_a_time(voice):
    v, rec = voice
    for phase in [Phase.INHALE, Phase.HOLD, Phase.EXHALE, Phase.HOLD] * 5:
        v.on_phase(phase)
        assert len(rec.down) <= 1, f"{len(rec.down)} notes down at once: {rec.down}"
    assert rec.max_simultaneous == 1


def test_release_precedes_press(voice):
    """Off must come before on, or a shared note number would be silenced."""
    v, rec = voice
    v.on_phase(Phase.INHALE)
    rec.events.clear()
    v.on_phase(Phase.EXHALE)
    assert rec.events == [("off", INHALE), ("on", EXHALE)]


def test_shared_note_number_retriggers(voice):
    """Two phases on the same note should retrigger, not fall silent."""
    v, rec = voice
    v.set_notes(inhale=60, hold=60, exhale=61)
    v.on_phase(Phase.INHALE)
    rec.events.clear()
    v.on_phase(Phase.HOLD)
    # Same pitch: it must be released and pressed again, and still sounding.
    assert rec.events == [("off", 60), ("on", 60)]
    assert rec.down == {60}


def test_no_double_note_on_ever(voice):
    v, rec = voice
    for phase in [Phase.INHALE, Phase.INHALE, Phase.HOLD, Phase.HOLD, Phase.EXHALE] * 4:
        v.on_phase(phase)
    assert rec.double_on == []


def test_repeating_the_same_phase_does_not_retrigger(voice):
    """Held key, not a machine gun — the note is pressed once."""
    v, rec = voice
    for _ in range(50):
        v.on_phase(Phase.INHALE)
    assert rec.events == [("on", INHALE)]


# ── note 0 means silent ──────────────────────────────────────────────────────


def test_hold_of_zero_releases_and_sounds_nothing(voice):
    v, rec = voice
    v.set_notes(inhale=INHALE, hold=SILENT, exhale=EXHALE)
    v.on_phase(Phase.INHALE)
    assert rec.down == {INHALE}
    v.on_phase(Phase.HOLD)
    assert rec.down == set(), "hold with note 0 must leave nothing sounding"
    v.on_phase(Phase.EXHALE)
    assert rec.down == {EXHALE}


def test_all_zero_never_sounds(voice):
    v, rec = voice
    v.set_notes(inhale=SILENT, hold=SILENT, exhale=SILENT)
    for phase in [Phase.INHALE, Phase.HOLD, Phase.EXHALE]:
        v.on_phase(phase)
    assert rec.events == []


# ── nothing may be left ringing ──────────────────────────────────────────────


def test_release_clears_the_sounding_note(voice):
    v, rec = voice
    v.on_phase(Phase.INHALE)
    v.release()
    assert rec.down == set()
    assert v.sounding_note is None


def test_release_is_idempotent(voice):
    v, rec = voice
    v.on_phase(Phase.INHALE)
    v.release()
    rec.events.clear()
    v.release()
    v.release()
    assert rec.events == []


def test_mute_releases_immediately(voice):
    v, rec = voice
    v.on_phase(Phase.INHALE)
    v.set_muted(True)
    assert rec.down == set(), "muting must not leave a note ringing"
    v.on_phase(Phase.EXHALE)
    assert rec.down == set(), "a muted device must stay silent"
    v.set_muted(False)
    v.on_phase(Phase.EXHALE)
    assert rec.down == {EXHALE}


def test_release_survives_a_dead_sink():
    """A closed port must not leave the voice thinking a note is still down."""

    class DeadSink:
        def send_note_on(self, *a):
            pass

        def send_note_off(self, *a):
            raise OSError("port closed")

        def send_cc(self, *a):
            pass

    v = BreathVoice(DeadSink(), channel=0)  # type: ignore[arg-type]
    v.set_notes(inhale=INHALE, hold=HOLD, exhale=EXHALE)
    v.on_phase(Phase.INHALE)
    v.release()
    assert v.sounding_note is None


# ── through the real DeviceRuntime ───────────────────────────────────────────


def runtime_with(rec: Recorder, hold_note: int = HOLD) -> DeviceRuntime:
    cfg = make_device_config(base_config(), INHALE, EXHALE, hold_note=hold_note)
    rt = DeviceRuntime(cfg, rec)  # type: ignore[arg-type]
    rt.set_cons_n(0)
    return rt


def drive(rt: DeviceRuntime, amps: list[float], muted: bool = False) -> None:
    for i, a in enumerate(amps):
        rt.on_sample(BreathSample(t=i / 50.0, amp=a, source_id="p"), muted=muted)


def test_runtime_never_sounds_two_notes():
    from .test_phase_fsm import box

    rec = Recorder()
    rt = runtime_with(rec)
    drive(rt, box(inhale_s=2.0, hold_s=2.0, cycles=4))
    assert rec.max_simultaneous <= 1
    assert rec.double_on == []


def test_runtime_release_stops_the_note():
    from .test_phase_fsm import ramp

    rec = Recorder()
    rt = runtime_with(rec)
    drive(rt, ramp(0.05, 0.9, 2.0))
    rt.release()
    assert rec.down == set()


def test_muted_runtime_releases_mid_phase():
    """Mute arriving mid-inhale must drop the note on the next sample."""
    from .test_phase_fsm import ramp

    rec = Recorder()
    rt = runtime_with(rec)
    rising = ramp(0.05, 0.9, 2.0)
    drive(rt, rising[: len(rising) // 2])
    sounding_before = set(rec.down)
    drive(rt, rising[len(rising) // 2 :], muted=True)
    assert sounding_before, "expected a note to be sounding before the mute"
    assert rec.down == set(), "mute did not release the held note"


def test_cc_mode_sends_no_notes():
    from .test_phase_fsm import box

    rec = Recorder()
    rt = runtime_with(rec)
    rt.set_output_mode(True)
    drive(rt, box(inhale_s=2.0, hold_s=2.0, cycles=3))
    assert not [e for e in rec.events if e[0] in ("on", "off")] or rec.down == set()
    assert rec.down == set()


def test_switching_to_cc_mode_releases_the_held_note():
    from .test_phase_fsm import ramp

    rec = Recorder()
    rt = runtime_with(rec)
    drive(rt, ramp(0.05, 0.9, 2.0))
    assert rec.down, "expected a sounding note before the switch"
    rt.set_output_mode(True)
    assert rec.down == set(), "switching to CC mode stranded a note"
