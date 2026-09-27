"""
Small drawn glyphs used as labels in the device panels.

    ↗  inhale     →  hold     ↘  exhale     •<>•  tolerance

Drawn rather than typed. Dear PyGui's default font atlas only rasterises basic
Latin, so the Unicode arrows (U+2197, U+2192, U+2198, U+2194) would come out
blank — and loading a font just for a handful of glyphs is a lot of machinery
for this.
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


TOL_WIDTH = 30
_DOT_R = 2.0
DIM_COLOR = (95, 95, 95, 255)


def add_tolerance_label(
    width: int = TOL_WIDTH,
    height: int = DEFAULT_SIZE,
    color: tuple[int, int, int, int] = _LABEL_COLOR,
    tag: str | None = None,
) -> None:
    """
    Draw the tolerance glyph: two dots with a double-headed arrow between them.

    It reads as "this much spread is allowed", which is what the consistency
    tolerance means — how far a breath's period and peak may sit from the
    rolling average and still count.

    `tag` names a group holding every piece, so the whole glyph can be dimmed
    in one call when the gate is off.
    """
    mid = height / 2.0
    left, right = _DOT_R + 1, width - _DOT_R - 1
    with dpg.drawlist(width=width, height=height, **({"tag": tag} if tag else {})):
        dpg.draw_circle((left, mid), _DOT_R, fill=color, color=color)
        dpg.draw_circle((right, mid), _DOT_R, fill=color, color=color)
        # Two arrows out from the centre, so both ends carry a head.
        centre = width / 2.0
        dpg.draw_arrow((left + _DOT_R + 1, mid), (centre, mid),
                       color=color, thickness=1, size=3)
        dpg.draw_arrow((right - _DOT_R - 1, mid), (centre, mid),
                       color=color, thickness=1, size=3)


def set_glyph_color(tag: str, color: tuple[int, int, int, int]) -> None:
    """Recolour every piece of a drawn glyph, e.g. to grey it out."""
    if not dpg.does_item_exist(tag):
        return
    for child in dpg.get_item_children(tag, 2) or []:
        cfg = dpg.get_item_configuration(child)
        kwargs = {"color": color}
        if "fill" in cfg:
            kwargs["fill"] = color
        dpg.configure_item(child, **kwargs)
