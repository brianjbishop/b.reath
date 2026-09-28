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
from breath_midi.triggers.v1.sustain_cc import (
    BreathCcTrigger,
    ExhaleSustainCcTrigger,
    InhaleSustainCcTrigger,
)
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

    def __init__(
        self,
        config: ConfigModel,
        shared_sink: MidiSink,
        midi_channel: int | None = None,
    ) -> None:
        self._shared_sink = shared_sink
        self._lock = threading.Lock()
        self._signal = SignalProcessor(config.signal)
        self._features = FeatureExtractor(config.detection)
        self._inh_cc = InhaleCcOnsetTrigger()
        self._exh_cc = ExhaleCcOnsetTrigger()
        self._hold_cc = HoldCcOnsetTrigger()
        # CC mode is continuous: the first two fields track amplitude within
        # their phase, the third tracks it all the way round.  The onset
        # triggers above sent one fixed value per phase change, which is a note
        # with extra steps rather than something you can map to a dial.
        self._inh_sustain = InhaleSustainCcTrigger()
        self._exh_sustain = ExhaleSustainCcTrigger()
        self._breath_cc = BreathCcTrigger()
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
        # The router reads cfg.midi.channel, so CC goes out on whatever the
        # device config says.  Without this every device's CC would land on
        # channel 1 however the Ch field was set — notes would route per device
        # and dials would not, which is a difference nobody would guess at.
        if midi_channel is not None:
            self._config = replace(
                self._config,
                midi=replace(
                    self._config.midi,
                    channel=max(0, min(15, int(midi_channel) - 1)),
                ),
            )

        # midi_channel is 1-16; the wire is 0-15. This and set_midi_channel
        # are the only two places that conversion happens.
        self._voice = BreathVoice(
            shared_sink,
            channel=(
                int(config.midi.channel)
                if midi_channel is None
                else max(0, min(15, int(midi_channel) - 1))
            ),
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
        cc = (
            [self._inh_sustain, self._exh_sustain, self._breath_cc]
            if self._cc_mode
            else []
        )
        return cc + [self._cons]

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
        """
        The CC number for the inhale dial.

        CC mode reuses the same three fields the notes use, so switching modes
        reinterprets the numbers rather than adding three more.
        """
        with self._lock:
            self._inh_cc.set_cc(cc_number, self._inh_cc._cc_value)
            self._config = replace(
                self._config,
                triggers=replace(
                    self._config.triggers,
                    inhale_sustain=replace(
                        self._config.triggers.inhale_sustain,
                        cc=int(cc_number), enabled=int(cc_number) > 0,
                    ),
                ),
            )
            self._triggers = TriggerEngine(
                self._config, strategies=self._current_strategies()
            )

    def set_exhale_cc(self, cc_number: int) -> None:
        """The CC number for the exhale dial."""
        with self._lock:
            self._exh_cc.set_cc(cc_number, self._exh_cc._cc_value)
            self._config = replace(
                self._config,
                triggers=replace(
                    self._config.triggers,
                    exhale_sustain=replace(
                        self._config.triggers.exhale_sustain,
                        cc=int(cc_number), enabled=int(cc_number) > 0,
                    ),
                ),
            )
            self._triggers = TriggerEngine(
                self._config, strategies=self._current_strategies()
            )

    def set_cc_value(self, cc_value: int) -> None:
        """Update the CC value fired by every CC onset trigger."""
        with self._lock:
            self._inh_cc.set_cc(self._inh_cc._cc_number, cc_value)
            self._exh_cc.set_cc(self._exh_cc._cc_number, cc_value)
            self._hold_cc.set_cc(self._hold_cc._cc_number, cc_value)

    def set_hold_cc(self, cc_number: int) -> None:
        """
        The CC number for the whole-cycle dial — the third field.

        Unlike the other two this one is not gated by phase, so it keeps sending
        through a hold.  It needs no enabled flag: the trigger treats 0 as off,
        the same sentinel a silent note uses.
        """
        with self._lock:
            self._hold_cc.set_cc(cc_number, self._hold_cc._cc_value)
            self._breath_cc.set_cc(int(cc_number))

    def release(self) -> None:
        """
        Release the sounding note.  Called on device timeout, stop, tab switch
        and app exit — anywhere a phase ends without another beginning.
        """
        with self._lock:
            self._voice.release()

    def set_midi_channel(self, channel: int) -> None:
        """
        Move this device to another channel.  `channel` is 1-16.

        Releases first, while _channel is still the old one, so the note-off
        lands where the note-on did.  Sending it after the change would leave a
        key held down on the old channel with nothing left to clear it.
        """
        with self._lock:
            wire = max(0, min(15, int(channel) - 1))
            self._voice.release()
            self._voice.set_channel(wire)
            # CC routes through the router, which reads this.
            self._config = replace(
                self._config,
                midi=replace(self._config.midi, channel=wire),
            )
            self._router.update_config(self._config)

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
            # Enabled per device by set_inhale_cc / set_exhale_cc, which switch
            # them on only when a CC number is set.  They used to be forced off
            # here, back when Every Breath did phase triggering and nothing else.
            inhale_sustain=replace(t.inhale_sustain, enabled=False),
            exhale_sustain=replace(t.exhale_sustain, enabled=False),
            consistent_breaths=replace(t.consistent_breaths, enabled=False),
        ),
    )
