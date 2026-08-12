from __future__ import annotations

import dearpygui.dearpygui as dpg

from breath_midi.every_breath.hub import DeviceUISnapshot, EveryBreathHub
from breath_midi.ui.qr import show_qr_popup
from breath_midi.ui.widgets.phase_rhombus import (
    build_phase_rhombus,
    refresh_phase_rhombus,
)

_CARD_W = 340
# The rhombus row is taller than the single row of In/Ex squares it replaced.
_CARD_H = 258
_PLOT_H = 120
_COLS = 4
_LEFT_W = 180
_RIGHT_W = 200

# Colors.  Phase-vertex colors live in ui.widgets.phase_rhombus.
_PLACEHOLDER_COLOR = (160, 160, 160)

_STATUS_TAG = "eb_status"


def set_status(message: str | None) -> None:
    """
    Show a start-up failure in the Every Breath toolbar, or clear it.

    Lives at module level because TabActivityManager owns start/stop and has no
    handle on the tab instance.
    """
    if dpg.does_item_exist(_STATUS_TAG):
        dpg.set_value(_STATUS_TAG, message or "")


class EveryBreathTab:
    """
    Renders the Every Breath grid UI inside an already-built DPG tab item.
    One device card per connected source_id, max 4 columns.

    update() is called every frame from main_window.tick().
    _rebuild_grid is intentionally guarded behind a UUID-list comparison —
    it deletes and recreates all DPG card items and must NOT fire every frame
    when the device set is stable. Only new connections, disconnections, or
    reorder events trigger a rebuild.
    """

    def __init__(self, hub: EveryBreathHub, parent_tag: int | str) -> None:
        self._hub = hub
        # Same threshold the detector uses, so the lit vertex agrees with the
        # phase rather than telling a slightly different story.
        self._peak_band = float(hub._config.detection.hold_peak_band)
        self._parent = parent_tag
        # None = never built yet. Using None (not []) as the sentinel so that
        # the first update() call always triggers _rebuild_grid even when there
        # are zero devices — that's what shows the placeholder text.
        self._built_uuids: list[str] | None = None
        # uuid → DPG theme tag for waveform line color.
        # Themes are top-level items — not children of the grid — so they must
        # be deleted explicitly when the grid is rebuilt.
        self._wave_theme_tags: dict[str, int] = {}
        # uuid → DPG theme tag for M/S button active color (device color).
        self._device_theme_tags: dict[str, int] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Called once from main_window._build() inside the tab_every context."""
        with dpg.child_window(
            parent=self._parent,
            border=False,
            width=-1,
            height=-1,
            tag="eb_container",
        ):
            # ── Toolbar ───────────────────────────────────────────────────────
            with dpg.group(horizontal=True, tag="eb_toolbar"):
                dpg.add_text(
                    "Every Breath  —  listening on port 8001",
                    color=(180, 180, 180),
                )
                dpg.add_spacer(width=20)
                dpg.add_button(
                    label="Show QR",
                    callback=lambda: show_qr_popup(8001, "breath-choir"),
                )
                dpg.add_spacer(width=20)
                # Empty unless something failed to start — see set_status().
                dpg.add_text("", tag=_STATUS_TAG, color=(230, 120, 100))
            dpg.add_separator()
            dpg.add_spacer(height=4)

            # ── 3-column body ─────────────────────────────────────────────────
            with dpg.group(horizontal=True, tag="eb_body"):
                # Left panel stub (future: activity monitor)
                with dpg.child_window(
                    tag="eb_left",
                    width=_LEFT_W,
                    height=-1,
                    border=True,
                ):
                    dpg.add_text("Activity", color=(220, 220, 160))
                    dpg.add_separator()
                    dpg.add_text(
                        "Coming soon",
                        color=_PLACEHOLDER_COLOR,
                    )

                # Center: scrollable device card grid
                with dpg.child_window(
                    tag="eb_center",
                    width=-_RIGHT_W - 8,
                    height=-1,
                    border=False,
                ):
                    dpg.add_group(tag="eb_grid")

                # Right panel stub (future: per-device detail)
                with dpg.child_window(
                    tag="eb_right",
                    width=_RIGHT_W,
                    height=-1,
                    border=True,
                ):
                    dpg.add_text("Device detail", color=(220, 220, 160))
                    dpg.add_separator()
                    dpg.add_text(
                        "Select a device",
                        color=_PLACEHOLDER_COLOR,
                    )

    def update(self) -> None:
        """Called every frame from main_window.tick()."""
        snapshots = self._hub.get_ui_snapshot()
        new_uuids = [s.uuid for s in snapshots]

        # Compare UUID ordered list before rebuilding.
        # _rebuild_grid is expensive (deletes+recreates all DPG items).
        # Must NOT be called every frame when device set is stable.
        # _built_uuids starts as None so the first call always rebuilds
        # (which is what shows the "Waiting for devices" placeholder).
        if new_uuids != self._built_uuids:
            self._rebuild_grid(snapshots)
        else:
            self._refresh_cards(snapshots)

    # ── grid management ───────────────────────────────────────────────────────

    def _rebuild_grid(self, snapshots: list[DeviceUISnapshot]) -> None:
        # Themes are top-level items — delete them before wiping the grid.
        for theme_tag in self._wave_theme_tags.values():
            if dpg.does_item_exist(theme_tag):
                dpg.delete_item(theme_tag)
        self._wave_theme_tags.clear()
        for theme_tag in self._device_theme_tags.values():
            if dpg.does_item_exist(theme_tag):
                dpg.delete_item(theme_tag)
        self._device_theme_tags.clear()
        dpg.delete_item("eb_grid", children_only=True)
        self._built_uuids = []

        if not snapshots:
            dpg.add_text(
                "Waiting for devices on port 8001",
                parent="eb_grid",
                color=_PLACEHOLDER_COLOR,
            )
            return

        row_tag: int | str | None = None
        for i, snap in enumerate(snapshots):
            if i % _COLS == 0:
                row_tag = dpg.add_group(
                    horizontal=True,
                    parent="eb_grid",
                    tag=f"eb_row_{i // _COLS}",
                )
            prev_uuid = snapshots[i - 1].uuid if i > 0 else None
            next_uuid = snapshots[i + 1].uuid if i < len(snapshots) - 1 else None
            self._build_card(snap, parent=row_tag, prev_uuid=prev_uuid, next_uuid=next_uuid)
            self._built_uuids.append(snap.uuid)

    def _build_card(
        self,
        snap: DeviceUISnapshot,
        parent: int | str | None,
        prev_uuid: str | None,
        next_uuid: str | None,
    ) -> None:
        card_tag = f"eb_card_{snap.uuid}"
        wave_tag = f"eb_wave_{snap.uuid}"
        rhombus_prefix = f"eb_rh_{snap.uuid}"
        inote_tag = f"eb_inote_{snap.uuid}"
        enote_tag = f"eb_enote_{snap.uuid}"
        hnote_tag = f"eb_hnote_{snap.uuid}"
        name_tag = f"eb_name_{snap.uuid}"
        mute_tag = f"eb_mute_{snap.uuid}"
        solo_tag = f"eb_solo_{snap.uuid}"
        up_tag = f"eb_up_{snap.uuid}"
        dn_tag = f"eb_dn_{snap.uuid}"

        uuid = snap.uuid  # capture for closures

        # Per-device color theme for M/S buttons — built once, never per-frame.
        r, g, b = snap.color
        with dpg.theme() as device_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button,       (r, g, b, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (r, g, b, 180))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,  (r, g, b, 255))
        self._device_theme_tags[uuid] = device_theme

        with dpg.child_window(
            parent=parent,
            tag=card_tag,
            width=_CARD_W,
            height=_CARD_H,
            border=True,
        ):
            # ── Row 1: ↑↓ reorder | name field | M | S ──────────────────────
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="^",
                    tag=up_tag,
                    width=20,
                    height=18,
                    enabled=prev_uuid is not None,
                    callback=lambda s, a, u: self._hub.swap_order(u[0], u[1]),
                    user_data=(uuid, prev_uuid),
                )
                dpg.add_button(
                    label="v",
                    tag=dn_tag,
                    width=20,
                    height=18,
                    enabled=next_uuid is not None,
                    callback=lambda s, a, u: self._hub.swap_order(u[0], u[1]),
                    user_data=(uuid, next_uuid),
                )
                dpg.add_input_text(
                    tag=name_tag,
                    default_value=snap.name,
                    width=118,
                    on_enter=True,
                    callback=lambda s, a, u: self._on_name_edit(s, a, u),
                    user_data=uuid,
                )
                dpg.add_spacer(width=4)
                dpg.add_button(
                    label="M",
                    tag=mute_tag,
                    width=24,
                    height=24,
                    callback=lambda s, a, u: self._on_mute_click(u),
                    user_data=uuid,
                )
                dpg.bind_item_theme(
                    mute_tag,
                    device_theme if snap.muted else "theme_circle_gray",
                )
                dpg.add_button(
                    label="S",
                    tag=solo_tag,
                    width=24,
                    height=24,
                    callback=lambda s, a, u: self._on_solo_click(u),
                    user_data=uuid,
                )
                dpg.bind_item_theme(
                    solo_tag,
                    device_theme if snap.soloed else "theme_circle_gray",
                )

            # ── Row 2: phase rhombus | the four phase notes ──────────────────
            # The diamond replaces the old In/Ex squares; the notes sit beside
            # it in the same clockwise order the cycle runs.
            with dpg.group(horizontal=True):
                build_phase_rhombus(
                    prefix=rhombus_prefix,
                    phase=snap.phase,
                    color=snap.color,
                    active=snap.active,
                    amp=snap.raw_amp,
                    peak_band=self._peak_band,
                )
                dpg.add_spacer(width=4)
                with dpg.group():
                    with dpg.group(horizontal=True):
                        dpg.add_text("In", color=(200, 200, 200))
                        dpg.add_input_int(
                            tag=inote_tag,
                            default_value=snap.inhale_note,
                            width=52,
                            min_value=0,
                            max_value=127,
                            step=0,
                            on_enter=True,
                            callback=lambda s, a, u: self._on_inhale_note_edit(s, a, u),
                            user_data=uuid,
                        )
                        dpg.add_spacer(width=6)
                        dpg.add_text("Ex", color=(200, 200, 200))
                        dpg.add_input_int(
                            tag=enote_tag,
                            default_value=snap.exhale_note,
                            width=52,
                            min_value=0,
                            max_value=127,
                            step=0,
                            on_enter=True,
                            callback=lambda s, a, u: self._on_exhale_note_edit(s, a, u),
                            user_data=uuid,
                        )
                    # 0 means silent — no checkbox needed, the number says it.
                    with dpg.group(horizontal=True):
                        dpg.add_text("Hold", color=(200, 200, 200))
                        dpg.add_input_int(
                            tag=hnote_tag,
                            default_value=snap.hold_note,
                            width=52,
                            min_value=0,
                            max_value=127,
                            step=0,
                            on_enter=True,
                            callback=lambda s, a, u: self._on_hold_note_edit(s, a, u),
                            user_data=uuid,
                        )
                        dpg.add_text("0 = silent", color=_PLACEHOLDER_COLOR)

            # ── Waveform plot ─────────────────────────────────────────────────
            # Line color is set to snap.color at build time so waveform,
            # inhale indicator, and exhale indicator are always identical.
            with dpg.plot(
                width=-1,
                height=_PLOT_H,
                no_menus=True,
                no_box_select=True,
                no_mouse_pos=True,
            ):
                xax = dpg.add_plot_axis(
                    dpg.mvXAxis,
                    no_gridlines=True,
                    no_tick_labels=True,
                    no_tick_marks=True,
                )
                dpg.set_axis_limits(xax, 0, 600)
                with dpg.plot_axis(
                    dpg.mvYAxis,
                    no_gridlines=True,
                    no_tick_labels=True,
                    no_tick_marks=True,
                ) as yax:
                    dpg.set_axis_limits(yax, -0.05, 1.05)
                    xs = list(range(len(snap.waveform)))
                    dpg.add_line_series(
                        xs, list(snap.waveform), tag=wave_tag, parent=yax
                    )
                    # Bind device color as a one-time theme — never touched per frame.
                    r, g, b = snap.color
                    with dpg.theme() as wave_theme:
                        with dpg.theme_component(dpg.mvLineSeries):
                            dpg.add_theme_color(
                                dpg.mvPlotCol_Line,
                                (r, g, b, 255),
                                category=dpg.mvThemeCat_Plots,
                            )
                    dpg.bind_item_theme(wave_tag, wave_theme)
                    self._wave_theme_tags[snap.uuid] = wave_theme

    # ── per-frame refresh ─────────────────────────────────────────────────────

    def _refresh_cards(self, snapshots: list[DeviceUISnapshot]) -> None:
        for snap in snapshots:
            wave_tag = f"eb_wave_{snap.uuid}"
            rhombus_prefix = f"eb_rh_{snap.uuid}"
            inote_tag = f"eb_inote_{snap.uuid}"
            enote_tag = f"eb_enote_{snap.uuid}"
            hnote_tag = f"eb_hnote_{snap.uuid}"
            mute_tag = f"eb_mute_{snap.uuid}"
            solo_tag = f"eb_solo_{snap.uuid}"
            name_tag = f"eb_name_{snap.uuid}"

            if dpg.does_item_exist(wave_tag):
                xs = list(range(len(snap.waveform)))
                dpg.set_value(wave_tag, [xs, list(snap.waveform)])

            # Phase vertices: dim white when paused, device color when active
            refresh_phase_rhombus(
                prefix=rhombus_prefix,
                phase=snap.phase,
                color=snap.color,
                active=snap.active,
                amp=snap.raw_amp,
                peak_band=self._peak_band,
            )

            device_theme = self._device_theme_tags.get(snap.uuid)
            if device_theme is not None:
                if dpg.does_item_exist(mute_tag):
                    dpg.bind_item_theme(mute_tag, device_theme if snap.muted else "theme_circle_gray")
                if dpg.does_item_exist(solo_tag):
                    dpg.bind_item_theme(solo_tag, device_theme if snap.soloed else "theme_circle_gray")

            if dpg.does_item_exist(name_tag):
                if str(dpg.get_value(name_tag) or "") != snap.name:
                    dpg.set_value(name_tag, snap.name)

            if dpg.does_item_exist(inote_tag):
                if int(dpg.get_value(inote_tag)) != snap.inhale_note:
                    dpg.set_value(inote_tag, snap.inhale_note)

            if dpg.does_item_exist(enote_tag):
                if int(dpg.get_value(enote_tag)) != snap.exhale_note:
                    dpg.set_value(enote_tag, snap.exhale_note)

            if dpg.does_item_exist(hnote_tag):
                if int(dpg.get_value(hnote_tag)) != snap.hold_note:
                    dpg.set_value(hnote_tag, snap.hold_note)

    # ── interaction callbacks ─────────────────────────────────────────────────

    def _on_mute_click(self, uuid: str) -> None:
        entry = self._hub.registry.get(uuid)
        if entry is not None:
            self._hub.set_muted(uuid, not entry.muted)

    def _on_solo_click(self, uuid: str) -> None:
        entry = self._hub.registry.get(uuid)
        if entry is not None:
            self._hub.set_soloed(uuid, not entry.soloed)

    def _on_name_edit(self, sender: int | str, app_data: str, user_data: str) -> None:
        uuid = str(user_data)
        name = str(app_data).strip()
        if name:
            self._hub.set_name(uuid, name)

    def _on_inhale_note_edit(self, sender: int | str, app_data: int, user_data: str) -> None:
        uuid = str(user_data)
        entry = self._hub.registry.get(uuid)
        if entry is not None:
            self._hub.set_device_notes(uuid, int(app_data), entry.exhale_note)

    def _on_exhale_note_edit(self, sender: int | str, app_data: int, user_data: str) -> None:
        uuid = str(user_data)
        entry = self._hub.registry.get(uuid)
        if entry is not None:
            self._hub.set_device_notes(uuid, entry.inhale_note, int(app_data))

    def _on_hold_note_edit(self, sender: int | str, app_data: int, user_data: str) -> None:
        self._hub.set_hold_number(str(user_data), int(app_data))

