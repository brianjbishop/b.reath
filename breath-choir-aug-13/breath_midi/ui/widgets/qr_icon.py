"""
QR code icon — opens the join-the-network popup.

Drawn on a 7x7 module grid rather than glyphed, for the same reason as the
Wi-Fi icon: DPG ships no icon set, and a text character cannot be scaled or
recoloured cleanly. Three finder squares in the corners is the minimum that
reads unmistakably as a QR code at 26px.

It brightens on hover, since unlike the Wi-Fi icon its colour carries no state
and hover is the only affordance saying it can be clicked.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg

IDLE = (150, 150, 150, 255)
HOVER = (230, 230, 230, 255)

# 7x7 grid: finders are 3x3 blocks at three corners, leaving a 3x3 data
# quadrant at the bottom right.
_GRID = 7
_FINDERS = ((0, 0), (4, 0), (0, 4))
_MODULES = ((4, 4), (6, 4), (5, 5), (4, 6), (6, 6))


def _parts(prefix: str) -> list[tuple[str, bool]]:
    """
    Every drawn part, paired with whether it is filled.

    Fill has to be tracked here rather than read back from the item, because
    DPG reports an unfilled rectangle's fill alpha as -1.0 — truthy in Python.
    Testing it at recolour time flooded the three finder rings solid on the
    first hover.  The geometry is fixed, so which parts are filled is knowable
    without asking.
    """
    out: list[tuple[str, bool]] = []
    i = 0
    for _ in _FINDERS:
        out.append((f"{prefix}_p{i}", False))   # outer ring, outline only
        out.append((f"{prefix}_p{i + 1}", True))  # the eye at its centre
        i += 2
    for _ in _MODULES:
        out.append((f"{prefix}_p{i}", True))
        i += 1
    return out


def build_qr_icon(prefix: str, size: int = 26, color=IDLE) -> None:
    """Draw the icon in the current container. `prefix` also tags the drawlist."""
    m = size / _GRID
    tags = iter(t for t, _ in _parts(prefix))

    with dpg.drawlist(width=size, height=size, tag=prefix):
        for gx, gy in _FINDERS:
            x, y = gx * m, gy * m
            dpg.draw_rectangle(
                (x, y), (x + 3 * m, y + 3 * m),
                color=color, thickness=max(1.5, m * 0.55), tag=next(tags),
            )
            dpg.draw_rectangle(
                (x + m, y + m), (x + 2 * m, y + 2 * m),
                color=color, fill=color, tag=next(tags),
            )
        for gx, gy in _MODULES:
            x, y = gx * m, gy * m
            dpg.draw_rectangle(
                (x, y), (x + m, y + m),
                color=color, fill=color, tag=next(tags),
            )


def set_qr_color(prefix: str, color) -> None:
    """Recolour in place. Safe to call every frame."""
    for tag, filled in _parts(prefix):
        if not dpg.does_item_exist(tag):
            continue
        if filled:
            dpg.configure_item(tag, color=color, fill=color)
        else:
            dpg.configure_item(tag, color=color)


def hovered(prefix: str) -> bool:
    return dpg.does_item_exist(prefix) and dpg.is_item_hovered(prefix)
