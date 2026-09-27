"""
The preset row in the Detection panel.

The widget module owns no logic: it lists, loads and saves through callbacks,
because main_window is what holds the config and the store. These tests pin that
boundary — the row calls back with the right name, and builds fine without any
preset wiring at all.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from breath_midi.ui.widgets import knob as K
from breath_midi.ui.widgets.hold_controls import build_hold_controls

KNOB_TAGS = (
    "ui_inhale_exit_delta", "ui_exhale_exit_delta", "ui_hold_exit_delta",
    "ui_hold_still_tol", "ui_min_hold_ms",
    "ui_hold_peak_band", "ui_hold_valley_band",
)


@pytest.fixture
def calls():
    return {"loaded": [], "saved": [], "names": ["hive show", "rehearsal"]}


@pytest.fixture
def panel(calls):
    dpg.create_context()
    K._reset_for_tests()
    with dpg.window(tag="root"):
        build_hold_controls(
            lambda *_: None,
            preset_names=lambda: calls["names"],
            on_preset_load=calls["loaded"].append,
            on_preset_save=calls["saved"].append,
        )
    yield calls
    dpg.destroy_context()
    K._reset_for_tests()


def test_preset_widgets_exist(panel):
    for tag in ("ui_preset_combo", "ui_preset_name", "ui_preset_save"):
        assert dpg.does_item_exist(tag), tag


def test_combo_is_populated_from_the_callback(panel):
    assert dpg.get_item_configuration("ui_preset_combo")["items"] == [
        "hive show", "rehearsal"
    ]


def test_choosing_a_preset_loads_it_by_name(panel):
    dpg.set_value("ui_preset_combo", "rehearsal")
    dpg.get_item_callback("ui_preset_combo")()
    assert panel["loaded"] == ["rehearsal"]


def test_save_uses_the_typed_name(panel):
    dpg.set_value("ui_preset_name", "hive show 2")
    dpg.get_item_callback("ui_preset_save")()
    assert panel["saved"] == ["hive show 2"]


def test_save_clears_the_field_and_refreshes_the_list(panel):
    panel["names"] = ["hive show", "rehearsal", "new one"]
    dpg.set_value("ui_preset_name", "new one")
    dpg.get_item_callback("ui_preset_save")()
    assert dpg.get_value("ui_preset_name") == ""
    assert "new one" in dpg.get_item_configuration("ui_preset_combo")["items"]


def test_blank_name_saves_nothing(panel):
    dpg.set_value("ui_preset_name", "   ")
    dpg.get_item_callback("ui_preset_save")()
    assert panel["saved"] == []


def test_all_seven_knobs_still_build(panel):
    for tag in KNOB_TAGS:
        assert dpg.does_item_exist(tag), tag
    assert dpg.does_item_exist("ui_hold_enabled")


def test_builds_without_any_preset_wiring():
    """The panel must still work for callers that pass no preset callbacks."""
    dpg.create_context()
    K._reset_for_tests()
    with dpg.window(tag="root"):
        build_hold_controls(lambda *_: None)
    assert not dpg.does_item_exist("ui_preset_combo")
    for tag in KNOB_TAGS:
        assert dpg.does_item_exist(tag), tag
    dpg.destroy_context()
    K._reset_for_tests()
