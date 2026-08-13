"""
Small drawn arrows used as labels for the per-phase note fields.

    ↗  inhale     →  hold     ↘  exhale

Drawn rather than typed. Dear PyGui's default font atlas only rasterises basic
Latin, so the Unicode arrows (U+2197, U+2192, U+2198) would come out blank —
and loading a font just for three glyphs is a lot of machinery for this.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg

from breath_midi.types import Phase

DEFAULT_SIZE = 18
_PAD_RATIO = 0.18
_LABEL_COLOR = (200, 200, 200, 255)


def _endpoints(phase: Phase, size: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (tail, tip). The arrow points the way the breath is going."""
    pad = size * _PAD_RATIO
    x0, x1 = pad, size - pad
    top, bottom, mid = pad, size - pad, size / 2.0
    if phase is Phase.INHALE:
        return (x0, bottom), (x1, top)
    if phase is Phase.EXHALE:
        return (x0, top), (x1, bottom)
    return (x0, mid), (x1, mid)  # HOLD — level


def add_arrow_label(
    phase: Phase,
    size: int = DEFAULT_SIZE,
    color: tuple[int, int, int, int] = _LABEL_COLOR,
    tag: str | None = None,
) -> None:
    """Draw one static arrow label into the current DPG container."""
    tail, tip = _endpoints(phase, size)
    with dpg.drawlist(width=size, height=size):
        # DPG draws the head at p1, so the tip goes first.
        dpg.draw_arrow(
            tip,
            tail,
            color=color,
            thickness=2,
            size=max(3, int(size * 0.22)),
            **({"tag": tag} if tag else {}),
        )
