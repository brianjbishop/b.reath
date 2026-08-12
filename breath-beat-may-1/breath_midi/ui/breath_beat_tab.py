from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from breath_midi.breath_beat.hub import BreathBeatHub
from breath_midi.ui.breath_beat_animation import BreathBeatAnimation
from breath_midi.ui.breath_beat_bottom_panel import BreathBeatBottomPanel
from breath_midi.ui.qr import show_qr_popup


class BreathBeatTab:
    """
    Renders the Breath Beat shared waveform view.

    All connected devices are overlaid as separate colored lines on a single
    shared plot.  Uses BreathBeatHub directly — independent OSC listener on
    port 8001 (separate instance from EveryBreathHub).

    update() is called every frame from main_window.tick().
    Series are added on first sight of a UUID and updated in-place via
    set_value() / configure_item(label=) only — no color/theme ops per frame.

    Color is set once at series creation via bind_item_theme() with
    mvPlotCol_Line.  Theme tags are stored in _theme_tags and deleted
    alongside their series when a device leaves the registry.

    Disconnected devices are hidden (show=False) rather than dimmed per
    frame — a single bool toggle with no render-state rebuild cost.
    """

    def __init__(self, hub: BreathBeatHub, parent_tag: str) -> None:
        self._hub = hub
        self._parent = parent_tag
        self._series_tags: dict[str, str] = {}   # uuid → series DPG tag
        self._theme_tags: dict[str, int] = {}    # uuid → theme DPG tag
        self._animation = BreathBeatAnimation()
        self._last_tick: float = 0.0
        self._bottom_panel = BreathBeatBottomPanel(hub=hub, parent_tag="bb_main_col")

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Called once from main_window._build() inside the tab_content_breath_beat context."""
        with dpg.child_window(
            parent=self._parent,
            tag="bb_container",
            border=False,
            width=-1,
            height=-1,
        ):
            # ── Header ────────────────────────────────────────────────────────
            with dpg.group(horizontal=True, tag="bb_header"):
                dpg.add_text("Breath Beat", color=(200, 200, 200))
                dpg.add_spacer(width=20)
                dpg.add_text(
                    "Waiting for devices on port 8001",
                    tag="bb_status_text",
                    color=(120, 120, 120),
                )
                dpg.add_spacer(width=20)
                dpg.add_button(
                    label="Show QR",
                    callback=lambda: show_qr_popup(8001, "breath-choir"),
                )

            dpg.add_spacer(height=8)

            # ── Horizontal body: main column (plot + panel) | animation ───────
            with dpg.group(horizontal=True, tag="bb_body_row"):

                # Left: breathwave plot + per-device strip panel
                with dpg.child_window(
                    tag="bb_main_col",
                    width=-224,
                    height=-1,
                    border=False,
                ):
                    # Shared breathwave plot (resizable — drag bottom edge)
                    with dpg.child_window(
                        tag="bb_plot_area",
                        border=False,
                        width=-1,
                        height=400,
                        resizable_y=True,
                    ):
                        with dpg.plot(
                            tag="bb_shared_plot",
                            label="",
                            height=-1,
                            width=-1,
                            no_title=True,
                        ):
                            dpg.add_plot_legend()
                            dpg.add_plot_axis(
                                dpg.mvXAxis,
                                tag="bb_xaxis",
                                no_tick_labels=True,
                            )
                            dpg.set_axis_limits("bb_xaxis", 0, 600)
                            dpg.add_plot_axis(
                                dpg.mvYAxis,
                                tag="bb_yaxis",
                                label="",
                            )
                            dpg.set_axis_limits("bb_yaxis", 0.0, 1.0)

                    # Per-device strip panel (fills remaining height)
                    self._bottom_panel.build()

                # Right: breath guide animation (fixed 220px)
                with dpg.child_window(
                    tag="bb_anim_col",
                    width=220,
                    height=-1,
                    border=True,
                ):
                    self._animation.build()

    # ── per-frame update ──────────────────────────────────────────────────────

    def stop_animation(self) -> None:
        """Called when the Breath Beat tab is toggled off."""
        self._animation.stop()

    def update(self) -> None:
        """Called every frame from main_window.tick()."""
        now = time.monotonic()
        dt = now - self._last_tick if self._last_tick > 0.0 else 0.0
        self._last_tick = now

        snapshots = self._hub.get_ui_snapshot()
        connected = [s for s in snapshots if s.active]

        # Status text
        if connected:
            dpg.set_value(
                "bb_status_text",
                f"{len(connected)} device(s) connected on port 8001",
            )
        else:
            dpg.set_value(
                "bb_status_text",
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
            series_tag = f"bb_series_{snap.uuid}"

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
            parent="bb_yaxis",
            tag=series_tag,
        )

        r, g, b = snap.color
        with dpg.theme() as series_theme:
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(
                    dpg.mvPlotCol_Line,
                    (r, g, b, 255),
                    category=dpg.mvThemeCat_Plots,
                )
        dpg.bind_item_theme(series_tag, series_theme)

        if not snap.active:
            dpg.configure_item(series_tag, show=False)

        self._series_tags[snap.uuid] = series_tag
        self._theme_tags[snap.uuid] = series_theme

    def _refresh_series(self, snap, series_tag: str) -> None:
        """Update waveform data and visibility.  No color/theme ops."""
        xs = list(range(len(snap.waveform)))
        dpg.set_value(series_tag, [xs, list(snap.waveform)])

        current_label = dpg.get_item_configuration(series_tag).get("label", "")
        if current_label != snap.name:
            dpg.configure_item(series_tag, label=snap.name)

        current_show = dpg.get_item_configuration(series_tag).get("show", True)
        if current_show != snap.active:
            dpg.configure_item(series_tag, show=snap.active)
