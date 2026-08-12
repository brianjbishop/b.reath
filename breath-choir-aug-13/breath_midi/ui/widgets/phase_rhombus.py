"""
Four-vertex phase indicator.

Replaces the pair of In/Ex squares.  The four breath phases sit at the points
of a diamond and the cycle runs clockwise, so a performer's breathing reads as
motion around a shape rather than two lamps blinking:

           hold full
               ◆
              / \\
    inhale  ◆     ◆  exhale
              \\ /
               ◆
          hold empty

Only the active vertex is lit.  Vertices are created once and recoloured in
place via configure_item — the same constraint the waveform plots are under
(rebuilding drawlist items every frame causes visible flicker).
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg

from breath_midi.types import Phase

# Vertex order around the diamond, clockwise from the left point.
_VERTEX_PHASES: tuple[Phase, ...] = (
    Phase.INHALE,
    Phase.HOLD_FULL,
    Phase.EXHALE,
    Phase.HOLD_EMPTY,
)

_EDGE_COLOR = (70, 70, 70, 255)
_GRAY_INACTIVE = (80, 80, 80, 255)
_PAUSED_COLOR = (200, 200, 200, 255)

DEFAULT_SIZE = 56
_VERTEX_R = 5


def vertex_tag(prefix: str, phase: Phase) -> str:
    return f"{prefix}_v_{phase.value}"


def _points(size: int) -> dict[Phase, tuple[float, float]]:
    c = size / 2.0
    r = c - _VERTEX_R - 1
    return {
        Phase.INHALE: (c - r, c),
        Phase.HOLD_FULL: (c, c - r),
        Phase.EXHALE: (c + r, c),
        Phase.HOLD_EMPTY: (c, c + r),
    }


def build_phase_rhombus(
    prefix: str,
    phase: Phase,
    color: tuple[int, int, int],
    active: bool,
    size: int = DEFAULT_SIZE,
) -> None:
    """Create the diamond inside the current DPG container."""
    pts = _points(size)
    with dpg.drawlist(width=size, height=size):
        # Edges first so the vertices draw on top of them.
        for i, p in enumerate(_VERTEX_PHASES):
            nxt = _VERTEX_PHASES[(i + 1) % len(_VERTEX_PHASES)]
            dpg.draw_line(pts[p], pts[nxt], color=_EDGE_COLOR, thickness=1)
        for p in _VERTEX_PHASES:
            dpg.draw_circle(
                pts[p],
                _VERTEX_R,
                fill=_vertex_fill(p, phase, color, active),
                color=(0, 0, 0, 0),
                tag=vertex_tag(prefix, p),
            )


def refresh_phase_rhombus(
    prefix: str,
    phase: Phase,
    color: tuple[int, int, int],
    active: bool,
) -> None:
    """Recolour the vertices for the current phase.  Safe to call every frame."""
    for p in _VERTEX_PHASES:
        tag = vertex_tag(prefix, p)
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, fill=_vertex_fill(p, phase, color, active))


def _vertex_fill(
    vertex: Phase,
    phase: Phase,
    color: tuple[int, int, int],
    active: bool,
) -> list[int]:
    if not active:
        return list(_PAUSED_COLOR)
    if vertex == phase:
        return [*color, 255]
    return list(_GRAY_INACTIVE)
