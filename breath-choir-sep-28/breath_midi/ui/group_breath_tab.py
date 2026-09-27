from __future__ import annotations

import time
from pathlib import Path

import dearpygui.dearpygui as dpg

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.ui.group_breath_animation import GroupBreathAnimation
from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel
from breath_midi.ui.qr import show_qr_popup

# Width of the right-hand column. The plot column is sized as its negative,
# so the two always add up to the window and cannot drift apart.
RIGHT_COL_W = 336


def _hovered(tag: str) -> bool:
    """A drawlist has no callback, so a click is an edge while it is hovered."""
    return dpg.does_item_exist(tag) and dpg.is_item_hovered(tag)

_NET_ICON = 26
_QR_ICON = 26
from breath_midi.net_identity import NetworkWatcher
from breath_midi.ui.widgets.hold_controls import build_hold_controls
from breath_midi.ui.widgets.qr_icon import (
    HOVER as QR_HOVER,
    IDLE as QR_IDLE,
    build_qr_icon,
    hovered as qr_hovered,
    set_qr_color,
)
from breath_midi.ui.widgets.wifi_icon import (
    FLASH_SECONDS,
    build_wifi_icon,
    flash_colour,
    hovered as wifi_hovered,
    set_wifi_color,
    state_colour as wifi_state_colour,
)


class GroupBreathTab:
    """
    Renders the Group Breath shared waveform view.

    All connected devices are overlaid as separate colored lines on a single
    shared plot.  Reuses EveryBreathHub directly — no separate OSC listener.

    update() is called every frame from main_window.tick().
    Series are added on first sight of a UUID and updated in-place via
    set_value() / configure_item(label=) only — no color/theme ops per frame.

    Color is set once at series creation via bind_item_theme() with
    mvPlotCol_Line.  Theme tags are stored in _theme_tags and deleted
    alongside their series when a device leaves the registry.

    Disconnected devices are hidden (show=False) rather than dimmed per
    frame — a single bool toggle with no render-state rebuild cost.
    """

    def __init__(
        self,
        hub: EveryBreathHub,
        parent_tag: str,
        on_change=None,
        preset_names=None,
        on_preset_load=None,
        on_preset_save=None,
    ) -> None:
        self._hub = hub
        # Preset wiring is passed straight through to the Detection panel; the
        # tab holds no preset logic of its own.
        self._preset_names = preset_names
        self._on_preset_load = on_preset_load
        self._on_preset_save = on_preset_save
        # main_window's apply-from-UI hook; the detection controls live here but
        # the config write still belongs to the window that owns the store.
        self._on_change = on_change or (lambda *_: None)
        self._parent = parent_tag
        self._series_tags: dict[str, str] = {}   # uuid → series DPG tag
        self._theme_tags: dict[str, int] = {}    # uuid → theme DPG tag
        self._animation = GroupBreathAnimation()
        self._last_tick: float = 0.0
        net = hub._config.network
        self._net = NetworkWatcher(expected_mac=net.expected_gateway_mac)
        self._net_label = net.label
        self._net.start()
        self._flash_until: float = 0.0
        self._mouse_was_down: bool = False
        self._header_gap: int = -1
        # Bottom panel parents into the main column, not the outer container
        self._bottom_panel = GroupBreathBottomPanel(hub=hub, parent_tag="gb_main_col")

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Called once from main_window._build() inside the tab_content_group context."""
        with dpg.child_window(
            parent=self._parent,
            tag="gb_container",
            border=False,
            width=-1,
            height=-1,
        ):
            # ── Header ────────────────────────────────────────────────────────
            # Two icons and nothing else: join on the left, network state on the
            # right. The device count and the port lived here as text, but the
            # strip panel below already lists every device by name, and the port
            # is not something anyone can act on mid-performance.
            with dpg.group(horizontal=True, tag="gb_header"):
                build_qr_icon("gb_qr_icon", size=_QR_ICON)
                # Right-aligned: DPG has no alignment, so the spacer is resized
                # each frame from the measured gap to the container's edge.
                dpg.add_spacer(width=1, tag="gb_header_push")
                build_wifi_icon("gb_net_icon", size=_NET_ICON)

            dpg.add_spacer(height=8)

            # ── Horizontal body: main column (plot + panel) | animation ───────
            with dpg.group(horizontal=True, tag="gb_body_row"):

                # Left: breathwave plot + per-device strip panel
                # Fill everything except the right column, which is fixed width.
                with dpg.child_window(
                    tag="gb_main_col",
                    width=-(RIGHT_COL_W + 8),
                    height=-1,
                    border=False,
                ):
                    # Shared breathwave plot (resizable — drag bottom edge)
                    with dpg.child_window(
                        tag="gb_plot_area",
                        border=False,
                        width=-1,
                        height=400,
                        resizable_y=True,
                    ):
                        with dpg.plot(
                            tag="gb_shared_plot",
                            label="",
                            height=-1,
                            width=-1,
                            no_title=True,
                        ):
                            dpg.add_plot_legend()
                            dpg.add_plot_axis(
                                dpg.mvXAxis,
                                tag="gb_xaxis",
                                no_tick_labels=True,
                            )
                            dpg.set_axis_limits("gb_xaxis", 0, 600)
                            dpg.add_plot_axis(
                                dpg.mvYAxis,
                                tag="gb_yaxis",
                                label="",
                            )
                            dpg.set_axis_limits("gb_yaxis", 0.0, 1.0)

                    # Per-device strip panel (fills remaining height)
                    self._bottom_panel.build()
                    self._bottom_panel.set_transport_callbacks(
                        on_load=self._on_load_track,
                        on_stop=self._hub.stop_all_tracks,
                        on_record=self._on_toggle_record,
                        on_export=self._on_export_take,
                    )

                # Right: collapsible Detection and Breath Guide sections.
                with dpg.child_window(
                    tag="gb_anim_col",
                    width=RIGHT_COL_W,
                    height=-1,
                    border=True,
                ):
                    with dpg.collapsing_header(
                        label="Detection", tag="gb_detection_header", default_open=True
                    ):
                        build_hold_controls(
                            self._on_change,
                            preset_names=self._preset_names,
                            on_preset_load=self._on_preset_load,
                            on_preset_save=self._on_preset_save,
                        )
                    dpg.add_spacer(height=6)
                    with dpg.collapsing_header(
                        label="Breath Guide", tag="gb_guide_header", default_open=True
                    ):
                        self._animation.build(panel_width=RIGHT_COL_W)

                    # The transport lives in the Devices header now: a loaded
                    # track is more devices, so it belongs with them.

    # ── per-frame update ──────────────────────────────────────────────────────

    def stop_animation(self) -> None:
        """Called when the Group Breath tab is toggled off."""
        self._animation.stop()

    def _on_learn_network(self) -> None:
        """Clicking the icon adopts whatever router we are on right now."""
        if self._net.learn_current():
            self._flash_until = time.monotonic() + FLASH_SECONDS
            self._on_change()   # persist through main_window's autosave path

    def _on_load_track(self) -> None:
        """
        Pick a track to add to the choir.

        A track joins the performers rather than replacing them, so this does
        not stop the live listener and does not touch the detection dials.
        """
        root = Path(__file__).resolve().parents[2]
        start_dir = root / "tracks" / "generated"
        # DPG lists no files at all unless the dialog is given extension
        # filters — an empty browser is what "no tracks here" looked like.
        with dpg.file_dialog(
            directory_selector=False,
            show=True,
            width=760,
            height=430,
            modal=True,
            default_path=str(start_dir if start_dir.exists() else root),
            callback=lambda _s, app_data: self._load_track_file(app_data),
        ):
            dpg.add_file_extension(".json", color=(160, 200, 255, 255))
            dpg.add_file_extension(".*")

    def _load_track_file(self, app_data) -> None:
        path = Path(str(app_data.get("file_path_name", "")))
        if not path.is_file():
            return
        try:
            self._hub.load_track(path)
        except (ValueError, OSError) as exc:
            # A bad file must not take the panel down mid-performance.
            print(f"[Tracks] could not load {path.name}: {exc}")

    def _on_toggle_record(self) -> None:
        """Rec starts a take; Stop rec writes it to tracks/recordings/."""
        if self._hub.is_recording:
            path = self._hub.stop_recording()
            if path is None:
                print("[Tracks] nothing captured — no file written")
        else:
            self._hub.start_recording(
                f"take {time.strftime('%Y-%m-%d %H%M%S')}"
            )

    def _on_export_take(self) -> None:
        """
        The export icon writes whatever take is currently rolling.

        Same action as Stop rec, reachable from the icon that has always meant
        'out of the tray'.
        """
        if self._hub.is_recording:
            self._on_toggle_record()

    def _poll_header_clicks(self) -> None:
        """
        Both header icons are drawlists, which have no callback of their own, so
        a click is an edge on the mouse button while one happens to be hovered.
        """
        down = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
        edge = down and not self._mouse_was_down
        if edge and wifi_hovered("gb_net_icon"):
            self._on_learn_network()
        elif edge and qr_hovered("gb_qr_icon"):
            show_qr_popup(8001, self._net_label)
        else:
            self._bottom_panel.poll_transport_clicks(edge)
        self._mouse_was_down = down

    # Right edge inset: the window and the container each add padding between
    # the viewport edge and the header's usable width.
    _HEADER_INSET = 26

    def _right_align_header(self) -> None:
        """
        Push the icon to the right edge of the header.

        Measured against the viewport rather than the container: a child_window
        reports rect_size but *not* rect_min, so asking for its left edge raises
        KeyError — which, inside the per-frame update, silently left the spacer
        at its 1px default and the icon sitting next to the QR button.
        """
        if not (dpg.does_item_exist("gb_qr_icon") and dpg.does_item_exist("gb_header_push")):
            return
        try:
            state = dpg.get_item_state("gb_qr_icon")
            qr_right = state["rect_min"][0] + state["rect_size"][0]
            right_edge = dpg.get_viewport_client_width() - self._HEADER_INSET
        except (KeyError, TypeError, IndexError):
            return
        gap = int(right_edge - qr_right - _NET_ICON)
        if gap != self._header_gap and gap >= 1:
            self._header_gap = gap
            dpg.configure_item("gb_header_push", width=gap)

    def _refresh_network(self) -> None:
        self._poll_header_clicks()
        self._right_align_header()
        set_qr_color("gb_qr_icon", QR_HOVER if qr_hovered("gb_qr_icon") else QR_IDLE)
        colour = flash_colour(time.monotonic(), self._flash_until)
        if colour is None:
            colour = wifi_state_colour(self._net.on_expected_network)
        set_wifi_color("gb_net_icon", colour)

    def update(self) -> None:
        """Called every frame from main_window.tick()."""
        self._refresh_network()
        now = time.monotonic()
        dt = now - self._last_tick if self._last_tick > 0.0 else 0.0
        self._last_tick = now

        snapshots = self._hub.get_ui_snapshot()

        current_uuids = {s.uuid for s in snapshots}

        # Remove series (and their themes) for devices no longer in the registry
        for uuid in list(self._series_tags.keys()):
            if uuid not in current_uuids:
                series_tag = self._series_tags.pop(uuid)
                if dpg.does_item_exist(series_tag):
                    dpg.delete_item(series_tag)
                theme_tag = self._theme_tags.pop(uuid, None)
                if theme_tag is not None and dpg.does_item_exist(theme_tag):
                    dpg.delete_item(theme_tag)

        # Add or refresh one series per device
        for snap in snapshots:
            series_tag = f"gb_series_{snap.uuid}"

            if snap.uuid not in self._series_tags:
                self._create_series(snap, series_tag)
            else:
                self._refresh_series(snap, series_tag)

        self._bottom_panel.refresh_transport(self._hub.is_recording)
        self._bottom_panel.update(snapshots)
        self._animation.update(dt)

    # ── private helpers ───────────────────────────────────────────────────────

    def _create_series(self, snap, series_tag: str) -> None:
        """Add a new line series and bind its color theme.  Called once per UUID."""
        xs = list(range(len(snap.waveform)))
        dpg.add_line_series(
            xs,
            list(snap.waveform),
            label=snap.name,
            parent="gb_yaxis",
            tag=series_tag,
        )

        # Build a per-series theme and bind it — never touched again per frame.
        r, g, b = snap.color
        with dpg.theme() as series_theme:
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(
                    dpg.mvPlotCol_Line,
                    (r, g, b, 255),
                    category=dpg.mvThemeCat_Plots,
                )
        dpg.bind_item_theme(series_tag, series_theme)

        # Hide immediately if the device is already inactive at first sight
        if not snap.active:
            dpg.configure_item(series_tag, show=False)

        self._series_tags[snap.uuid] = series_tag
        self._theme_tags[snap.uuid] = series_theme

    def _refresh_series(self, snap, series_tag: str) -> None:
        """Update waveform data and visibility.  No color/theme ops."""
        xs = list(range(len(snap.waveform)))
        dpg.set_value(series_tag, [xs, list(snap.waveform)])

        # Sync legend label if the device was renamed in Every Breath tab
        current_label = dpg.get_item_configuration(series_tag).get("label", "")
        if current_label != snap.name:
            dpg.configure_item(series_tag, label=snap.name)

        # Show/hide on active state change — single bool, no render rebuild
        current_show = dpg.get_item_configuration(series_tag).get("show", True)
        if current_show != snap.active:
            dpg.configure_item(series_tag, show=snap.active)
