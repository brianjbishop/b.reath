"""
Four-vertex phase indicator.

Replaces the pair of In/Ex squares.  The four breath phases sit at the points
of a diamond and the cycle runs clockwise, so a performer's breathing reads as
motion around a shape rather than two lamps blinking:

             hold
               ◆
              / \\
    inhale  ◆     ◆  exhale
              \\ /
               ◆
             hold

Only the active vertex is lit.  There is one HOLD phase, not two: the top and
bottom vertices are the same state, and which one lights is decided by where
the breath actually is.  That keeps the cycle readable without inventing a
distinction the detector does not make.  Vertices are created once and recoloured in
place via configure_item — the same constraint the waveform plots are under
(rebuilding drawlist items every frame causes visible flicker).
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg

from breath_midi.types import Phase

# Vertex order around the diamond, clockwise from the left point.
# Positions around the diamond, clockwise from the left point.  HOLD appears
# twice because the cycle passes through it twice.
HOLD_TOP = "hold_top"
HOLD_BOTTOM = "hold_bottom"
_VERTICES: tuple[str, ...] = (Phase.INHALE.value, HOLD_TOP, Phase.EXHALE.value, HOLD_BOTTOM)

_EDGE_COLOR = (70, 70, 70, 255)
_GRAY_INACTIVE = (80, 80, 80, 255)
_PAUSED_COLOR = (200, 200, 200, 255)

DEFAULT_SIZE = 56
_VERTEX_R = 5


def vertex_tag(prefix: str, vertex: str | Phase) -> str:
    name = vertex.value if isinstance(vertex, Phase) else vertex
    return f"{prefix}_v_{name}"


def _points(size: int) -> dict[str, tuple[float, float]]:
    c = size / 2.0
    r = c - _VERTEX_R - 1
    return {
        Phase.INHALE.value: (c - r, c),
        HOLD_TOP: (c, c - r),
        Phase.EXHALE.value: (c + r, c),
        HOLD_BOTTOM: (c, c + r),
    }


def _lit_vertex(
    phase: Phase, amp: float, peak_band: float, valley_band: float = 0.0
) -> str | None:
    """
    Which vertex the current phase lights.

    A hold lights the top or the bottom depending on where the breath is — the
    detector has one HOLD state, but the performer can see which end they are
    holding at.

    The split is the midpoint *between* the two bands rather than the peak
    threshold itself.  Once a hold has latched the value can drift, and with
    wide bands a peak hold that sagged slightly would otherwise jump to the
    bottom vertex while the performer is still holding at the top.
    """
    if phase is Phase.INHALE:
        return Phase.INHALE.value
    if phase is Phase.EXHALE:
        return Phase.EXHALE.value
    if phase is Phase.HOLD:
        midpoint = (peak_band + valley_band) / 2.0
        return HOLD_TOP if amp >= midpoint else HOLD_BOTTOM
    return None  # REST lights nothing


def build_phase_rhombus(
    prefix: str,
    phase: Phase,
    color: tuple[int, int, int],
    active: bool,
    size: int = DEFAULT_SIZE,
    amp: float = 0.0,
    peak_band: float = 0.5,
    valley_band: float = 0.5,
) -> None:
    """Create the diamond inside the current DPG container."""
    pts = _points(size)
    lit = _lit_vertex(phase, amp, peak_band, valley_band)
    with dpg.drawlist(width=size, height=size):
        # Edges first so the vertices draw on top of them.
        for i, v in enumerate(_VERTICES):
            nxt = _VERTICES[(i + 1) % len(_VERTICES)]
            dpg.draw_line(pts[v], pts[nxt], color=_EDGE_COLOR, thickness=1)
        for v in _VERTICES:
            dpg.draw_circle(
                pts[v],
                _VERTEX_R,
                fill=_vertex_fill(v, lit, color, active),
                color=(0, 0, 0, 0),
                tag=vertex_tag(prefix, v),
            )


def refresh_phase_rhombus(
    prefix: str,
    phase: Phase,
    color: tuple[int, int, int],
    active: bool,
    amp: float = 0.0,
    peak_band: float = 0.5,
    valley_band: float = 0.5,
) -> None:
    """Recolour the vertices for the current phase.  Safe to call every frame."""
    lit = _lit_vertex(phase, amp, peak_band, valley_band)
    for v in _VERTICES:
        tag = vertex_tag(prefix, v)
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, fill=_vertex_fill(v, lit, color, active))


def _vertex_fill(
    vertex: str,
    lit: str | None,
    color: tuple[int, int, int],
    active: bool,
) -> list[int]:
    if not active:
        return list(_PAUSED_COLOR)
    if vertex == lit:
        return [*color, 255]
    return list(_GRAY_INACTIVE)
