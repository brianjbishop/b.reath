"""
QR header icon.

The interesting case is recolouring: the finder squares are outlines and must
stay outlines through a hover, which is not something you can check by reading
the item back (see _parts).

No viewport here — the rest of the UI tests build items under a bare context
and never render.  Opening a real viewport in-process hangs the suite.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from breath_midi.ui.widgets.qr_icon import (
    HOVER,
    IDLE,
    _FINDERS,
    _MODULES,
    _parts,
    build_qr_icon,
    hovered,
    set_qr_color,
)

UNFILLED_ALPHA = -1.0  # what DPG reports for a rectangle drawn without fill


@pytest.fixture
def icon():
    dpg.create_context()
    with dpg.window(tag="root"):
        build_qr_icon("q", size=26)
    yield "q"
    dpg.destroy_context()


def test_draws_every_part(icon):
    """Three finders (ring + eye) plus the data modules."""
    children = dpg.get_item_children(icon, 2) or []
    assert len(children) == len(_FINDERS) * 2 + len(_MODULES)


def test_icon_is_square_at_the_requested_size(icon):
    cfg = dpg.get_item_configuration(icon)
    assert (cfg["width"], cfg["height"]) == (26, 26)


def test_finder_rings_stay_hollow_through_a_recolour(icon):
    """
    The regression this file exists for.

    DPG reports an unfilled rectangle's fill as alpha -1.0, which is truthy.
    Deciding fill by reading the item back therefore filled the rings on the
    first hover and turned the icon into three solid blocks.
    """
    ring = next(tag for tag, filled in _parts(icon) if not filled)

    set_qr_color(icon, HOVER)

    assert dpg.get_item_configuration(ring)["fill"][3] == UNFILLED_ALPHA
    assert dpg.get_item_configuration(ring)["color"][0] == pytest.approx(
        HOVER[0] / 255.0, abs=1e-3
    )


def test_filled_parts_follow_the_colour(icon):
    eye = next(tag for tag, filled in _parts(icon) if filled)

    set_qr_color(icon, HOVER)
    assert dpg.get_item_configuration(eye)["fill"][3] == pytest.approx(1.0)

    set_qr_color(icon, IDLE)
    assert dpg.get_item_configuration(eye)["fill"][0] == pytest.approx(
        IDLE[0] / 255.0, abs=1e-3
    )


def test_recolour_is_safe_when_the_icon_is_gone(icon):
    """Called every frame from the tab, including across a rebuild."""
    dpg.delete_item(icon)
    set_qr_color(icon, HOVER)


def test_hovered_is_false_when_the_icon_is_gone(icon):
    assert hovered("no_such_icon") is False
