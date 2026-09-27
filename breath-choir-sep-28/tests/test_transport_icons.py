"""Stop and record icons."""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from breath_midi.ui.widgets.transport_icons import (
    HOVER,
    IDLE,
    RECORDING,
    build_record_icon,
    build_stop_icon,
    hovered,
    set_icon_color,
)


@pytest.fixture
def ctx():
    dpg.create_context()
    with dpg.window(tag="root"):
        build_stop_icon("stop")
        build_record_icon("rec")
    yield
    dpg.destroy_context()


def test_both_icons_build(ctx):
    assert dpg.does_item_exist("stop") and dpg.does_item_exist("rec")


def test_icons_are_square_at_the_requested_size(ctx):
    for tag in ("stop", "rec"):
        cfg = dpg.get_item_configuration(tag)
        assert (cfg["width"], cfg["height"]) == (26, 26)


def test_record_goes_red(ctx):
    set_icon_color("rec", RECORDING)
    fill = dpg.get_item_configuration("rec_shape")["fill"]
    assert fill[0] == pytest.approx(RECORDING[0] / 255.0, abs=1e-3)


def test_colour_returns_to_idle(ctx):
    set_icon_color("rec", RECORDING)
    set_icon_color("rec", IDLE)
    fill = dpg.get_item_configuration("rec_shape")["fill"]
    assert fill[0] == pytest.approx(IDLE[0] / 255.0, abs=1e-3)


def test_stop_brightens_on_hover(ctx):
    set_icon_color("stop", HOVER)
    fill = dpg.get_item_configuration("stop_shape")["fill"]
    assert fill[0] == pytest.approx(HOVER[0] / 255.0, abs=1e-3)


def test_recolour_is_safe_when_the_icon_is_gone(ctx):
    dpg.delete_item("rec")
    set_icon_color("rec", RECORDING)


def test_hovered_is_false_for_a_missing_icon(ctx):
    assert hovered("nope") is False
