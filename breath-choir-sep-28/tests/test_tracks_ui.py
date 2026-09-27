"""
The Tracks row.

Two tray placeholders already existed and did nothing: an arrow into a tray and
an arrow out of one. They map onto the two real jobs — import becomes load,
export becomes save a recording — so no new icons are needed. The export icon
must survive this task even though nothing wires it until recording lands.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from breath_midi.ui.group_breath_tab import build_track_row, set_track_list


@pytest.fixture
def row():
    dpg.create_context()
    calls = {"load": 0, "stop": 0}
    with dpg.window(tag="root"):
        build_track_row(
            on_load=lambda: calls.__setitem__("load", calls["load"] + 1),
            on_stop=lambda: calls.__setitem__("stop", calls["stop"] + 1),
        )
    yield calls
    dpg.destroy_context()


def test_has_load_stop_and_a_list(row):
    for tag in ("gb_track_load", "gb_track_stop", "gb_track_list"):
        assert dpg.does_item_exist(tag), tag


def test_export_placeholder_survives_for_recording(row):
    """Recording wires this icon. Deleting it here breaks that task."""
    assert dpg.does_item_exist("gb_track_export")


def test_list_starts_empty(row):
    assert dpg.get_value("gb_track_list") == ""


def test_stop_button_calls_back(row):
    dpg.get_item_callback("gb_track_stop")()
    assert row["stop"] == 1


def test_set_track_list_shows_names(row):
    set_track_list(["Group of four", "Dropout"])
    assert dpg.get_value("gb_track_list") == "Group of four, Dropout"


def test_set_track_list_clears(row):
    set_track_list(["Group of four"])
    set_track_list([])
    assert dpg.get_value("gb_track_list") == ""


def test_set_track_list_is_safe_with_no_row():
    """Called every frame from update(); must not raise before the row exists."""
    dpg.create_context()
    set_track_list(["anything"])
    dpg.destroy_context()
