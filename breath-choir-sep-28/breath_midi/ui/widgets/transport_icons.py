"""
Stop and record icons.

Drawn, like the tray and Wi-Fi icons, because DPG ships no icon set and a text
glyph cannot be recoloured or scaled cleanly.  A filled square and a filled
circle are the two most universally read transport symbols there are, so
neither needs a label.

Record turns red while a take is rolling.  That is the only state either icon
carries, and it matters: a take left running unnoticed is the failure mode.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg

IDLE = (150, 150, 150, 255)
HOVER = (230, 230, 230, 255)
RECORDING = (215, 65, 60, 255)

_SIZE = 26


def build_stop_icon(tag: str, size: int = _SIZE) -> None:
    """A filled square, inset so it optically matches the other icons."""
    with dpg.drawlist(width=size, height=size, tag=tag):
        pad = size * 0.28
        dpg.draw_rectangle(
            (pad, pad), (size - pad, size - pad),
            color=IDLE, fill=IDLE, tag=f"{tag}_shape",
        )


def build_record_icon(tag: str, size: int = _SIZE) -> None:
    """A filled circle."""
    with dpg.drawlist(width=size, height=size, tag=tag):
        c = size / 2.0
        dpg.draw_circle(
            (c, c), size * 0.24,
            color=IDLE, fill=IDLE, tag=f"{tag}_shape",
        )


def set_icon_color(tag: str, color) -> None:
    """Recolour in place. Safe to call every frame, and before the icon exists."""
    shape = f"{tag}_shape"
    if dpg.does_item_exist(shape):
        dpg.configure_item(shape, color=color, fill=color)


def hovered(tag: str) -> bool:
    return dpg.does_item_exist(tag) and dpg.is_item_hovered(tag)
