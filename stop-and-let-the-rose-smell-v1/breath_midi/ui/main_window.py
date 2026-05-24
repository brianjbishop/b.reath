"""
Breath → MIDI controller UI (Dear PyGui only — same toolkit family as totem_receiver).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import replace

from bleak import BleakClient, BleakScanner  # noqa: F401

import dearpygui.dearpygui as dpg

from breath_midi.config.model import (
    ConfigModel,
    ConsistentBreathsTriggerConfig,
    ExhaleOnsetTriggerConfig,
    InhaleOnsetTriggerConfig,
    SustainTriggerConfig,
    TriggersConfig,
    UiConfig,
)
from breath_midi.config.store import ConfigStore
from breath_midi.midi.activity_bus import MidiActivityBus, MidiActivityEvent
from breath_midi.midi.mido_sink import MidoMidiSink
from breath_midi.runtime import ControllerRuntime
from breath_midi.types import TriggerEvent
from breath_midi.ui.midi_activity import MidiActivityVisualizer, labels_for_note
from breath_midi.ui.window_placement import (
    centered_position_on_primary,
    viewport_restored_position_is_valid,
)

WINDOW_SECONDS = 15.0

# Fixed side column widths; center column width is set explicitly each layout pass.
# Dear PyGui horizontal layout: a child_window with width=-1 before a fixed sibling
# often absorbs all width, so the right panel gets no space even when show=True.
_LEFT_PANEL_W = 400
_RIGHT_PANEL_W = 380
_LAYOUT_H_GAP = 32
_MIN_SIDE_PANEL_W = 180
_MIN_CENTER_PANEL_W = 280


def run_ui(
    runtime: ControllerRuntime, store: ConfigStore, midi_bus: MidiActivityBus
) -> None:
    BreathMidiDpgUI(runtime, store, midi_bus).run()


class BreathMidiDpgUI:
    def __init__(
        self,
        runtime: ControllerRuntime,
        store: ConfigStore,
        midi_bus: MidiActivityBus,
    ) -> None:
        self.runtime = runtime
        self.store = store
        self._midi_bus = midi_bus
        self._midi_viz: MidiActivityVisualizer | None = None
        self._midi_log_entries: deque[tuple[float, str]] = deque(maxlen=80)
        self._autosave = True
        self._loading = False
        self._reload_busy = False
        self._ui_persist_deadline: float | None = None
        self._panel_left_w = _LEFT_PANEL_W
        self._panel_right_w = _RIGHT_PANEL_W

    def _cb(self, *args) -> None:
        if not self._loading:
            self.apply_from_ui()

    def run(self) -> None:
        dpg.create_context()
        ui0 = self.runtime.config.ui
        ww = int(ui0.window_width)
        wh = int(ui0.window_height)
        wx, wy = int(ui0.window_x), int(ui0.window_y)
        if wx >= 0 and wy >= 0:
            if not viewport_restored_position_is_valid(wx, wy, ww, wh):
                wx, wy = centered_position_on_primary(ww, wh)
                new_ui = replace(ui0, window_x=wx, window_y=wy)
                self.runtime.config = replace(self.runtime.config, ui=new_ui)

        dpg.create_viewport(
            title="Breath → MIDI Controller",
            width=ww,
            height=wh,
        )
        dpg.set_viewport_min_width(960)
        dpg.set_viewport_min_height(600)
        if wx >= 0 and wy >= 0:
            dpg.set_viewport_pos([wx, wy])
        dpg.setup_dearpygui()
        self._build()
        dpg.set_viewport_resize_callback(lambda *_: self._on_viewport_resize())
        dpg.show_viewport()
        self._layout_main_to_viewport()
        self.load_into_ui(self.runtime.config)
        # Auto-start once init completes (same end state as after Reload).
        self.runtime.start()
        self._sync_start_stop_buttons()

        while dpg.is_dearpygui_running():
            self._flush_ui_persist()
            self.tick()
            dpg.render_dearpygui_frame()
            time.sleep(0.016)

        if self._ui_persist_deadline is not None:
            self._ui_persist_deadline = None
            self._persist_viewport_to_config()

        try:
            dpg.destroy_context()
        except Exception:
            pass

    def _build(self) -> None:
        with dpg.window(
            label="Breath → MIDI Controller",
            tag="win_main",
            no_title_bar=True,
            no_resize=False,
            pos=(0, 0),
        ):
            with dpg.group(horizontal=True):
                with dpg.child_window(
                    tag="panel_left",
                    width=_LEFT_PANEL_W,
                    height=-1,
                    border=True,
                    resizable_x=True,
                ):
                    with dpg.child_window(width=-1, height=-1, border=False):
                        dpg.add_text("Live Monitor", color=(220, 220, 160))
                        dpg.add_separator()
                        dpg.add_text("Amplitude: 0.0000", tag="mon_amp")
                        dpg.add_text("Phase: rest", tag="mon_phase")
                        dpg.add_text("Source: --", tag="mon_src")
                        dpg.add_text("dA/dt: 0.0000", tag="mon_deriv")
                        dpg.add_text("Cycle: --", tag="mon_cycle")
                        dpg.add_text("Rolling avg: --", tag="mon_roll")
                        dpg.add_text("Consistent: 0/0 (idle)", tag="mon_consistent")
                        dpg.add_text("Connection: --", tag="mon_conn")
                        dpg.add_spacer(height=8)
                        dpg.add_text("Trigger activity (~1.5s)", color=(220, 220, 160))
                        dpg.add_input_text(
                            tag="mon_triggers",
                            multiline=True,
                            readonly=True,
                            height=120,
                            width=-1,
                            default_value="",
                        )
                        dpg.add_spacer(height=6)
                        dpg.add_text("MIDI activity", color=(220, 220, 160))
                        grp_midi_viz = dpg.add_group(tag="midi_viz_root")
                        self._midi_viz = MidiActivityVisualizer(grp_midi_viz)

                with dpg.child_window(
                    tag="panel_center",
                    width=520,
                    height=-1,
                    border=True,
                    resizable_x=True,
                ):
                    with dpg.group(horizontal=True):
                        dpg.add_checkbox(
                            label="Left panel",
                            tag="chk_panel_left",
                            default_value=True,
                            callback=self._on_panel_left_toggle,
                        )
                        dpg.add_checkbox(
                            label="Right panel",
                            tag="chk_panel_right",
                            default_value=True,
                            callback=self._on_panel_right_toggle,
                        )

                    with dpg.group(horizontal=True):
                        dpg.add_text("Input:", color=(180, 180, 180))

                        def _on_viewer_mode_change(_s, app_data, _u):
                            if isinstance(app_data, int):
                                mode = "ble" if app_data == 0 else "osc"
                            else:
                                mode = "ble" if str(app_data).lower().strip() == "ble" else "osc"
                            dpg.set_value("ui_input_mode", mode)
                            self._cb()

                        dpg.add_radio_button(
                            items=["ble", "osc"],
                            default_value="osc",
                            horizontal=True,
                            tag="viewer_mode",
                            callback=_on_viewer_mode_change,
                        )

                        dpg.add_spacer(width=12)
                        dpg.add_text("Status:", color=(180, 180, 180))
                        dpg.add_text("--", tag="viewer_status")
                        dpg.add_spacer(width=12)
                        dpg.add_text("RX:", color=(180, 180, 180))
                        dpg.add_text("--", tag="viewer_rx")

                    with dpg.group(horizontal=True):
                        with dpg.group(horizontal=True, tag="viewer_ble_row"):
                            dpg.add_button(label="Scan", callback=lambda: self._ble_scan(), tag="viewer_ble_scan")
                            dpg.add_combo([], width=250, tag="viewer_ble_combo")
                            dpg.add_button(
                                label="Connect",
                                callback=lambda: self._ble_connect_btn(from_viewer=True),
                                tag="viewer_ble_connect",
                            )

                        with dpg.group(horizontal=True, tag="viewer_osc_row"):
                            dpg.add_text("Port:", color=(180, 180, 180))
                            dpg.add_input_int(
                                tag="viewer_osc_port",
                                width=90,
                                min_value=1,
                                max_value=65535,
                                default_value=8000,
                                callback=lambda *_: self._sync_viewer_osc_port(),
                            )
                            dpg.add_button(label="Listen (OSC)", callback=lambda: self._osc_listen(), tag="viewer_osc_listen")
                            dpg.add_button(label="Stop OSC", callback=lambda: self._osc_stop(), tag="viewer_osc_stop")

                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_text("Source:", color=(180, 180, 180))
                        dpg.add_text("--", tag="viewer_source")
                        dpg.add_spacer(width=12)
                        dpg.add_text("Breath:", color=(180, 180, 180))
                        dpg.add_text("0.0000", tag="viewer_value")

                    with dpg.plot(label="Breath (processed)", height=-1, width=-1):
                        dpg.add_plot_legend()
                        dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="plot_xaxis")
                        dpg.add_plot_axis(dpg.mvYAxis, label="Breath (processed)", tag="plot_yaxis")
                        dpg.set_axis_limits("plot_yaxis", -0.05, 1.05)
                        dpg.add_line_series([], [], label="breath", parent="plot_yaxis", tag="plot_series")

                with dpg.child_window(
                    tag="panel_right",
                    width=_RIGHT_PANEL_W,
                    height=-1,
                    border=True,
                    resizable_x=True,
                ):
                    with dpg.group(horizontal=True):
                        dpg.add_checkbox(
                            label="Auto-save",
                            default_value=True,
                            tag="ui_autosave",
                            callback=self._on_autosave_toggle,
                        )
                        dpg.add_spacer(width=8)
                        dpg.add_button(label="Start", tag="btn_start", callback=lambda: self._on_start())
                        dpg.add_button(label="Stop", tag="btn_stop", callback=lambda: self._on_stop())
                        dpg.add_spacer(width=8)
                        dpg.add_button(label="Reload", tag="btn_reload", callback=lambda: self.reload())
                        dpg.add_button(label="Save now", callback=lambda: self.save_now())

                    with dpg.child_window(width=-1, height=-1, border=False):
                        with dpg.tab_bar():
                            with dpg.tab(label="Input"):
                                self._build_tab_input()
                            with dpg.tab(label="Detection"):
                                self._build_tab_detection()
                            with dpg.tab(label="MIDI"):
                                self._build_tab_midi()
                            with dpg.tab(label="Triggers"):
                                self._build_tab_triggers()

        with dpg.item_handler_registry(tag="ih_rz_left"):
            dpg.add_item_resize_handler(callback=lambda *a: self._on_panel_split_resize())
        with dpg.item_handler_registry(tag="ih_rz_center"):
            dpg.add_item_resize_handler(callback=lambda *a: self._on_panel_split_resize())
        with dpg.item_handler_registry(tag="ih_rz_right"):
            dpg.add_item_resize_handler(callback=lambda *a: self._on_panel_split_resize())
        dpg.bind_item_handler_registry("panel_left", "ih_rz_left")
        dpg.bind_item_handler_registry("panel_center", "ih_rz_center")
        dpg.bind_item_handler_registry("panel_right", "ih_rz_right")

    def _build_tab_input(self) -> None:
        dpg.add_text("Input mode")
        dpg.add_combo(
            items=["osc", "ble"],
            tag="ui_input_mode",
            width=120,
            callback=self._cb,
        )
        dpg.add_text("OSC port")
        dpg.add_input_int(
            tag="ui_osc_port",
            width=120,
            min_value=1,
            max_value=65535,
            default_value=8000,
            callback=self._cb,
        )
        dpg.add_text("Source filter (all or device UUID)")
        dpg.add_input_text(tag="ui_source_filter", width=-1, callback=self._cb)

        dpg.add_separator()
        dpg.add_text("Bluetooth", color=(180, 180, 180))
        with dpg.group(horizontal=True, tag="grp_ble_io"):
            dpg.add_button(label="Scan", callback=lambda: self._ble_scan())
            dpg.add_combo([], width=280, tag="dpg_ble_combo")
            dpg.add_button(
                label="Connect",
                callback=lambda: self._ble_connect_btn(from_viewer=False),
                tag="dpg_ble_connect_btn",
            )

        dpg.add_text("OSC actions", color=(180, 180, 180))
        with dpg.group(horizontal=True, tag="grp_osc_io"):
            dpg.add_button(label="Listen (OSC)", callback=lambda: self._osc_listen())
            dpg.add_button(label="Stop OSC", callback=lambda: self._osc_stop())

    def _build_tab_detection(self) -> None:
        dpg.add_text("Smoothing alpha")
        dpg.add_input_float(
            tag="ui_smooth",
            width=140,
            default_value=0.25,
            min_value=0.01,
            max_value=0.99,
            format="%.3f",
            callback=self._cb,
        )
        dpg.add_text("Deadzone")
        dpg.add_input_float(
            tag="ui_deadzone",
            width=140,
            default_value=0.02,
            min_value=0.0,
            max_value=0.5,
            format="%.4f",
            callback=self._cb,
        )
        dpg.add_text("Gain")
        dpg.add_input_float(
            tag="ui_gain",
            width=140,
            default_value=1.0,
            min_value=0.1,
            max_value=10.0,
            format="%.2f",
            callback=self._cb,
        )
        dpg.add_text("Inhale enter amp")
        dpg.add_input_float(
            tag="ui_inh_enter",
            width=140,
            default_value=0.08,
            min_value=0.0,
            max_value=1.0,
            format="%.3f",
            callback=self._cb,
        )
        dpg.add_text("Exhale enter amp")
        dpg.add_input_float(
            tag="ui_exh_enter",
            width=140,
            default_value=0.08,
            min_value=0.0,
            max_value=1.0,
            format="%.3f",
            callback=self._cb,
        )
        dpg.add_text("Rest enter amp")
        dpg.add_input_float(
            tag="ui_rest_enter",
            width=140,
            default_value=0.04,
            min_value=0.0,
            max_value=1.0,
            format="%.3f",
            callback=self._cb,
        )
        dpg.add_text("Slope enter epsilon (abs dA/dt)")
        dpg.add_input_float(
            tag="ui_slope_enter",
            width=140,
            default_value=0.08,
            min_value=0.0,
            max_value=5.0,
            format="%.3f",
            callback=self._cb,
        )
        dpg.add_text("Slope flat epsilon for REST (abs dA/dt)")
        dpg.add_input_float(
            tag="ui_slope_rest",
            width=140,
            default_value=0.03,
            min_value=0.0,
            max_value=5.0,
            format="%.3f",
            callback=self._cb,
        )
        dpg.add_text("Hysteresis")
        dpg.add_input_float(
            tag="ui_hysteresis",
            width=140,
            default_value=0.02,
            min_value=0.0,
            max_value=0.5,
            format="%.3f",
            callback=self._cb,
        )
        dpg.add_text("Min phase (ms)")
        dpg.add_input_int(
            tag="ui_min_phase_ms",
            width=140,
            min_value=0,
            max_value=2000,
            default_value=120,
            callback=self._cb,
        )

    def _build_tab_midi(self) -> None:
        with dpg.group(horizontal=True):
            dpg.add_combo([], tag="ui_midi_port", width=360, callback=self._cb)
            dpg.add_button(label="Refresh ports", callback=lambda: self.refresh_midi_ports(True))
        dpg.add_text("Channel (0–15)")
        dpg.add_input_int(
            tag="ui_midi_ch", width=100, min_value=0, max_value=15, default_value=0, callback=self._cb
        )
        dpg.add_text("Default velocity")
        dpg.add_input_int(
            tag="ui_midi_vel",
            width=100,
            min_value=0,
            max_value=127,
            default_value=100,
            callback=self._cb,
        )
        dpg.add_text("CC rate (Hz)")
        dpg.add_input_int(
            tag="ui_cc_rate",
            width=100,
            min_value=1,
            max_value=200,
            default_value=30,
            callback=self._cb,
        )

    def _build_tab_triggers(self) -> None:
        dpg.add_text("Onsets", color=(220, 220, 160))
        dpg.add_text("Inhale onset enabled")
        dpg.add_checkbox(tag="ui_inh_on_en", default_value=True, callback=self._cb)
        dpg.add_text("Inhale note / velocity / debounce ms")
        with dpg.group(horizontal=True):
            dpg.add_input_int(
                tag="ui_inh_on_note",
                width=70,
                min_value=0,
                max_value=127,
                default_value=60,
                callback=self._cb,
            )
            dpg.add_input_int(
                tag="ui_inh_on_vel",
                width=70,
                min_value=0,
                max_value=127,
                default_value=100,
                callback=self._cb,
            )
            dpg.add_input_int(
                tag="ui_inh_on_db",
                width=90,
                min_value=0,
                max_value=2000,
                default_value=200,
                callback=self._cb,
            )
        dpg.add_text("Exhale onset enabled")
        dpg.add_checkbox(tag="ui_exh_on_en", default_value=True, callback=self._cb)
        dpg.add_text("Exhale note / velocity / debounce ms")
        with dpg.group(horizontal=True):
            dpg.add_input_int(
                tag="ui_exh_on_note",
                width=70,
                min_value=0,
                max_value=127,
                default_value=62,
                callback=self._cb,
            )
            dpg.add_input_int(
                tag="ui_exh_on_vel",
                width=70,
                min_value=0,
                max_value=127,
                default_value=100,
                callback=self._cb,
            )
            dpg.add_input_int(
                tag="ui_exh_on_db",
                width=90,
                min_value=0,
                max_value=2000,
                default_value=200,
                callback=self._cb,
            )

        dpg.add_separator()
        dpg.add_text("Sustain CC", color=(220, 220, 160))
        dpg.add_text("Inhale sustain enabled")
        dpg.add_checkbox(tag="ui_inh_cc_en", default_value=True, callback=self._cb)
        dpg.add_text("Inhale CC#")
        dpg.add_input_int(
            tag="ui_inh_cc_num", width=80, min_value=0, max_value=127, default_value=1, callback=self._cb
        )
        dpg.add_text("Exhale sustain enabled")
        dpg.add_checkbox(tag="ui_exh_cc_en", default_value=True, callback=self._cb)
        dpg.add_text("Exhale CC#")
        dpg.add_input_int(
            tag="ui_exh_cc_num", width=80, min_value=0, max_value=127, default_value=2, callback=self._cb
        )

        dpg.add_separator()
        dpg.add_text("Consistent breaths", color=(220, 220, 160))
        dpg.add_checkbox(tag="ui_cons_en", default_value=False, callback=self._cb)
        dpg.add_text("N breaths")
        dpg.add_input_int(tag="ui_cons_n", width=80, min_value=1, max_value=50, default_value=4, callback=self._cb)
        dpg.add_text("Period tol (rel) / Peak tol (abs)")
        with dpg.group(horizontal=True):
            dpg.add_input_float(
                tag="ui_cons_ptol",
                width=100,
                min_value=0.0,
                max_value=1.0,
                format="%.3f",
                default_value=0.15,
                callback=self._cb,
            )
            dpg.add_input_float(
                tag="ui_cons_ktol",
                width=100,
                min_value=0.0,
                max_value=1.0,
                format="%.3f",
                default_value=0.12,
                callback=self._cb,
            )
        dpg.add_text("Note / velocity")
        with dpg.group(horizontal=True):
            dpg.add_input_int(
                tag="ui_cons_note",
                width=70,
                min_value=0,
                max_value=127,
                default_value=64,
                callback=self._cb,
            )
            dpg.add_input_int(
                tag="ui_cons_vel",
                width=70,
                min_value=0,
                max_value=127,
                default_value=100,
                callback=self._cb,
            )

    def _on_autosave_toggle(self, s, a, u) -> None:
        self._autosave = bool(dpg.get_value("ui_autosave"))

    def _sync_viewer_osc_port(self) -> None:
        dpg.set_value("ui_osc_port", int(dpg.get_value("viewer_osc_port")))
        self._cb()

    def _resolve_main_inner_width(self, main_inner_width: int | None) -> int | None:
        if main_inner_width is not None and main_inner_width > 0:
            return int(main_inner_width)
        try:
            r = dpg.get_available_content_region("win_main")
            if r and len(r) >= 1 and r[0] > 0:
                return int(r[0])
            rs = dpg.get_item_rect_size("win_main")
            if rs and len(rs) >= 1 and rs[0] > 0:
                return int(rs[0])
            cw = int(dpg.get_viewport_client_width())
            if cw > 0:
                return cw
        except Exception:
            pass
        return None

    def _capture_panel_widths_from_ui(self) -> None:
        try:
            if bool(dpg.get_value("chk_panel_left")):
                r = dpg.get_item_rect_size("panel_left")
                if r and len(r) >= 1 and r[0] > 0:
                    self._panel_left_w = max(_MIN_SIDE_PANEL_W, int(r[0]))
            if bool(dpg.get_value("chk_panel_right")):
                r = dpg.get_item_rect_size("panel_right")
                if r and len(r) >= 1 and r[0] > 0:
                    self._panel_right_w = max(_MIN_SIDE_PANEL_W, int(r[0]))
        except Exception:
            pass

    def _on_panel_split_resize(self, *args: object) -> None:
        self._capture_panel_widths_from_ui()
        self._sync_three_column_widths()

    def _sync_three_column_widths(self, main_inner_width: int | None = None) -> None:
        try:
            main_inner_width = self._resolve_main_inner_width(main_inner_width)
            if main_inner_width is None or main_inner_width <= 0:
                return
            left_on = bool(dpg.get_value("chk_panel_left"))
            right_on = bool(dpg.get_value("chk_panel_right"))
            left_w = self._panel_left_w if left_on else 0
            right_w = self._panel_right_w if right_on else 0
            center_w = int(main_inner_width) - left_w - right_w - _LAYOUT_H_GAP
            center_w = max(_MIN_CENTER_PANEL_W, center_w)
            dpg.configure_item("panel_center", width=center_w)
        except Exception:
            pass

    def _layout_main_to_viewport(self) -> None:
        try:
            cw = dpg.get_viewport_client_width()
            ch = dpg.get_viewport_client_height()
            if cw > 0 and ch > 0:
                dpg.configure_item("win_main", width=cw, height=ch)
                self._sync_three_column_widths(cw)
        except Exception:
            pass

    def _on_viewport_resize(self) -> None:
        self._layout_main_to_viewport()
        self._ui_persist_deadline = time.monotonic() + 0.5

    def _flush_ui_persist(self) -> None:
        if self._ui_persist_deadline is None:
            return
        if time.monotonic() < self._ui_persist_deadline:
            return
        self._ui_persist_deadline = None
        self._persist_viewport_to_config()

    def _persist_viewport_to_config(self) -> None:
        try:
            w = int(dpg.get_viewport_width())
            h = int(dpg.get_viewport_height())
            pos = dpg.get_viewport_pos()
            px, py = int(pos[0]), int(pos[1])
            left_open = bool(dpg.get_value("chk_panel_left"))
            right_open = bool(dpg.get_value("chk_panel_right"))
            u0 = self.runtime.config.ui
            new_ui = UiConfig(
                window_width=w,
                window_height=h,
                window_x=px,
                window_y=py,
                left_panel_open=left_open,
                right_panel_open=right_open,
                midi_activity=u0.midi_activity,
            )
            self.runtime.config = replace(self.runtime.config, ui=new_ui)
            self._maybe_autosave_ui()
        except Exception:
            pass

    def _maybe_autosave_ui(self) -> None:
        if not self._autosave:
            return
        try:
            self.store.save(self.runtime.config)
        except Exception:
            pass

    def _sync_start_stop_buttons(self) -> None:
        if self._reload_busy:
            dpg.configure_item("btn_start", enabled=False)
            dpg.configure_item("btn_stop", enabled=False)
            return
        running = self.runtime.is_running()
        dpg.configure_item("btn_start", enabled=not running)
        dpg.configure_item("btn_stop", enabled=running)

    def _clear_plot_and_monitor(self) -> None:
        self._midi_bus.drain()
        self._midi_log_entries.clear()
        if self._midi_viz is not None:
            self._midi_viz.reset_state()
        dpg.set_value("plot_series", [[], []])
        dpg.set_axis_limits("plot_xaxis", 0.0, WINDOW_SECONDS)
        dpg.set_axis_limits("plot_yaxis", -0.05, 1.05)
        dpg.set_value("mon_triggers", "")
        dpg.set_value("mon_amp", "Amplitude: 0.0000")
        dpg.set_value("mon_phase", "Phase: rest")
        dpg.set_value("mon_src", "Source: --")
        dpg.set_value("mon_deriv", "dA/dt: 0.0000")
        dpg.set_value("mon_cycle", "Cycle: --")
        dpg.set_value("mon_roll", "Rolling avg: --")
        dpg.set_value("mon_consistent", "Consistent: 0/0 (idle)")
        dpg.set_value("mon_conn", "Connection: --")

    def _update_midi_sink_source_id(self) -> None:
        m = self.runtime.midi
        if isinstance(m, MidoMidiSink):
            m.set_activity_source_id(str(self.runtime.config.controller_id))

    @staticmethod
    def _trigger_activity_line(e: TriggerEvent, controller_id: str) -> str:
        if e.kind.value == "note_on":
            note = (e.meta or {}).get("note", "?")
            return (
                f"{e.mono_t:.4f}  [{controller_id}]  {e.name}  "
                f"NOTE {note}  vel={e.value}"
            )
        if e.kind.value == "note_off":
            note = (e.meta or {}).get("note", "?")
            return f"{e.mono_t:.4f}  [{controller_id}]  {e.name}  NOTE_OFF {note}"
        cc = (e.meta or {}).get("cc", "?")
        return f"{e.mono_t:.4f}  [{controller_id}]  {e.name}  CC {cc}  value={e.value}"

    def _append_midi_sink_log_lines(
        self, cfg: ConfigModel, midi_events: list[MidiActivityEvent]
    ) -> None:
        for e in midi_events:
            if e.kind == "note_on" and e.note is not None:
                lab = labels_for_note(cfg, e.channel, e.note)
                if not lab:
                    continue
                vel = int(e.velocity) if e.velocity is not None else 0
                self._midi_log_entries.append(
                    (
                        e.mono_t,
                        f"{e.mono_t:.4f}  [{e.source_id}]  {lab}  "
                        f"NOTE ON  note={int(e.note)}  vel={vel}",
                    )
                )
            elif e.kind == "note_off" and e.note is not None:
                lab = labels_for_note(cfg, e.channel, e.note)
                if not lab:
                    continue
                self._midi_log_entries.append(
                    (
                        e.mono_t,
                        f"{e.mono_t:.4f}  [{e.source_id}]  {lab}  "
                        f"NOTE OFF  note={int(e.note)}",
                    )
                )

    def _refresh_trigger_activity_panel(self, st) -> None:
        cfg = self.runtime.config
        cid = str(cfg.controller_id)
        trig_lines = [
            (e.mono_t, self._trigger_activity_line(e, cid)) for e in st.recent_triggers
        ]
        merged = sorted([*trig_lines, *self._midi_log_entries], key=lambda x: x[0])
        tail = merged[-50:]
        dpg.set_value("mon_triggers", "\n".join(t[1] for t in tail))

    def _on_start(self) -> None:
        self.runtime.start()
        self._sync_start_stop_buttons()

    def _on_stop(self) -> None:
        self.runtime.stop()
        self.runtime.reset_subsystems_from_config(self.runtime.config)
        self._clear_plot_and_monitor()
        if self._midi_viz is not None:
            self._midi_viz.sync_config(self.runtime.config)
        self._sync_start_stop_buttons()

    def _on_panel_left_toggle(self, s, a, u) -> None:
        open_ = bool(dpg.get_value("chk_panel_left"))
        dpg.configure_item("panel_left", show=open_)
        if open_:
            dpg.configure_item("panel_left", width=self._panel_left_w)
        ui = replace(self.runtime.config.ui, left_panel_open=open_)
        self.runtime.config = replace(self.runtime.config, ui=ui)
        self._sync_three_column_widths()
        self._maybe_autosave_ui()

    def _on_panel_right_toggle(self, s, a, u) -> None:
        open_ = bool(dpg.get_value("chk_panel_right"))
        dpg.configure_item("panel_right", show=open_)
        if open_:
            dpg.configure_item("panel_right", width=self._panel_right_w)
        ui = replace(self.runtime.config.ui, right_panel_open=open_)
        self.runtime.config = replace(self.runtime.config, ui=ui)
        self._sync_three_column_widths()
        self._maybe_autosave_ui()

    def _ble_scan(self) -> None:
        devs = self.runtime.ble_scan()
        items = [f"{label} [{addr}]" for label, addr in devs] if devs else []
        dpg.configure_item("dpg_ble_combo", items=items)
        dpg.configure_item("viewer_ble_combo", items=items)

    def _ble_connect_btn(self, from_viewer: bool) -> None:
        st = self.runtime.get_latest_state()
        if st.input_mode == "ble" and st.input_status == "connected":
            self.runtime.ble_disconnect()
            return
        combo_tag = "viewer_ble_combo" if from_viewer else "dpg_ble_combo"
        s = str(dpg.get_value(combo_tag) or "")
        if "[" in s and "]" in s:
            addr = s.split("[")[-1].rstrip("]")
            if addr:
                self.runtime.ble_connect(addr)

    def _osc_listen(self) -> None:
        c = self.runtime.config
        port = int(dpg.get_value("ui_osc_port"))
        self._apply_cfg(
            replace(
                c,
                input=replace(
                    c.input,
                    mode="osc",
                    osc_port=port,
                ),
            )
        )

    def _osc_stop(self) -> None:
        c = self.runtime.config
        inp = c.input
        self._apply_cfg(
            replace(
                c,
                input=replace(
                    inp,
                    mode="ble",
                    ble_auto_connect=False,
                ),
            )
        )

    def _apply_cfg(self, cfg: ConfigModel) -> None:
        self.runtime.set_config(cfg)
        if self._autosave:
            try:
                self.store.save(cfg)
            except Exception:
                pass
        self.load_into_ui(cfg)

    def save_now(self) -> None:
        self._persist_viewport_to_config()
        try:
            self.store.save(self.runtime.config)
        except Exception:
            pass

    def reload(self) -> None:
        if self._reload_busy:
            return
        self._reload_busy = True
        try:
            dpg.configure_item("btn_reload", enabled=False)
            self.runtime.stop()
            cfg = self.store.load()
            self.runtime.reset_subsystems_from_config(cfg)
            self._clear_plot_and_monitor()
            self.load_into_ui(cfg)
            self.runtime.start()
        finally:
            self._reload_busy = False
            dpg.configure_item("btn_reload", enabled=True)
        self._sync_start_stop_buttons()

    def refresh_midi_ports(self, apply_after: bool) -> None:
        ports = MidoMidiSink.list_outputs()
        if not ports:
            ports = [""]
        current = str(dpg.get_value("ui_midi_port") or "").strip()
        dpg.configure_item("ui_midi_port", items=ports)
        if current and current in ports:
            dpg.set_value("ui_midi_port", current)
        else:
            dpg.set_value("ui_midi_port", ports[0])
        if apply_after and not self._loading:
            self.apply_from_ui()

    def apply_from_ui(self) -> None:
        def apply(cfg: ConfigModel) -> ConfigModel:
            mode = str(dpg.get_value("ui_input_mode") or "osc").strip().lower()
            if mode not in ("osc", "ble"):
                mode = "osc"
            input_cfg = replace(
                cfg.input,
                mode=mode,
                osc_port=int(dpg.get_value("ui_osc_port")),
                source_filter=str(dpg.get_value("ui_source_filter") or "all").strip() or "all",
            )
            signal_cfg = replace(
                cfg.signal,
                smoothing_alpha=float(dpg.get_value("ui_smooth")),
                gain=float(dpg.get_value("ui_gain")),
                deadzone=float(dpg.get_value("ui_deadzone")),
            )
            detection_cfg = replace(
                cfg.detection,
                inhale_enter_amp=float(dpg.get_value("ui_inh_enter")),
                exhale_enter_amp=float(dpg.get_value("ui_exh_enter")),
                rest_enter_amp=float(dpg.get_value("ui_rest_enter")),
                slope_enter_abs=float(dpg.get_value("ui_slope_enter")),
                slope_rest_abs=float(dpg.get_value("ui_slope_rest")),
                hysteresis=float(dpg.get_value("ui_hysteresis")),
                min_phase_ms=int(dpg.get_value("ui_min_phase_ms")),
            )
            port_name = str(dpg.get_value("ui_midi_port") or "").strip()
            midi_cfg = replace(
                cfg.midi,
                out_port=port_name,
                channel=int(dpg.get_value("ui_midi_ch")),
                default_velocity=int(dpg.get_value("ui_midi_vel")),
                cc_rate_hz=int(dpg.get_value("ui_cc_rate")),
            )
            inhale_onset = InhaleOnsetTriggerConfig(
                enabled=bool(dpg.get_value("ui_inh_on_en")),
                note=int(dpg.get_value("ui_inh_on_note")),
                velocity=int(dpg.get_value("ui_inh_on_vel")),
                debounce_ms=int(dpg.get_value("ui_inh_on_db")),
            )
            exhale_onset = ExhaleOnsetTriggerConfig(
                enabled=bool(dpg.get_value("ui_exh_on_en")),
                note=int(dpg.get_value("ui_exh_on_note")),
                velocity=int(dpg.get_value("ui_exh_on_vel")),
                debounce_ms=int(dpg.get_value("ui_exh_on_db")),
            )
            inhale_sustain = SustainTriggerConfig(
                enabled=bool(dpg.get_value("ui_inh_cc_en")),
                cc=int(dpg.get_value("ui_inh_cc_num")),
                min_value=cfg.triggers.inhale_sustain.min_value,
                max_value=cfg.triggers.inhale_sustain.max_value,
                curve_kind=cfg.triggers.inhale_sustain.curve_kind,
                curve_gamma=cfg.triggers.inhale_sustain.curve_gamma,
            )
            exhale_sustain = SustainTriggerConfig(
                enabled=bool(dpg.get_value("ui_exh_cc_en")),
                cc=int(dpg.get_value("ui_exh_cc_num")),
                min_value=cfg.triggers.exhale_sustain.min_value,
                max_value=cfg.triggers.exhale_sustain.max_value,
                curve_kind=cfg.triggers.exhale_sustain.curve_kind,
                curve_gamma=cfg.triggers.exhale_sustain.curve_gamma,
            )
            consistent = ConsistentBreathsTriggerConfig(
                enabled=bool(dpg.get_value("ui_cons_en")),
                n=int(dpg.get_value("ui_cons_n")),
                min_cycles_before_eval=cfg.triggers.consistent_breaths.min_cycles_before_eval,
                period_tol_kind=cfg.triggers.consistent_breaths.period_tol_kind,
                period_tol_value=float(dpg.get_value("ui_cons_ptol")),
                peak_tol_kind=cfg.triggers.consistent_breaths.peak_tol_kind,
                peak_tol_value=float(dpg.get_value("ui_cons_ktol")),
                note=int(dpg.get_value("ui_cons_note")),
                velocity=int(dpg.get_value("ui_cons_vel")),
            )
            triggers_cfg = TriggersConfig(
                inhale_onset=inhale_onset,
                exhale_onset=exhale_onset,
                inhale_sustain=inhale_sustain,
                exhale_sustain=exhale_sustain,
                consistent_breaths=consistent,
            )
            return ConfigModel(
                version=cfg.version,
                controller_id=cfg.controller_id,
                input=input_cfg,
                signal=signal_cfg,
                detection=detection_cfg,
                midi=midi_cfg,
                triggers=triggers_cfg,
                ui=cfg.ui,
            )

        cfg = apply(self.runtime.config)
        self.runtime.set_config(cfg)
        if self._midi_viz is not None:
            self._midi_viz.sync_config(cfg)
        self._update_midi_sink_source_id()
        if self._autosave:
            try:
                self.store.save(cfg)
            except Exception:
                pass

    def load_into_ui(self, cfg: ConfigModel) -> None:
        self._loading = True
        try:
            mode = (cfg.input.mode or "osc").lower().strip()
            dpg.set_value("ui_input_mode", "ble" if mode == "ble" else "osc")
            dpg.set_value("viewer_mode", "ble" if mode == "ble" else "osc")
            dpg.set_value("ui_osc_port", int(cfg.input.osc_port))
            dpg.set_value("viewer_osc_port", int(cfg.input.osc_port))
            dpg.set_value("ui_source_filter", str(cfg.input.source_filter))
            dpg.set_value("ui_smooth", float(cfg.signal.smoothing_alpha))
            dpg.set_value("ui_deadzone", float(cfg.signal.deadzone))
            dpg.set_value("ui_gain", float(cfg.signal.gain))
            dpg.set_value("ui_inh_enter", float(cfg.detection.inhale_enter_amp))
            dpg.set_value("ui_exh_enter", float(cfg.detection.exhale_enter_amp))
            dpg.set_value("ui_rest_enter", float(cfg.detection.rest_enter_amp))
            dpg.set_value("ui_slope_enter", float(cfg.detection.slope_enter_abs))
            dpg.set_value("ui_slope_rest", float(cfg.detection.slope_rest_abs))
            dpg.set_value("ui_hysteresis", float(cfg.detection.hysteresis))
            dpg.set_value("ui_min_phase_ms", int(cfg.detection.min_phase_ms))

            ports = MidoMidiSink.list_outputs()
            if not ports:
                ports = [""]
            want = str(cfg.midi.out_port or "").strip()
            dpg.configure_item("ui_midi_port", items=ports)
            if want and want in ports:
                dpg.set_value("ui_midi_port", want)
            else:
                dpg.set_value("ui_midi_port", ports[0])

            dpg.set_value("ui_midi_ch", int(cfg.midi.channel))
            dpg.set_value("ui_midi_vel", int(cfg.midi.default_velocity))
            dpg.set_value("ui_cc_rate", int(cfg.midi.cc_rate_hz))

            dpg.set_value("ui_inh_on_en", bool(cfg.triggers.inhale_onset.enabled))
            dpg.set_value("ui_inh_on_note", int(cfg.triggers.inhale_onset.note))
            dpg.set_value("ui_inh_on_vel", int(cfg.triggers.inhale_onset.velocity))
            dpg.set_value("ui_inh_on_db", int(cfg.triggers.inhale_onset.debounce_ms))

            dpg.set_value("ui_exh_on_en", bool(cfg.triggers.exhale_onset.enabled))
            dpg.set_value("ui_exh_on_note", int(cfg.triggers.exhale_onset.note))
            dpg.set_value("ui_exh_on_vel", int(cfg.triggers.exhale_onset.velocity))
            dpg.set_value("ui_exh_on_db", int(cfg.triggers.exhale_onset.debounce_ms))

            dpg.set_value("ui_inh_cc_en", bool(cfg.triggers.inhale_sustain.enabled))
            dpg.set_value("ui_inh_cc_num", int(cfg.triggers.inhale_sustain.cc))
            dpg.set_value("ui_exh_cc_en", bool(cfg.triggers.exhale_sustain.enabled))
            dpg.set_value("ui_exh_cc_num", int(cfg.triggers.exhale_sustain.cc))

            dpg.set_value("ui_cons_en", bool(cfg.triggers.consistent_breaths.enabled))
            dpg.set_value("ui_cons_n", int(cfg.triggers.consistent_breaths.n))
            dpg.set_value("ui_cons_ptol", float(cfg.triggers.consistent_breaths.period_tol_value))
            dpg.set_value("ui_cons_ktol", float(cfg.triggers.consistent_breaths.peak_tol_value))
            dpg.set_value("ui_cons_note", int(cfg.triggers.consistent_breaths.note))
            dpg.set_value("ui_cons_vel", int(cfg.triggers.consistent_breaths.velocity))

            dpg.set_value("ui_autosave", self._autosave)

            u = cfg.ui
            dpg.set_value("chk_panel_left", u.left_panel_open)
            dpg.set_value("chk_panel_right", u.right_panel_open)
            dpg.configure_item("panel_left", show=u.left_panel_open)
            dpg.configure_item("panel_right", show=u.right_panel_open)
            if u.left_panel_open:
                dpg.configure_item("panel_left", width=self._panel_left_w)
            if u.right_panel_open:
                dpg.configure_item("panel_right", width=self._panel_right_w)
            self._sync_three_column_widths()
        finally:
            if self._midi_viz is not None:
                self._midi_viz.sync_config(cfg)
            self._update_midi_sink_source_id()
            self._loading = False

    def tick(self) -> None:
        self._sync_start_stop_buttons()
        st = self.runtime.get_latest_state()
        dpg.set_value("mon_amp", f"Amplitude: {st.amp:.4f}")
        dpg.set_value("mon_deriv", f"dA/dt: {st.d_amp:.4f}")
        dpg.set_value("mon_src", f"Source: {st.source_id}")
        dpg.set_value("mon_phase", f"Phase: {st.phase.value}")
        dpg.set_value(
            "mon_conn",
            f"Connection: {st.input_mode} / {st.input_status}   RX: {st.rx_hz:.0f} Hz",
        )
        dpg.set_value("viewer_status", f"{st.input_mode} / {st.input_status}")
        dpg.set_value("viewer_rx", f"{st.rx_hz:.0f} Hz")
        dpg.set_value("viewer_source", st.source_id)
        dpg.set_value("viewer_value", f"{st.amp:.4f}")
        if st.last_cycle:
            dpg.set_value(
                "mon_cycle",
                f"Cycle: period={st.last_cycle.period_s:.3f}s peak={st.last_cycle.peak_amp:.3f}",
            )
        else:
            dpg.set_value("mon_cycle", "Cycle: --")
        rp = st.rolling.avg_period_s
        rk = st.rolling.avg_peak_amp
        if rp is not None and rk is not None:
            dpg.set_value("mon_roll", f"Rolling avg: period={rp:.3f}s peak={rk:.3f}")
        else:
            dpg.set_value("mon_roll", "Rolling avg: --")
        held_txt = "held" if st.consistent_held else "idle"
        dpg.set_value(
            "mon_consistent",
            f"Consistent: {int(st.consistent_streak)}/{int(st.consistent_target)} ({held_txt})",
        )

        midi_events = self._midi_bus.drain()
        cfg = self.runtime.config
        if self._midi_viz is not None:
            self._midi_viz.process_events(midi_events, cfg)
        self._append_midi_sink_log_lines(cfg, midi_events)
        self._refresh_trigger_activity_panel(st)

        mode = (st.input_mode or "osc").lower().strip()
        is_ble = mode == "ble"
        dpg.configure_item("grp_ble_io", show=is_ble)
        dpg.configure_item("grp_osc_io", show=not is_ble)
        dpg.configure_item("viewer_ble_row", show=is_ble)
        dpg.configure_item("viewer_osc_row", show=not is_ble)
        if is_ble and st.input_status == "connected":
            dpg.configure_item("dpg_ble_connect_btn", label="Disconnect")
            dpg.configure_item("viewer_ble_connect", label="Disconnect")
        else:
            dpg.configure_item("dpg_ble_connect_btn", label="Connect")
            dpg.configure_item("viewer_ble_connect", label="Connect")

        ts, vs = self.runtime.get_plot_data()
        if ts:
            latest = ts[-1]
            if latest <= WINDOW_SECONDS:
                dpg.set_axis_limits("plot_xaxis", 0.0, WINDOW_SECONDS)
            else:
                dpg.set_axis_limits("plot_xaxis", latest - WINDOW_SECONDS, latest)
            dpg.set_value("plot_series", [ts, vs])
