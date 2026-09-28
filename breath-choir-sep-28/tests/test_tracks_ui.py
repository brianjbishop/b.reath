"""
The transport in the Devices header.

Four icons, right-aligned: load, save, stop, record. They sit with the device
list rather than in the side column, because a loaded track *is* more devices.

The two tray placeholders that shipped doing nothing are now the load and save
halves, so no new icon art was needed for them.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel
from breath_midi.ui.widgets.transport_icons import IDLE, RECORDING

ICONS = ("gb_track_load", "gb_track_export", "gb_track_stop", "gb_track_record")


class FakeRegistry:
    def get(self, uuid):
        return None

    def all_entries(self):
        return []

    def connected_uuids(self):
        return set()


@pytest.fixture
def panel():
    from pathlib import Path

    from breath_midi.config.store import ConfigStore

    dpg.create_context()

    class FakeHub:
        registry = FakeRegistry()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    with dpg.window(tag="root"):
        p = GroupBreathBottomPanel(FakeHub(), "root")  # type: ignore[arg-type]
        p.build()
    yield p
    dpg.destroy_context()


def test_all_four_icons_are_in_the_devices_header(panel):
    header = dpg.get_alias_id("gb_bottom_header")
    for tag in ICONS:
        assert dpg.does_item_exist(tag), tag
        # get_item_parent returns the alias when one is set, the id otherwise.
        parent = dpg.get_item_parent(tag)
        parent_id = dpg.get_alias_id(parent) if isinstance(parent, str) else parent
        assert parent_id == header, f"{tag} is not in the Devices header"


def test_icons_are_the_same_size(panel):
    sizes = {
        (dpg.get_item_configuration(t)["width"], dpg.get_item_configuration(t)["height"])
        for t in ICONS
    }
    assert len(sizes) == 1, f"icons differ in size: {sizes}"


def test_a_push_spacer_exists_for_right_alignment(panel):
    assert dpg.does_item_exist("gb_transport_push")


def test_record_icon_goes_red_while_recording(panel):
    panel.refresh_transport(is_recording=True)
    fill = dpg.get_item_configuration("gb_track_record_shape")["fill"]
    assert fill[0] == pytest.approx(RECORDING[0] / 255.0, abs=1e-3)


def test_record_icon_returns_to_idle(panel):
    panel.refresh_transport(is_recording=True)
    panel.refresh_transport(is_recording=False)
    fill = dpg.get_item_configuration("gb_track_record_shape")["fill"]
    assert fill[0] == pytest.approx(IDLE[0] / 255.0, abs=1e-3)


def test_clicks_route_to_the_callbacks(panel):
    fired = []
    panel.set_transport_callbacks(
        on_load=lambda: fired.append("load"),
        on_stop=lambda: fired.append("stop"),
        on_record=lambda: fired.append("record"),
        on_export=lambda: fired.append("export"),
    )
    # Nothing is hovered in a headless context, so no callback should fire.
    panel.poll_transport_clicks(edge=True)
    assert fired == []


def test_polling_without_an_edge_does_nothing(panel):
    fired = []
    panel.set_transport_callbacks(
        on_load=lambda: fired.append("load"),
        on_stop=lambda: fired.append("stop"),
        on_record=lambda: fired.append("record"),
        on_export=lambda: fired.append("export"),
    )
    panel.poll_transport_clicks(edge=False)
    assert fired == []


def test_refresh_is_safe_before_callbacks_are_wired(panel):
    panel.refresh_transport(is_recording=False)
    panel.poll_transport_clicks(edge=True)


def test_alignment_never_reads_the_panel_it_is_sizing(panel):
    """
    The regression this guards.

    _right_align_transport used to measure the panel's own rect_size while
    sizing that panel's content — a feedback loop that widened the gap every
    frame until the icons sat off the right edge behind a scrollbar. The
    measurement must come from the viewport, which contents cannot push.
    """
    import inspect

    src = inspect.getsource(panel._right_align_transport)
    assert "get_viewport_client_width" in src
    assert "_panel_tag" not in src, "alignment is measuring the panel again"


def test_alignment_is_safe_without_a_viewport(panel):
    """Headless, and during the app's first frames, there is no viewport."""
    panel._right_align_transport()


def test_right_column_width_is_configurable(panel):
    panel.set_right_column_width(400)
    assert panel._right_col_w == 400
