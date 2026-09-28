"""
MIDI note numbers as names, the way Ableton writes them.

Octave numbering is not standardised.  Scientific pitch notation calls note 60
C4; Ableton, and most hardware aimed at it, calls it C3.  This module follows
Ableton, because the whole point of showing a name here is to match what is
written on a drum pad in the set these notes are going to.

    36 -> C1     the bottom left pad of a default Drum Rack
    60 -> C3     Ableton's middle C
    54 -> F#2

Note 0 is this app's silent sentinel — see BreathVoice.SILENT — so it is named
as such rather than as C-2, which would look like a real, very low note.
"""

from __future__ import annotations

_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Ableton puts middle C (60) at C3; scientific pitch puts it at C4.
_OCTAVE_OFFSET = 2

SILENT = 0


def note_name(note: int) -> str:
    """The bare name, e.g. 'F#2'.  Names note 0 as C-2 rather than 'silent'."""
    note = int(note)
    return f"{_NAMES[note % 12]}{note // 12 - _OCTAVE_OFFSET}"


def note_label(note: int) -> str:
    """
    What to show beside a note field.

    Zero means the phase plays nothing, so it reads 'silent' instead of naming
    a pitch nobody is going to hear.
    """
    note = int(note)
    if note == SILENT:
        return "silent"
    return note_name(note)
