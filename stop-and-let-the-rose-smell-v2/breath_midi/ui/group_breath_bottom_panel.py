from __future__ import annotations

import dearpygui.dearpygui as dpg

from breath_midi.every_breath.hub import DeviceUISnapshot, EveryBreathHub
from breath_midi.types import Phase

_GRAY_INACTIVE = (80, 80, 80, 255)
_GATE_OPEN_COLOR = (0, 200, 100, 255)


class GroupBreathBottomPanel:
    """
    Collapsible per-device strip panel for the Group Breath tab.

    Rendered below the shared breathwave plot.  One horizontal strip per
    device — shows name, In/Ex indicators, Mute/Solo, CC mode toggle,
    and In#/Ex# / CC value inputs.

    Strips are rebuilt only when the UUID list changes (same guard as
    EveryBreathTab._rebuild_grid).  Per-frame refresh uses configure_item
    on drawlist rect fill — no delete/redraw.

    Mute/Solo button themes reuse "theme_circle_yellow" / "theme_circle_gray"
    defined in main_window._build().
    """

    def __init__(self, hub: EveryBreathHub, parent_tag: str) -> None:
        self._hub = hub
        self._parent = parent_tag
        self._built_uuids: list[str] = []
        self._panel_tag = "gb_bottom_panel"
        self._strip_container_tag = "gb_strip_container"
        self._device_theme_tags: dict[str, int] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Called once from GroupBreathTab.build() after the shared plot."""
        with dpg.child_window(
            tag=self._panel_tag,
            parent=self._parent,
            border=True,
            height=-1,
            width=-1,
        ):
            # ── Collapse toggle header ─────────────────────────────────────────
            with dpg.group(horizontal=True, tag="gb_bottom_header"):
                dpg.add_button(
                    label="v Devices",
                    tag="gb_bottom_collapse_btn",
                    callback=self._on_collapse_toggle,
                    small=True,
                )
                dpg.add_text("  Per-device MIDI settings", color=(140, 140, 140))

            # ── Scrollable horizontal strip container ─────────────────────────
            with dpg.child_window(
                tag=self._strip_container_tag,
                border=False,
                width=-1,
                height=-1,
                horizontal_scrollbar=True,
            ):
                pass  # strips added dynamically in update()

    # ── per-frame update ──────────────────────────────────────────────────────

    def update(self, snapshots: list[DeviceUISnapshot]) -> None:
        """Called every frame from GroupBreathTab.update() with already-fetched snapshots."""
        current_uuids = [s.uuid for s in snapshots]
        if current_uuids == self._built_uuids:
            self._refresh_strips(snapshots)
        else:
            self._rebuild_strips(snapshots)

    # ── grid management ───────────────────────────────────────────────────────

    def _rebuild_strips(self, snapshots: list[DeviceUISnapshot]) -> None:
        # Delete per-device themes before wiping the strip widgets
        for theme_tag in self._device_theme_tags.values():
            if dpg.does_item_exist(theme_tag):
                dpg.delete_item(theme_tag)
        self._device_theme_tags.clear()
        dpg.delete_item(self._strip_container_tag, children_only=True)
        self._built_uuids = []

        if not snapshots:
            dpg.add_text(
                "No devices connected",
                parent=self._strip_container_tag,
                color=(120, 120, 120),
            )
            return

        with dpg.group(
            horizontal=True,
            parent=self._strip_container_tag,
            tag="gb_strip_row",
        ):
            for snap in snapshots:
                self._build_strip(snap)
                self._built_uuids.append(snap.uuid)

    def _build_strip(self, snap: DeviceUISnapshot) -> None:
        """Build one 200px vertical strip for a device."""
        strip_tag = f"gb_strip_{snap.uuid}"
        r, g, b = snap.color
        inh_color = (r, g, b, 255) if snap.phase == Phase.INHALE else _GRAY_INACTIVE
        exh_color = (r, g, b, 255) if snap.phase == Phase.EXHALE else _GRAY_INACTIVE

        # Per-device color theme for M/S buttons when active
        with dpg.theme() as device_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button,        (r, g, b, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,  (r, g, b, 180))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,   (r, g, b, 255))
        self._device_theme_tags[snap.uuid] = device_theme

        with dpg.child_window(
            tag=strip_tag,
            parent="gb_strip_row",
            width=200,
            height=-1,
            border=True,
        ):
            # Row 1: Name in device color
            dpg.add_text(
                snap.name[:15],
                tag=f"gb_strip_name_{snap.uuid}",
                color=(r, g, b, 255),
            )

            dpg.add_spacer(height=4)

            # Row 2: In/Ex phase indicators + gate dot
            with dpg.group(horizontal=True):
                dpg.add_text("In")
                dpg.add_drawlist(
                    width=14, height=14,
                    tag=f"gb_strip_inh_{snap.uuid}",
                )
                dpg.draw_rectangle(
                    (1, 1), (13, 13),
                    fill=inh_color,
                    color=inh_color,
                    parent=f"gb_strip_inh_{snap.uuid}",
                    tag=f"gb_strip_inh_rect_{snap.uuid}",
                )
                dpg.add_spacer(width=6)
                dpg.add_text("Ex")
                dpg.add_drawlist(
                    width=14, height=14,
                    tag=f"gb_strip_exh_{snap.uuid}",
                )
                dpg.draw_rectangle(
                    (1, 1), (13, 13),
                    fill=exh_color,
                    color=exh_color,
                    parent=f"gb_strip_exh_{snap.uuid}",
                    tag=f"gb_strip_exh_rect_{snap.uuid}",
                )
                dpg.add_spacer(width=6)
                dpg.add_text("Gate")
                gate_color = _GATE_OPEN_COLOR if snap.consistent_gate_open else _GRAY_INACTIVE
                dpg.add_drawlist(
                    width=14, height=14,
                    tag=f"gb_strip_gate_{snap.uuid}",
                )
                dpg.draw_rectangle(
                    (1, 1), (13, 13),
                    fill=gate_color,
                    color=gate_color,
                    parent=f"gb_strip_gate_{snap.uuid}",
                    tag=f"gb_strip_gate_rect_{snap.uuid}",
                )

            dpg.add_spacer(height=4)

            # Row 3: Mute / Solo / Note-CC toggle
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="M",
                    tag=f"gb_strip_mute_{snap.uuid}",
                    width=24,
                    height=24,
                    callback=lambda s, a, u: self._on_mute(u),
                    user_data=snap.uuid,
                )
                dpg.bind_item_theme(
                    f"gb_strip_mute_{snap.uuid}",
                    device_theme if snap.muted else "theme_circle_gray",
                )
                dpg.add_spacer(width=4)
                dpg.add_button(
                    label="S",
                    tag=f"gb_strip_solo_{snap.uuid}",
                    width=24,
                    height=24,
                    callback=lambda s, a, u: self._on_solo(u),
                    user_data=snap.uuid,
                )
                dpg.bind_item_theme(
                    f"gb_strip_solo_{snap.uuid}",
                    device_theme if snap.soloed else "theme_circle_gray",
                )
                dpg.add_spacer(width=4)
                dpg.add_button(
                    label="CC" if snap.cc_mode else "Note",
                    tag=f"gb_strip_mode_toggle_{snap.uuid}",
                    width=44,
                    height=24,
                    callback=lambda s, a, u: self._on_mode_toggle(u),
                    user_data=snap.uuid,
                )
                dpg.bind_item_theme(
                    f"gb_strip_mode_toggle_{snap.uuid}",
                    "theme_circle_yellow",
                )

            dpg.add_spacer(height=4)

            # Row 4: Consistent breaths count (0 = gating off)
            with dpg.group(horizontal=True):
                dpg.add_text("N:")
                dpg.add_input_int(
                    tag=f"gb_strip_cons_n_{snap.uuid}",
                    default_value=snap.cons_n,
                    width=50,
                    min_value=0,
                    max_value=20,
                    step=0,
                    on_enter=True,
                    callback=lambda s, a, u: self._on_cons_n_change(u, a),
                    user_data=snap.uuid,
                )

            # Row 5: Consistency tolerance (period + peak, single knob)
            with dpg.group(horizontal=True):
                dpg.add_text("Tol:")
                dpg.add_input_float(
                    tag=f"gb_strip_cons_tol_{snap.uuid}",
                    default_value=snap.cons_tolerance,
                    width=55,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.0,
                    format="%.2f",
                    on_enter=True,
                    callback=lambda s, a, u: self._on_cons_tol_change(u, a),
                    user_data=snap.uuid,
                )

            dpg.add_spacer(height=4)

            # Row 6: Inhale number (note or CC number)
            with dpg.group(horizontal=True):
                dpg.add_text("In#:")
                dpg.add_input_int(
                    tag=f"gb_strip_inh_num_{snap.uuid}",
                    default_value=snap.inhale_note,
                    width=60,
                    min_value=0,
                    max_value=127,
                    step=0,
                    on_enter=True,
                    callback=lambda s, a, u: self._on_inhale_num_change(u, a),
                    user_data=snap.uuid,
                )

            # Row 7: Exhale number (note or CC number)
            with dpg.group(horizontal=True):
                dpg.add_text("Ex#:")
                dpg.add_input_int(
                    tag=f"gb_strip_exh_num_{snap.uuid}",
                    default_value=snap.exhale_note,
                    width=60,
                    min_value=0,
                    max_value=127,
                    step=0,
                    on_enter=True,
                    callback=lambda s, a, u: self._on_exhale_num_change(u, a),
                    user_data=snap.uuid,
                )

            dpg.add_spacer(height=4)

            # Row 8: CC value — only visible when CC mode on
            with dpg.group(
                horizontal=True,
                tag=f"gb_strip_cc_val_row_{snap.uuid}",
                show=snap.cc_mode,
            ):
                dpg.add_text("Val:")
                dpg.add_input_int(
                    tag=f"gb_strip_cc_val_{snap.uuid}",
                    default_value=snap.cc_value,
                    width=60,
                    min_value=0,
                    max_value=127,
                    step=0,
                    callback=lambda s, a, u: self._on_cc_value_change(u, a),
                    user_data=snap.uuid,
                )

    # ── per-frame refresh ─────────────────────────────────────────────────────

    def _refresh_strips(self, snapshots: list[DeviceUISnapshot]) -> None:
        for snap in snapshots:
            uuid = snap.uuid
            r, g, b = snap.color
            inh_color = (r, g, b, 255) if snap.phase == Phase.INHALE else _GRAY_INACTIVE
            exh_color = (r, g, b, 255) if snap.phase == Phase.EXHALE else _GRAY_INACTIVE
            gate_color = _GATE_OPEN_COLOR if snap.consistent_gate_open else _GRAY_INACTIVE

            name_tag = f"gb_strip_name_{uuid}"
            if dpg.does_item_exist(name_tag):
                if dpg.get_value(name_tag) != snap.name[:15]:
                    dpg.set_value(name_tag, snap.name[:15])

            inh_rect = f"gb_strip_inh_rect_{uuid}"
            if dpg.does_item_exist(inh_rect):
                dpg.configure_item(inh_rect, fill=inh_color, color=inh_color)

            exh_rect = f"gb_strip_exh_rect_{uuid}"
            if dpg.does_item_exist(exh_rect):
                dpg.configure_item(exh_rect, fill=exh_color, color=exh_color)

            gate_rect = f"gb_strip_gate_rect_{uuid}"
            if dpg.does_item_exist(gate_rect):
                dpg.configure_item(gate_rect, fill=gate_color, color=gate_color)

            device_theme = self._device_theme_tags.get(uuid)
            mute_tag = f"gb_strip_mute_{uuid}"
            if device_theme is not None and dpg.does_item_exist(mute_tag):
                dpg.bind_item_theme(
                    mute_tag,
                    device_theme if snap.muted else "theme_circle_gray",
                )

            solo_tag = f"gb_strip_solo_{uuid}"
            if device_theme is not None and dpg.does_item_exist(solo_tag):
                dpg.bind_item_theme(
                    solo_tag,
                    device_theme if snap.soloed else "theme_circle_gray",
                )

            mode_toggle = f"gb_strip_mode_toggle_{uuid}"
            if dpg.does_item_exist(mode_toggle):
                expected_label = "CC" if snap.cc_mode else "Note"
                if dpg.get_item_configuration(mode_toggle).get("label", "") != expected_label:
                    dpg.configure_item(mode_toggle, label=expected_label)

            cc_val_row = f"gb_strip_cc_val_row_{uuid}"
            if dpg.does_item_exist(cc_val_row):
                current_show = dpg.get_item_configuration(cc_val_row).get("show", True)
                if current_show != snap.cc_mode:
                    dpg.configure_item(cc_val_row, show=snap.cc_mode)

            cons_n_tag = f"gb_strip_cons_n_{uuid}"
            if dpg.does_item_exist(cons_n_tag):
                if int(dpg.get_value(cons_n_tag)) != snap.cons_n:
                    dpg.set_value(cons_n_tag, snap.cons_n)

            cons_tol_tag = f"gb_strip_cons_tol_{uuid}"
            if dpg.does_item_exist(cons_tol_tag):
                if abs(float(dpg.get_value(cons_tol_tag)) - snap.cons_tolerance) > 1e-4:
                    dpg.set_value(cons_tol_tag, snap.cons_tolerance)

            inh_num = f"gb_strip_inh_num_{uuid}"
            if dpg.does_item_exist(inh_num):
                if int(dpg.get_value(inh_num)) != snap.inhale_note:
                    dpg.set_value(inh_num, snap.inhale_note)

            exh_num = f"gb_strip_exh_num_{uuid}"
            if dpg.does_item_exist(exh_num):
                if int(dpg.get_value(exh_num)) != snap.exhale_note:
                    dpg.set_value(exh_num, snap.exhale_note)

    # ── interaction callbacks ─────────────────────────────────────────────────

    def _on_mute(self, uuid: str) -> None:
        entry = self._hub.registry.get(uuid)
        if entry is not None:
            self._hub.set_muted(uuid, not entry.muted)

    def _on_solo(self, uuid: str) -> None:
        entry = self._hub.registry.get(uuid)
        if entry is not None:
            self._hub.set_soloed(uuid, not entry.soloed)

    def _on_mode_toggle(self, uuid: str) -> None:
        entry = self._hub.registry.get(uuid)
        if entry is None:
            return
        new_mode = not entry.cc_mode
        self._hub.set_cc_mode(uuid, new_mode)
        # Update label immediately without waiting for next snapshot
        toggle_tag = f"gb_strip_mode_toggle_{uuid}"
        if dpg.does_item_exist(toggle_tag):
            dpg.configure_item(toggle_tag, label="CC" if new_mode else "Note")

    def _on_cons_n_change(self, uuid: str, value: int) -> None:
        self._hub.set_cons_n(uuid, int(value))  # 0 = gating off

    def _on_cons_tol_change(self, uuid: str, value: float) -> None:
        self._hub.set_cons_tolerance(uuid, float(value))

    def _on_inhale_num_change(self, uuid: str, value: int) -> None:
        self._hub.set_inhale_number(uuid, int(value))

    def _on_exhale_num_change(self, uuid: str, value: int) -> None:
        self._hub.set_exhale_number(uuid, int(value))

    def _on_cc_value_change(self, uuid: str, value: int) -> None:
        self._hub.set_cc_value(uuid, int(value))

    def _on_collapse_toggle(self) -> None:
        currently_shown = dpg.get_item_configuration(self._strip_container_tag).get("show", True)
        dpg.configure_item(self._strip_container_tag, show=not currently_shown)
        label = "v Devices" if not currently_shown else "> Devices"
        dpg.configure_item("gb_bottom_collapse_btn", label=label)
