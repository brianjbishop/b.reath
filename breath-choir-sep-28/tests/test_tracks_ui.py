"""
The transport row.

Four icons at the bottom left of the main column: load, save, stop, record.

Deliberately left-aligned and fixed. The previous attempt right-aligned them by
measuring a container while sizing that container's own contents, which fed back
on itself and walked the icons off the edge behind a scrollbar. A fixed row
cannot do that, and needs no per-frame measurement at all.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from breath_midi.ui.group_breath_tab import (
    TRANSPORT_ICONS,
    build_transport_row,
    refresh_transport,
)
from breath_midi.ui.widgets.transport_icons import IDLE, RECORDING


@pytest.fixture
def row():
    dpg.create_context()
    with dpg.window(tag="root"):
        build_transport_row()
    yield
    dpg.destroy_context()


def test_all_four_icons_exist(row):
    for tag in TRANSPORT_ICONS:
        assert dpg.does_item_exist(tag), tag


def test_icons_are_in_reading_order(row):
    children = dpg.get_item_children("gb_transport_row", 1)
    order = [
        dpg.get_item_alias(c)
        for c in children
        if dpg.get_item_alias(c) in TRANSPORT_ICONS
    ]
    assert order == list(TRANSPORT_ICONS)


def test_icons_are_the_same_size(row):
    sizes = {
        (dpg.get_item_configuration(t)["width"], dpg.get_item_configuration(t)["height"])
        for t in TRANSPORT_ICONS
    }
    assert len(sizes) == 1, f"icons differ in size: {sizes}"


def test_no_alignment_spacer_exists(row):
    """The push spacer was the feedback loop. It should be gone for good."""
    assert not dpg.does_item_exist("gb_transport_push")


def test_nothing_measures_a_container_to_place_the_row():
    """The regression guard: placement must not depend on measured geometry."""
    import inspect

    src = inspect.getsource(build_transport_row)
    for banned in ("get_viewport_client_width", "rect_size", "rect_min", "get_item_state"):
        assert banned not in src, f"{banned} is back in the transport row"


def test_record_icon_goes_red(row):
    refresh_transport(is_recording=True)
    fill = dpg.get_item_configuration("gb_track_record_shape")["fill"]
    assert fill[0] == pytest.approx(RECORDING[0] / 255.0, abs=1e-3)


def test_record_icon_returns_to_idle(row):
    refresh_transport(is_recording=True)
    refresh_transport(is_recording=False)
    fill = dpg.get_item_configuration("gb_track_record_shape")["fill"]
    assert fill[0] == pytest.approx(IDLE[0] / 255.0, abs=1e-3)


def test_refresh_is_safe_before_the_row_is_built():
    """Called every frame, including before the tab has been constructed."""
    dpg.create_context()
    refresh_transport(is_recording=False)
    dpg.destroy_context()
