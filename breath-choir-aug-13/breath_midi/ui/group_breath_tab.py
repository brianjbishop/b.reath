from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.ui.group_breath_animation import GroupBreathAnimation
from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel
from breath_midi.ui.qr import show_qr_popup

_NET_OK = (0, 200, 110, 255)
_NET_WRONG = (230, 150, 60, 255)
_NET_UNKNOWN = (110, 110, 110, 255)
from breath_midi.net_identity import NetworkWatcher
from breath_midi.ui.widgets.hold_controls import build_hold_controls
from breath_midi.ui.widgets.tray_icon import tray_button as _tray_button


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

    def __init__(self, hub: EveryBreathHub, parent_tag: str, on_change=None) -> None:
        self._hub = hub
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
            with dpg.group(horizontal=True, tag="gb_header"):
                dpg.add_text("Group Breath", color=(200, 200, 200))
                dpg.add_spacer(width=20)
                dpg.add_text(
                    "Waiting for devices on port 8001",
                    tag="gb_status_text",
                    color=(120, 120, 120),
                )
                dpg.add_spacer(width=20)
                dpg.add_button(
                    label="Show QR",
                    callback=lambda: show_qr_popup(8001, "breath-choir"),
                )
                # Pushed to the right edge; recomputed on resize by the
                # spacer's width, which is cheap enough to leave fixed.
                dpg.add_spacer(width=-1, tag="gb_header_push")
                dpg.add_text("", tag="gb_net_dot", color=_NET_UNKNOWN)
                dpg.add_text("", tag="gb_net_label", color=(150, 150, 150))
                dpg.add_button(
                    label="Set",
                    tag="gb_net_learn",
                    small=True,
                    callback=self._on_learn_network,
                )
                with dpg.tooltip("gb_net_learn"):
                    dpg.add_text(
                        "Remember this router as the performance network.\n"
                        "Identified by gateway MAC — macOS will not report a\n"
                        "Wi-Fi name without Location Services permission.",
                    )

            dpg.add_spacer(height=8)

            # ── Horizontal body: main column (plot + panel) | animation ───────
            with dpg.group(horizontal=True, tag="gb_body_row"):

                # Left: breathwave plot + per-device strip panel
                # Fill everything except the right column, which is fixed width.
                with dpg.child_window(
                    tag="gb_main_col",
                    width=-344,
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

                # Right: collapsible Detection and Breath Guide sections.
                with dpg.child_window(
                    tag="gb_anim_col",
                    width=336,
                    height=-1,
                    border=True,
                ):
                    with dpg.collapsing_header(
                        label="Detection", tag="gb_detection_header", default_open=True
                    ):
                        build_hold_controls(self._on_change)
                    dpg.add_spacer(height=6)
                    with dpg.collapsing_header(
                        label="Breath Guide", tag="gb_guide_header", default_open=True
                    ):
                        self._animation.build()

                    # Pinned to the bottom of the right column.
                    dpg.add_spacer(height=-1, tag="gb_tracks_push")
                    dpg.add_separator()
                    with dpg.group(horizontal=True, tag="gb_track_row"):
                        dpg.add_text("Tracks", color=(140, 140, 140))
                        dpg.add_spacer(width=8)
                        _tray_button("gb_track_import", into_tray=True)
                        dpg.add_spacer(width=6)
                        _tray_button("gb_track_export", into_tray=False)
                        dpg.add_spacer(width=8)
                        dpg.add_text("(placeholder)", color=(110, 110, 110))

    # ── per-frame update ──────────────────────────────────────────────────────

    def stop_animation(self) -> None:
        """Called when the Group Breath tab is toggled off."""
        self._animation.stop()

    def _on_learn_network(self) -> None:
        mac = self._net.learn_current()
        if mac:
            self._on_change()   # persist through main_window's autosave path

    def _refresh_network(self) -> None:
        identity = self._net.identity
        if not identity.online:
            dot, colour, text = "\u25cf", _NET_UNKNOWN, "no network"
        elif not self._net.expected_mac:
            dot, colour, text = "\u25cf", _NET_UNKNOWN, f"{identity.ip} (unset)"
        elif self._net.on_expected_network:
            dot, colour, text = "\u25cf", _NET_OK, f"{self._net_label}  {identity.ip}"
        else:
            dot, colour, text = "\u25cf", _NET_WRONG, f"wrong network  {identity.ip}"
        if dpg.does_item_exist("gb_net_dot"):
            dpg.set_value("gb_net_dot", dot)
            dpg.configure_item("gb_net_dot", color=colour)
        if dpg.does_item_exist("gb_net_label"):
            dpg.set_value("gb_net_label", text)

    def update(self) -> None:
        """Called every frame from main_window.tick()."""
        self._refresh_network()
        now = time.monotonic()
        dt = now - self._last_tick if self._last_tick > 0.0 else 0.0
        self._last_tick = now

        snapshots = self._hub.get_ui_snapshot()
        connected = [s for s in snapshots if s.active]

        # Status text
        if connected:
            dpg.set_value(
                "gb_status_text",
                f"{len(connected)} device(s) connected on port 8001",
            )
        else:
            dpg.set_value(
                "gb_status_text",
                "Waiting for devices on port 8001",
            )

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
