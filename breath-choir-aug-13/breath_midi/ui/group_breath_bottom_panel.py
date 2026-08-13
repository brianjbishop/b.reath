from __future__ import annotations

import dearpygui.dearpygui as dpg

from breath_midi.every_breath.hub import DeviceUISnapshot, EveryBreathHub
from breath_midi.types import Phase
from breath_midi.ui.widgets.arrow_label import (
    DIM_COLOR,
    add_arrow_label,
    add_tolerance_label,
    set_glyph_color,
)
from breath_midi.ui.widgets.phase_rhombus import (
    build_phase_rhombus,
    refresh_phase_rhombus,
)

_STRIP_W = 236
_RHOMBUS_SIZE = 92
_GRAY_INACTIVE = (80, 80, 80, 255)
_GATE_OPEN_COLOR = (0, 200, 100, 255)
# N=0 bypasses the gate entirely, so lighting it green would claim something is
# happening that is not. Draw it as off, and dim its label to match.
_GATE_OFF_COLOR = (45, 45, 45, 255)
_GATE_LABEL_DIM = (90, 90, 90, 255)
_GATE_LABEL_ON = (200, 200, 200, 255)
_TOL_ON_COLOR = (200, 200, 200, 255)


def _gate_theme(snap: DeviceUISnapshot) -> str:
    """
    Green when the gate is open, grey otherwise — and grey whenever N=0, since
    the gate is bypassed then and green would claim something that is not
    happening.
    """
    if snap.cons_n == 0 or not snap.consistent_gate_open:
        return "theme_circle_gray"
    return "theme_gate_green"


def _tol_color(snap: DeviceUISnapshot) -> tuple[int, int, int, int]:
    """Tolerance only means anything while the gate is on, i.e. N > 0."""
    return DIM_COLOR if snap.cons_n == 0 else _TOL_ON_COLOR


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
        # Handler registries are top-level items, so a grid rebuild has to
        # delete them explicitly or they accumulate.
        self._name_handler_tags: dict[str, int] = {}
        self._edit_handler_tags: dict[str, int] = {}
        self._enter_handler: int | None = None


    def _bands(self) -> tuple[float, float]:
        """
        Current (peak, valley) bands, read live so the rhombus tracks the
        Detection tab while you are tuning rather than needing a restart.
        """
        d = self._hub._config.detection
        return float(d.hold_peak_band), float(d.hold_valley_band)

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
        for registry in (*self._name_handler_tags.values(), *self._edit_handler_tags.values()):
            if dpg.does_item_exist(registry):
                dpg.delete_item(registry)
        self._name_handler_tags.clear()
        self._edit_handler_tags.clear()
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
            width=_STRIP_W,
            height=-1,
            border=True,
        ):
            # Row 1: name in the device colour, double-click to rename.
            dpg.add_text(
                snap.name[:15],
                tag=f"gb_strip_name_{snap.uuid}",
                color=(r, g, b, 255),
            )
            dpg.add_input_text(
                tag=f"gb_strip_name_edit_{snap.uuid}",
                default_value=snap.name,
                width=_STRIP_W - 24,
                show=False,
                on_enter=True,
                callback=lambda s_, a_, u_: self._on_name_commit(u_),
                user_data=snap.uuid,
            )
            # Committing on focus loss as well, so clicking away saves rather
            # than silently discarding the edit.
            with dpg.item_handler_registry() as name_reg:
                dpg.add_item_double_clicked_handler(
                    callback=lambda s_, a_, u_: self._begin_rename(u_),
                    user_data=snap.uuid,
                )
            dpg.bind_item_handler_registry(f"gb_strip_name_{snap.uuid}", name_reg)
            self._name_handler_tags[snap.uuid] = name_reg

            with dpg.item_handler_registry() as edit_reg:
                dpg.add_item_deactivated_handler(
                    callback=lambda s_, a_, u_: self._on_name_commit(u_),
                    user_data=snap.uuid,
                )
            dpg.bind_item_handler_registry(f"gb_strip_name_edit_{snap.uuid}", edit_reg)
            self._edit_handler_tags[snap.uuid] = edit_reg

            dpg.add_spacer(height=6)

            # Row 2: the rhombus on its own, centred and large enough to read
            # across a room.  The gate moved down beside Note.
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=(_STRIP_W - _RHOMBUS_SIZE) // 2 - 8)
                build_phase_rhombus(
                    prefix=f"gb_strip_rh_{snap.uuid}",
                    phase=snap.phase,
                    color=snap.color,
                    active=True,
                    size=_RHOMBUS_SIZE,
                    amp=snap.raw_amp,
                    peak_band=self._bands()[0],
                    valley_band=self._bands()[1],
                )

            dpg.add_spacer(height=6)

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
                dpg.add_spacer(width=4)
                # Indicator, not a control — it reads state, clicking does
                # nothing.  Styled like Note so the row is one visual family.
                dpg.add_button(
                    label="Gate",
                    tag=f"gb_strip_gate_{snap.uuid}",
                    width=44,
                    height=24,
                )
                dpg.bind_item_theme(
                    f"gb_strip_gate_{snap.uuid}", _gate_theme(snap)
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
                add_tolerance_label(tag=f"gb_strip_tol_lbl_{snap.uuid}",
                                    color=_tol_color(snap))
                dpg.add_input_float(
                    tag=f"gb_strip_cons_tol_{snap.uuid}",
                    default_value=snap.cons_tolerance,
                    enabled=snap.cons_n != 0,
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
                add_arrow_label(Phase.INHALE, size=16, tag=f"gb_lbl_in_{snap.uuid}")
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
                add_arrow_label(Phase.EXHALE, size=16, tag=f"gb_lbl_ex_{snap.uuid}")
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

            # Row 7: hold number. 0 = silent, so no enable checkbox.
            with dpg.group(horizontal=True):
                add_arrow_label(Phase.HOLD, size=16, tag=f"gb_lbl_hd_{snap.uuid}")
                dpg.add_input_int(
                    tag=f"gb_strip_h_num_{snap.uuid}",
                    default_value=snap.hold_note,
                    width=60,
                    min_value=0,
                    max_value=127,
                    step=0,
                    on_enter=True,
                    callback=lambda s, a, u: self._on_hold_num_change(u, a),
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
            name_tag = f"gb_strip_name_{uuid}"
            edit_tag = f"gb_strip_name_edit_{uuid}"
            editing = dpg.does_item_exist(edit_tag) and dpg.is_item_shown(edit_tag)
            if dpg.does_item_exist(name_tag) and not editing:
                if dpg.get_value(name_tag) != snap.name[:15]:
                    dpg.set_value(name_tag, snap.name[:15])

            refresh_phase_rhombus(
                prefix=f"gb_strip_rh_{uuid}",
                phase=snap.phase,
                color=snap.color,
                active=True,
                amp=snap.raw_amp,
                peak_band=self._bands()[0],
                valley_band=self._bands()[1],
            )

            gate_btn = f"gb_strip_gate_{uuid}"
            if dpg.does_item_exist(gate_btn):
                dpg.bind_item_theme(gate_btn, _gate_theme(snap))

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

            tol_lbl = f"gb_strip_tol_lbl_{uuid}"
            if dpg.does_item_exist(tol_lbl):
                set_glyph_color(tol_lbl, _tol_color(snap))

            cons_tol_tag = f"gb_strip_cons_tol_{uuid}"
            if dpg.does_item_exist(cons_tol_tag):
                if dpg.get_item_configuration(cons_tol_tag)["enabled"] != (snap.cons_n != 0):
                    dpg.configure_item(cons_tol_tag, enabled=snap.cons_n != 0)
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

            h_num = f"gb_strip_h_num_{uuid}"
            if dpg.does_item_exist(h_num):
                if int(dpg.get_value(h_num)) != snap.hold_note:
                    dpg.set_value(h_num, snap.hold_note)

    # ── interaction callbacks ─────────────────────────────────────────────────

    def _ensure_enter_handler(self) -> None:
        """
        Commit a rename on Enter.

        The input already sets on_enter, but that did not fire for a widget
        that gets shown and hidden — only clicking away committed. A global key
        handler does not depend on those semantics: whichever rename is open
        gets committed, and there is at most one.
        """
        if self._enter_handler is not None:
            return
        with dpg.handler_registry() as reg:
            dpg.add_key_release_handler(
                key=dpg.mvKey_Return, callback=lambda *_: self._commit_open_rename()
            )
            dpg.add_key_release_handler(
                key=dpg.mvKey_NumPadEnter, callback=lambda *_: self._commit_open_rename()
            )
        self._enter_handler = reg

    def _commit_open_rename(self) -> None:
        for uuid in list(self._built_uuids):
            edit_tag = f"gb_strip_name_edit_{uuid}"
            if dpg.does_item_exist(edit_tag) and dpg.is_item_shown(edit_tag):
                self._on_name_commit(uuid)
                return

    def _begin_rename(self, uuid: str) -> None:
        """Double-click swaps the label for an input and focuses it."""
        name_tag, edit_tag = f"gb_strip_name_{uuid}", f"gb_strip_name_edit_{uuid}"
        entry = self._hub.registry.get(uuid)
        if entry is None or not dpg.does_item_exist(edit_tag):
            return
        dpg.set_value(edit_tag, entry.name)
        dpg.configure_item(name_tag, show=False)
        dpg.configure_item(edit_tag, show=True)
        dpg.focus_item(edit_tag)
        self._ensure_enter_handler()

    def _on_name_commit(self, uuid: str) -> None:
        """Save and swap back. Fires on Enter and on losing focus."""
        name_tag, edit_tag = f"gb_strip_name_{uuid}", f"gb_strip_name_edit_{uuid}"
        if not dpg.does_item_exist(edit_tag) or not dpg.is_item_shown(edit_tag):
            return
        new_name = str(dpg.get_value(edit_tag) or "").strip()
        if new_name:
            self._hub.set_name(uuid, new_name)
            if dpg.does_item_exist(name_tag):
                dpg.set_value(name_tag, new_name[:15])
        dpg.configure_item(edit_tag, show=False)
        dpg.configure_item(name_tag, show=True)

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

    def _on_hold_num_change(self, uuid: str, value: int) -> None:
        self._hub.set_hold_number(uuid, int(value))

    def _on_cc_value_change(self, uuid: str, value: int) -> None:
        self._hub.set_cc_value(uuid, int(value))

    def _on_collapse_toggle(self) -> None:
        currently_shown = dpg.get_item_configuration(self._strip_container_tag).get("show", True)
        dpg.configure_item(self._strip_container_tag, show=not currently_shown)
        label = "v Devices" if not currently_shown else "> Devices"
        dpg.configure_item("gb_bottom_collapse_btn", label=label)
