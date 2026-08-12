"""
One sounding note per device.

Each phase behaves like a key held down: pressed when the phase begins,
released when it ends. The invariant is that a device has at most one note
down at any instant, and it is enforced structurally — a single object owns the
note state, so there is nowhere else for a stray note-on to come from.

This replaces per-phase onset triggers for the multi-device path. Those fired
NOTE_ON and never released, which is fine for one-shot samples and wrong for
gates: four independent strategies each deciding to fire cannot guarantee that
exactly one note is down.
"""

from __future__ import annotations

from breath_midi.midi.base import MidiSink
from breath_midi.types import Phase

# Note 0 means silent. It is a real MIDI note (C-1) that nothing in this piece
# uses, and it reads better in the UI than a separate enable checkbox per phase.
SILENT = 0


class BreathVoice:
    """
    Holds down one note at a time, following the breath phase.

    Not thread-safe on its own: DeviceRuntime calls it under its own lock, from
    the single OSC receive thread.
    """

    def __init__(self, sink: MidiSink, channel: int = 0, velocity: int = 100) -> None:
        self._sink = sink
        self._channel = int(channel)
        self._velocity = int(velocity)
        self._notes: dict[Phase, int] = {
            Phase.INHALE: SILENT,
            Phase.HOLD: SILENT,
            Phase.EXHALE: SILENT,
        }
        self._sounding: int | None = None
        self._phase: Phase | None = None
        self._muted = False

    # ── configuration ─────────────────────────────────────────────────────────

    def set_notes(self, inhale: int, hold: int, exhale: int) -> None:
        self._notes = {
            Phase.INHALE: int(inhale),
            Phase.HOLD: int(hold),
            Phase.EXHALE: int(exhale),
        }

    def set_channel(self, channel: int) -> None:
        self._channel = int(channel)

    def set_velocity(self, velocity: int) -> None:
        self._velocity = max(0, min(127, int(velocity)))

    def set_muted(self, muted: bool) -> None:
        """Muting releases immediately — a held note must not survive a mute."""
        self._muted = bool(muted)
        if self._muted:
            self.release()

    # ── state ─────────────────────────────────────────────────────────────────

    @property
    def sounding_note(self) -> int | None:
        return self._sounding

    def note_for(self, phase: Phase) -> int:
        return self._notes.get(phase, SILENT)

    # ── the one operation that matters ────────────────────────────────────────

    def on_phase(self, phase: Phase) -> None:
        """
        Move to the note for `phase`, releasing whatever was sounding.

        Release always precedes press. If two phases share a note number that
        ordering makes the transition a retrigger; the other order would send
        note-on then note-off for the same pitch and leave silence.
        """
        target = self._notes.get(phase, SILENT)
        if self._muted:
            target = SILENT
        # Keyed on the phase, not just the note: two phases may share a note
        # number, and moving between them is a new articulation that should
        # retrigger rather than sustain silently through the change.
        if phase == self._phase and target == self._sounding:
            return

        self.release()
        self._phase = phase
        if target != SILENT:
            self._sink.send_note_on(self._channel, target, self._velocity)
            self._sounding = target

    def release(self) -> None:
        """
        Release the sounding note, if any. Safe to call repeatedly.

        Every path that can end a phase without a new one beginning must call
        this — device timeout, mute, solo-out, gate close, stop, tab switch,
        app exit — or the note rings until something else happens to clear it.
        """
        if self._sounding is None:
            return
        note, self._sounding = self._sounding, None
        try:
            self._sink.send_note_off(self._channel, note, 0)
        except Exception:
            # A closed or swapped MIDI port must not leave _sounding set, or the
            # next press would think a note is still down.
            pass
