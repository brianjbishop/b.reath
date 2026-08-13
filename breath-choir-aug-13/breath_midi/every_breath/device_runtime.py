from __future__ import annotations

import threading
from dataclasses import replace

from breath_midi.config.model import ConfigModel
from breath_midi.midi.base import MidiSink
from breath_midi.midi.router import MidiRouter
from breath_midi.signal.features import FeatureExtractor
from breath_midi.signal.processor import SignalProcessor
from breath_midi.triggers.engine import TriggerEngine
from breath_midi.triggers.v1.consistent_breaths import ConsistentBreathsTrigger
from breath_midi.triggers.v1.exhale_cc_onset import ExhaleCcOnsetTrigger
from breath_midi.triggers.v1.exhale_onset import ExhaleOnsetTrigger
from breath_midi.triggers.v1.hold_cc_onset import HoldCcOnsetTrigger
from breath_midi.triggers.v1.inhale_cc_onset import InhaleCcOnsetTrigger
from breath_midi.triggers.v1.inhale_onset import InhaleOnsetTrigger
from breath_midi.midi.voice import SILENT, BreathVoice
from breath_midi.types import BreathSample, Phase, TriggerKind


class DeviceRuntime:
    """
    Independent signal → phase → MIDI pipeline for one OSC device.

    In note mode the phase drives a BreathVoice: inhale, hold and exhale each
    behave like a key held down, and exactly one is down at a time.  In CC mode
    the phase fires one-shot CC messages through the trigger engine instead,
    since CC has no on/off pairing to keep exclusive.

    Either way output is gated by ConsistentBreathsTrigger.  When N=0 the gate
    is bypassed and MIDI always flows.  When N>0 the gate opens after N
    consistent breaths and closes when consistency is lost — and closing it
    releases the sounding note rather than stranding it.

    Sustain CC is intentionally excluded — Every Breath tracks phase changes
    per performer for choir-level triggering, not continuous CC.
    """

    def __init__(self, config: ConfigModel, shared_sink: MidiSink) -> None:
        self._shared_sink = shared_sink
        self._lock = threading.Lock()
        self._signal = SignalProcessor(config.signal)
        self._features = FeatureExtractor(config.detection)
        self._inh_cc = InhaleCcOnsetTrigger()
        self._exh_cc = ExhaleCcOnsetTrigger()
        self._hold_cc = HoldCcOnsetTrigger()
        self._cons = ConsistentBreathsTrigger()
        self._cc_mode: bool = False
        self._gate_open: bool = True   # starts open; closes only after streak is lost
        self._cons_n: int = 0
        self._cons_tolerance: float = 0.30
        # Enable consistent_breaths gating with defaults
        t = config.triggers
        self._config = replace(
            config,
            triggers=replace(
                t,
                consistent_breaths=replace(
                    t.consistent_breaths,
                    enabled=True,
                    n=self._cons_n,
                    period_tol_value=self._cons_tolerance,
                    peak_tol_value=self._cons_tolerance,
                ),
            ),
        )
        self._triggers = TriggerEngine(
            self._config,
            strategies=self._current_strategies(),
        )
        self._router = MidiRouter(self._config, midi=shared_sink)
        self._phase: Phase = Phase.REST
        self._voice = BreathVoice(
            shared_sink,
            channel=int(config.midi.channel),
            velocity=int(config.midi.default_velocity),
        )
        self._voice.set_notes(
            inhale=int(config.triggers.inhale_onset.note),
            hold=int(config.triggers.hold_onset.note),
            exhale=int(config.triggers.exhale_onset.note),
        )

    def on_sample(self, sample: BreathSample, muted: bool = False) -> Phase:
        ps = self._signal.process(sample)
        frame = self._features.update(ps)
        with self._lock:
            events = self._triggers.on_frame(frame)
            # Update gate state from consistent_breaths events — never routed to MIDI
            for e in events:
                if e.name == ConsistentBreathsTrigger.id:
                    self._gate_open = (e.kind == TriggerKind.NOTE_ON)
            # N=0 bypasses gating entirely; otherwise gate must be open
            gate_pass = self._cons_n == 0 or self._gate_open
            allowed = (not muted) and gate_pass

            if self._cc_mode:
                if allowed:
                    for e in events:
                        if e.name != ConsistentBreathsTrigger.id:
                            try:
                                self._router.handle(e)
                            except Exception:
                                pass
            else:
                # The voice is told the phase every frame, not only on change:
                # it is idempotent, and this way a mute or a closing gate
                # releases the note on the very next sample instead of waiting
                # for the performer to change phase.
                if allowed:
                    self._voice.on_phase(frame.phase)
                else:
                    self._voice.release()
        self._phase = frame.phase
        return frame.phase

    def get_phase(self) -> Phase:
        return self._phase

    def get_gate_open(self) -> bool:
        """True when consistent breaths streak is met, or when N=0 (gating disabled)."""
        return self._cons_n == 0 or self._gate_open

    # ── private helpers ───────────────────────────────────────────────────────

    def _current_strategies(self) -> list:
        # Note mode is driven by BreathVoice, not by onset strategies — the
        # gate needs a single owner of the note state.  Only CC mode still
        # goes through the trigger engine, because CC has no on/off pairing.
        onset = [self._inh_cc, self._exh_cc, self._hold_cc] if self._cc_mode else []
        return onset + [self._cons]

    # ── public controls ───────────────────────────────────────────────────────

    def set_notes(self, inhale_note: int, exhale_note: int, hold_note: int = SILENT) -> None:
        """Assign this device's three phase notes.  0 means silent."""
        t = self._config.triggers
        new_cfg = replace(
            self._config,
            triggers=replace(
                t,
                inhale_onset=replace(t.inhale_onset, note=inhale_note),
                exhale_onset=replace(t.exhale_onset, note=exhale_note),
                hold_onset=replace(t.hold_onset, note=hold_note),
            ),
        )
        with self._lock:
            self._config = new_cfg
            self._triggers = TriggerEngine(new_cfg, strategies=self._current_strategies())
            self._router = MidiRouter(new_cfg, midi=self._shared_sink)
            # Retune without dropping the sounding note: if the note for the
            # current phase changed, the next frame moves to it cleanly.
            self._voice.set_notes(
                inhale=inhale_note, hold=hold_note, exhale=exhale_note
            )

    def set_output_mode(self, cc_mode: bool) -> None:
        """Switch between note-onset mode (default) and CC-onset mode."""
        with self._lock:
            self._cc_mode = cc_mode
            # Leaving note mode must not strand the sounding note.
            self._voice.release()
            self._triggers = TriggerEngine(self._config, strategies=self._current_strategies())

    def set_inhale_cc(self, cc_number: int) -> None:
        """Update the inhale CC trigger's CC number (used in CC mode)."""
        with self._lock:
            self._inh_cc.set_cc(cc_number, self._inh_cc._cc_value)

    def set_exhale_cc(self, cc_number: int) -> None:
        """Update the exhale CC trigger's CC number (used in CC mode)."""
        with self._lock:
            self._exh_cc.set_cc(cc_number, self._exh_cc._cc_value)

    def set_cc_value(self, cc_value: int) -> None:
        """Update the CC value fired by every CC onset trigger."""
        with self._lock:
            self._inh_cc.set_cc(self._inh_cc._cc_number, cc_value)
            self._exh_cc.set_cc(self._exh_cc._cc_number, cc_value)
            self._hold_cc.set_cc(self._hold_cc._cc_number, cc_value)

    def set_hold_cc(self, cc_number: int) -> None:
        """Update the hold CC trigger's CC number (used in CC mode)."""
        with self._lock:
            self._hold_cc.set_cc(cc_number, self._hold_cc._cc_value)

    def release(self) -> None:
        """
        Release the sounding note.  Called on device timeout, stop, tab switch
        and app exit — anywhere a phase ends without another beginning.
        """
        with self._lock:
            self._voice.release()

    def set_midi_channel(self, channel: int) -> None:
        """Move this device to another channel, releasing on the old one first."""
        with self._lock:
            self._voice.release()
            self._voice.set_channel(channel)

    def set_cons_n(self, n: int) -> None:
        """Set consistent breaths streak target.  n=0 disables gating."""
        with self._lock:
            self._cons_n = n
            t = self._config.triggers
            self._config = replace(
                self._config,
                triggers=replace(t, consistent_breaths=replace(t.consistent_breaths, n=max(1, n))),
            )
            self._triggers = TriggerEngine(self._config, strategies=self._current_strategies())

    def set_cons_tolerance(self, tol: float) -> None:
        """Set period and peak tolerance to the same value (single knob)."""
        with self._lock:
            self._cons_tolerance = tol
            t = self._config.triggers
            self._config = replace(
                self._config,
                triggers=replace(
                    t,
                    consistent_breaths=replace(
                        t.consistent_breaths,
                        period_tol_value=tol,
                        peak_tol_value=tol,
                    ),
                ),
            )
            self._triggers = TriggerEngine(self._config, strategies=self._current_strategies())


def make_device_config(
    base: ConfigModel,
    inhale_note: int,
    exhale_note: int,
    hold_note: int = SILENT,
) -> ConfigModel:
    """
    Build a per-device ConfigModel from base config with device-specific notes.
    Sustain CC and ConsistentBreaths triggers are disabled — see DeviceRuntime.
    hold_note defaults to 0, which means the hold is silent.
    """
    t = base.triggers
    return replace(
        base,
        triggers=replace(
            t,
            inhale_onset=replace(t.inhale_onset, note=inhale_note, enabled=True),
            exhale_onset=replace(t.exhale_onset, note=exhale_note, enabled=True),
            hold_onset=replace(t.hold_onset, note=hold_note, enabled=True),
            inhale_sustain=replace(t.inhale_sustain, enabled=False),
            exhale_sustain=replace(t.exhale_sustain, enabled=False),
            consistent_breaths=replace(t.consistent_breaths, enabled=False),
        ),
    )
