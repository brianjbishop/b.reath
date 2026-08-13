"""
Ableton-style rotary knob for Dear PyGui.

DPG has no knob widget, so this is drawn: a 270° track with the gap at the
bottom, a value arc sweeping clockwise from the lower left, and a pointer.
Drag vertically or scroll the wheel to change it.

The value lives in a DPG *value registry* under the caller's tag, so
`dpg.get_value(tag)` and `dpg.set_value(tag)` behave exactly as they would for
an `add_input_float`. Existing code that reads or writes these controls needs
no changes — only the line that creates the widget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import dearpygui.dearpygui as dpg

# Gap at the bottom, like a hardware pot: sweep left → top → right.
_START_DEG = 135.0
_SWEEP_DEG = 270.0
_ARC_SEGMENTS = 48

_TRACK_COLOR = (70, 70, 74, 255)
_VALUE_COLOR = (235, 200, 90, 255)
_POINTER_COLOR = (245, 245, 245, 255)
_LABEL_COLOR = (170, 170, 170, 255)
_VALUE_TEXT_COLOR = (225, 225, 225, 255)

# A full sweep takes this many pixels of vertical drag. Roughly Ableton's feel:
# far enough that fine adjustment is possible without the knob feeling sticky.
_DRAG_PIXELS_FULL_RANGE = 220.0


@dataclass
class _Knob:
    tag: str
    draw_tag: str
    text_tag: str
    minimum: float
    maximum: float
    step: float
    fmt: str
    callback: Callable | None
    size: int
    is_int: bool
    last_drawn: float | None = field(default=None)
    drag_start_value: float = 0.0


_knobs: dict[str, _Knob] = {}
_active_tag: str | None = None
_registry_built = False


def _clamp(k: _Knob, v: float) -> float:
    v = max(k.minimum, min(k.maximum, v))
    return float(round(v)) if k.is_int else v


def _fraction(k: _Knob, v: float) -> float:
    span = k.maximum - k.minimum
    return 0.0 if span <= 0 else (v - k.minimum) / span


def _point(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return (cx + r * math.cos(rad), cy + r * math.sin(rad))


def _arc_points(cx: float, cy: float, r: float, frac: float) -> list[tuple[float, float]]:
    span = _SWEEP_DEG * max(0.0, min(1.0, frac))
    steps = max(2, int(_ARC_SEGMENTS * max(frac, 0.02)))
    return [_point(cx, cy, r, _START_DEG + span * i / (steps - 1)) for i in range(steps)]


def add_knob(
    tag: str,
    label: str,
    *,
    default: float,
    min_value: float,
    max_value: float,
    step: float,
    fmt: str = "%.2f",
    callback: Callable | None = None,
    size: int = 58,
    is_int: bool = False,
) -> None:
    """
    Create a knob bound to `tag`.

    `tag` becomes a value-registry item, so the rest of the app keeps using
    dpg.get_value(tag) / dpg.set_value(tag) unchanged.
    """
    _ensure_handlers()

    if not dpg.does_item_exist("knob_value_registry"):
        dpg.add_value_registry(tag="knob_value_registry")
    dpg.add_float_value(tag=tag, default_value=float(default), parent="knob_value_registry")

    k = _Knob(
        tag=tag,
        draw_tag=f"{tag}__knob",
        text_tag=f"{tag}__knobval",
        minimum=float(min_value),
        maximum=float(max_value),
        step=float(step),
        fmt=fmt,
        callback=callback,
        size=size,
        is_int=is_int,
    )
    _knobs[tag] = k

    cx = cy = size / 2.0
    r = size / 2.0 - 5

    with dpg.group():
        dpg.add_text(label, color=_LABEL_COLOR)
        with dpg.drawlist(width=size, height=size, tag=k.draw_tag):
            dpg.draw_polyline(
                _arc_points(cx, cy, r, 1.0), color=_TRACK_COLOR, thickness=3
            )
            dpg.draw_polyline(
                _arc_points(cx, cy, r, _fraction(k, default)),
                color=_VALUE_COLOR,
                thickness=3,
                tag=f"{tag}__arc",
            )
            ang = _START_DEG + _SWEEP_DEG * _fraction(k, default)
            dpg.draw_line(
                _point(cx, cy, r * 0.30, ang),
                _point(cx, cy, r * 0.82, ang),
                color=_POINTER_COLOR,
                thickness=2,
                tag=f"{tag}__ptr",
            )
        dpg.add_text(fmt % default, tag=k.text_tag, color=_VALUE_TEXT_COLOR)

    _redraw(k, force=True)


def refresh_knobs() -> None:
    """Redraw any knob whose bound value changed underneath it (e.g. config load)."""
    for k in _knobs.values():
        _redraw(k)


def _redraw(k: _Knob, force: bool = False) -> None:
    if not dpg.does_item_exist(k.draw_tag):
        return
    v = float(dpg.get_value(k.tag))
    if not force and k.last_drawn is not None and abs(v - k.last_drawn) < 1e-9:
        return
    k.last_drawn = v

    cx = cy = k.size / 2.0
    r = k.size / 2.0 - 5
    frac = _fraction(k, v)

    dpg.configure_item(f"{k.tag}__arc", points=_arc_points(cx, cy, r, frac))
    ang = _START_DEG + _SWEEP_DEG * frac
    dpg.configure_item(
        f"{k.tag}__ptr",
        p1=_point(cx, cy, r * 0.30, ang),
        p2=_point(cx, cy, r * 0.82, ang),
    )
    dpg.set_value(k.text_tag, k.fmt % v)


def _set(k: _Knob, v: float) -> None:
    v = _clamp(k, v)
    if abs(v - float(dpg.get_value(k.tag))) < 1e-12:
        return
    dpg.set_value(k.tag, v)
    _redraw(k)
    if k.callback is not None:
        k.callback()


def _hovered() -> _Knob | None:
    for k in _knobs.values():
        if dpg.does_item_exist(k.draw_tag) and dpg.is_item_hovered(k.draw_tag):
            return k
    return None


# ── mouse plumbing ────────────────────────────────────────────────────────────


def _on_click(_sender, _app_data) -> None:
    global _active_tag
    k = _hovered()
    if k is None:
        _active_tag = None
        return
    _active_tag = k.tag
    # Drag deltas from DPG are cumulative from the press, so anchor here.
    k.drag_start_value = float(dpg.get_value(k.tag))


def _on_drag(_sender, app_data) -> None:
    if _active_tag is None:
        return
    k = _knobs.get(_active_tag)
    if k is None:
        return
    _button, _dx, dy = app_data
    span = k.maximum - k.minimum
    # Up increases, which is what every DAW does.
    _set(k, k.drag_start_value - (dy / _DRAG_PIXELS_FULL_RANGE) * span)


def _on_release(_sender, _app_data) -> None:
    global _active_tag
    _active_tag = None


def _on_wheel(_sender, app_data) -> None:
    k = _hovered()
    if k is None:
        return
    _set(k, float(dpg.get_value(k.tag)) + float(app_data) * k.step)


def _ensure_handlers() -> None:
    """
    One shared global handler registry.

    Per-item handlers cannot see the wheel, and a drag has to be tracked past
    the edge of the widget, so this is global and resolves the target by
    hit-testing on press.
    """
    global _registry_built
    if _registry_built:
        return
    with dpg.handler_registry():
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=_on_click)
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, callback=_on_drag)
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=_on_release)
        dpg.add_mouse_wheel_handler(callback=_on_wheel)
    _registry_built = True


def _reset_for_tests() -> None:
    """DPG state does not survive destroy_context(); mirror that here."""
    global _registry_built, _active_tag
    _knobs.clear()
    _registry_built = False
    _active_tag = None
