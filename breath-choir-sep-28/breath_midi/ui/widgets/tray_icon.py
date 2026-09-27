"""
Import / export tray buttons.

Drawn rather than glyphs: an arrow into a tray for import, out of a tray for
export. DPG has no icon set, and the two need to be mirror images of each
other to read as a pair.

Placeholders — they do nothing yet, and say so on hover rather than looking
broken when clicked.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg

_SIZE = 26
_COLOR = (170, 170, 170, 255)


def tray_button(tag: str, into_tray: bool) -> None:
    """
    A small square icon: an arrow going into or out of a tray.

    No tooltip — DPG 2.3 cannot attach one to a drawlist, and attempting it
    corrupts the container stack rather than failing cleanly.
    """
    with dpg.drawlist(width=_SIZE, height=_SIZE, tag=tag):
        s = _SIZE
        # The tray: an open-topped box across the bottom third.
        left, right = s * 0.22, s * 0.78
        floor = s * 0.80
        lip = s * 0.60
        dpg.draw_line((left, lip), (left, floor), color=_COLOR, thickness=2)
        dpg.draw_line((left, floor), (right, floor), color=_COLOR, thickness=2)
        dpg.draw_line((right, floor), (right, lip), color=_COLOR, thickness=2)

        # The arrow: down into the tray for import, up out of it for export.
        mid_x = s * 0.5
        top, bottom = s * 0.14, s * 0.52
        if into_tray:
            dpg.draw_arrow((mid_x, bottom), (mid_x, top), color=_COLOR,
                           thickness=2, size=4)
        else:
            dpg.draw_arrow((mid_x, top), (mid_x, bottom), color=_COLOR,
                           thickness=2, size=4)
