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
from breath_midi.triggers.v1.inhale_cc_onset import InhaleCcOnsetTrigger
from breath_midi.triggers.v1.inhale_onset import InhaleOnsetTrigger
from breath_midi.types import BreathSample, Phase, TriggerKind


class DeviceRuntime:
    """
    Independent signal → trigger → MIDI pipeline for one OSC device.

    Runs inhale/exhale onset triggers (note or CC mode) gated by a
    ConsistentBreathsTrigger.  When N=0 the gate is bypassed and MIDI
    always fires.  When N>0 the gate opens after N consistent breaths
    and closes when consistency is lost.

    Sustain CC is intentionally excluded — Every Breath tracks onset
    events per performer for choir-level triggering, not continuous CC.
    """

    def __init__(self, config: ConfigModel, shared_sink: MidiSink) -> None:
        self._shared_sink = shared_sink
        self._lock = threading.Lock()
        self._signal = SignalProcessor(config.signal)
        self._features = FeatureExtractor(config.detection)
        self._inh_cc = InhaleCcOnsetTrigger()
        self._exh_cc = ExhaleCcOnsetTrigger()
        self._cons = ConsistentBreathsTrigger()
        self._cc_mode: bool = False
        self._gate_open: bool = True   # starts open; closes only after streak is lost
        self._cons_n: int = 3
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
            if not muted and gate_pass:
                for e in events:
                    if e.name != ConsistentBreathsTrigger.id:
                        try:
                            self._router.handle(e)
                        except Exception:
                            pass
        self._phase = frame.phase
        return frame.phase

    def get_phase(self) -> Phase:
        return self._phase

    def get_gate_open(self) -> bool:
        """True when consistent breaths streak is met, or when N=0 (gating disabled)."""
        return self._cons_n == 0 or self._gate_open

    # ── private helpers ───────────────────────────────────────────────────────

    def _current_strategies(self) -> list:
        onset = [self._inh_cc, self._exh_cc] if self._cc_mode else [InhaleOnsetTrigger(), ExhaleOnsetTrigger()]
        return onset + [self._cons]

    # ── public controls ───────────────────────────────────────────────────────

    def set_notes(self, inhale_note: int, exhale_note: int) -> None:
        t = self._config.triggers
        new_cfg = replace(
            self._config,
            triggers=replace(
                t,
                inhale_onset=replace(t.inhale_onset, note=inhale_note),
                exhale_onset=replace(t.exhale_onset, note=exhale_note),
            ),
        )
        with self._lock:
            self._config = new_cfg
            self._triggers = TriggerEngine(new_cfg, strategies=self._current_strategies())
            self._router = MidiRouter(new_cfg, midi=self._shared_sink)

    def set_output_mode(self, cc_mode: bool) -> None:
        """Switch between note-onset mode (default) and CC-onset mode."""
        with self._lock:
            self._cc_mode = cc_mode
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
        """Update the CC value fired by both CC onset triggers."""
        with self._lock:
            self._inh_cc.set_cc(self._inh_cc._cc_number, cc_value)
            self._exh_cc.set_cc(self._exh_cc._cc_number, cc_value)

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


def make_device_config(base: ConfigModel, inhale_note: int, exhale_note: int) -> ConfigModel:
    """
    Build a per-device ConfigModel from base config with device-specific notes.
    Sustain CC and ConsistentBreaths triggers are disabled — see DeviceRuntime docstring.
    """
    t = base.triggers
    return replace(
        base,
        triggers=replace(
            t,
            inhale_onset=replace(t.inhale_onset, note=inhale_note, enabled=True),
            exhale_onset=replace(t.exhale_onset, note=exhale_note, enabled=True),
            inhale_sustain=replace(t.inhale_sustain, enabled=False),
            exhale_sustain=replace(t.exhale_sustain, enabled=False),
            consistent_breaths=replace(t.consistent_breaths, enabled=False),
        ),
    )
