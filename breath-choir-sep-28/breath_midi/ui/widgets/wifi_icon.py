"""
Wi-Fi status icon.

Three arcs and a dot, drawn rather than glyphed — DPG ships no icon set, and a
text character cannot be recoloured per-arc or scaled cleanly.

The icon is the control: clicking it adopts the current router as the
performance network. There is no separate button and no text, because the only
question it answers is "are the phones going to reach me", which is a yes or a
no.

    red       not on the target network (or none set, or offline)
    green     on the target network
    grey      flashing, briefly, right after you set it
"""

from __future__ import annotations

import math
import time

import dearpygui.dearpygui as dpg

RED = (225, 70, 60, 255)
GREEN = (0, 200, 110, 255)
GREY_ON = (170, 170, 170, 255)
GREY_OFF = (70, 70, 70, 255)

# How long the grey flash lasts after setting, and how fast it blinks.
FLASH_SECONDS = 1.6
_FLASH_HZ = 4.0

_ARC_SEGMENTS = 18
# Each ring is a fraction of the icon size; the dot sits at the origin.
_RINGS = (0.92, 0.64, 0.36)


def _arc_points(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """A 100-degree fan opening upward, which is the usual Wi-Fi wedge."""
    start, end = math.radians(-140.0), math.radians(-40.0)
    return [
        (
            cx + r * math.cos(start + (end - start) * i / (_ARC_SEGMENTS - 1)),
            cy + r * math.sin(start + (end - start) * i / (_ARC_SEGMENTS - 1)),
        )
        for i in range(_ARC_SEGMENTS)
    ]


def ring_tag(prefix: str, i: int) -> str:
    return f"{prefix}_ring{i}"


def dot_tag(prefix: str) -> str:
    return f"{prefix}_dot"


def build_wifi_icon(prefix: str, size: int = 26, color=GREY_OFF) -> None:
    """Draw the icon in the current container. `prefix` also tags the drawlist."""
    with dpg.drawlist(width=size, height=size, tag=prefix):
        cx = size / 2.0
        cy = size * 0.86           # origin near the bottom, arcs sweep above it
        radius = size * 0.40
        for i, scale in enumerate(_RINGS):
            dpg.draw_polyline(
                _arc_points(cx, cy, radius * scale / _RINGS[0]),
                color=color,
                thickness=max(2.0, size * 0.09),
                tag=ring_tag(prefix, i),
            )
        dpg.draw_circle(
            (cx, cy), max(1.5, size * 0.075),
            fill=color, color=color, tag=dot_tag(prefix),
        )


def set_wifi_color(prefix: str, color) -> None:
    """Recolour in place. Safe to call every frame."""
    for i in range(len(_RINGS)):
        tag = ring_tag(prefix, i)
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, color=color)
    tag = dot_tag(prefix)
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, fill=color, color=color)


def flash_colour(now: float, flash_until: float) -> tuple | None:
    """
    Grey blink while a set is settling, or None once it has finished.

    Returning None rather than a colour lets the caller fall through to the
    real red/green state without needing to know the flash is over.
    """
    if now >= flash_until:
        return None
    on = int((flash_until - now) * _FLASH_HZ * 2) % 2 == 0
    return GREY_ON if on else GREY_OFF


def state_colour(on_target: bool) -> tuple:
    return GREEN if on_target else RED


def hovered(prefix: str) -> bool:
    return dpg.does_item_exist(prefix) and dpg.is_item_hovered(prefix)
