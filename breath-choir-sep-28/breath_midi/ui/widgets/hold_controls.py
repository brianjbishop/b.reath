"""
Detection controls.

Lives in the Group Breath right column rather than the Single Breath Detection
tab, because these are tuned by ear against live performers while watching the
group waveform — having to leave that view to reach them defeats the purpose.

DPG tags are globally unique, so this section exists in exactly one place; the
Single Breath Detection tab points at it rather than duplicating the widgets.
"""

from __future__ import annotations

from typing import Callable

import dearpygui.dearpygui as dpg

from breath_midi.ui.widgets.knob import add_knob

_KNOB_SIZE = 52


def _build_preset_row(
    preset_names: Callable[[], list[str]],
    on_load: Callable[[str], None],
    on_save: Callable[[str], None],
) -> None:
    """Pick a saved dial set, or name the current one and keep it."""

    def _refresh() -> None:
        dpg.configure_item("ui_preset_combo", items=list(preset_names()))

    def _load(*_args) -> None:
        name = dpg.get_value("ui_preset_combo")
        if name:
            on_load(name)

    def _save(*_args) -> None:
        name = (dpg.get_value("ui_preset_name") or "").strip()
        if not name:
            return
        on_save(name)
        dpg.set_value("ui_preset_name", "")
        _refresh()
        dpg.set_value("ui_preset_combo", name)

    with dpg.group(horizontal=True):
        dpg.add_combo([], tag="ui_preset_combo", width=140, callback=_load)
        dpg.add_spacer(width=6)
        dpg.add_input_text(tag="ui_preset_name", width=90, hint="name")
        dpg.add_spacer(width=6)
        dpg.add_button(label="Save", tag="ui_preset_save", callback=_save)
    _refresh()


def build_hold_controls(
    on_change: Callable,
    preset_names: Callable[[], list[str]] | None = None,
    on_preset_load: Callable[[str], None] | None = None,
    on_preset_save: Callable[[str], None] | None = None,
) -> None:
    """
    Build the detection controls into the current DPG container.

    The preset row is optional and carries no logic of its own — it lists, loads
    and saves through the callbacks, because main_window is what owns the config
    and the store.  Passing none of them builds the panel exactly as before.
    """
    if preset_names is not None and on_preset_load is not None and on_preset_save is not None:
        _build_preset_row(preset_names, on_preset_load, on_preset_save)
        dpg.add_spacer(height=6)
        dpg.add_separator()
        dpg.add_spacer(height=6)

    with dpg.group(horizontal=True):
        add_knob(
            "ui_inhale_exit_delta", "In exit",
            default=0.06, min_value=0.0, max_value=0.60, step=0.005,
            fmt="%.3f", callback=on_change, size=_KNOB_SIZE,
        )
        dpg.add_spacer(width=10)
        add_knob(
            "ui_exhale_exit_delta", "Ex exit",
            default=0.12, min_value=0.0, max_value=0.60, step=0.005,
            fmt="%.3f", callback=on_change, size=_KNOB_SIZE,
        )
        dpg.add_spacer(width=10)
        add_knob(
            "ui_hold_exit_delta", "Hold exit",
            default=0.15, min_value=0.0, max_value=0.60, step=0.005,
            fmt="%.3f", callback=on_change, size=_KNOB_SIZE,
        )
    dpg.add_spacer(height=8)
    dpg.add_separator()
    dpg.add_spacer(height=4)

    dpg.add_checkbox(
        label="Detect holds",
        tag="ui_hold_enabled",
        default_value=True,
        callback=on_change,
    )
    dpg.add_spacer(height=4)
    with dpg.group(horizontal=True):
        add_knob(
            "ui_hold_still_tol", "Still tol",
            default=0.05, min_value=0.0, max_value=0.50, step=0.005,
            fmt="%.3f", callback=on_change, size=_KNOB_SIZE,
        )
        dpg.add_spacer(width=10)
        add_knob(
            "ui_min_hold_ms", "Hold time",
            default=1500, min_value=0, max_value=5000, step=50,
            fmt="%.0f", callback=on_change, size=_KNOB_SIZE, is_int=True,
        )
    dpg.add_spacer(height=4)
    with dpg.group(horizontal=True):
        add_knob(
            "ui_hold_peak_band", "Peak",
            default=0.80, min_value=0.0, max_value=1.0, step=0.01,
            callback=on_change, size=_KNOB_SIZE,
        )
        dpg.add_spacer(width=10)
        add_knob(
            "ui_hold_valley_band", "Valley",
            default=0.20, min_value=0.0, max_value=1.0, step=0.01,
            callback=on_change, size=_KNOB_SIZE,
        )

    dpg.add_spacer(height=8)
    dpg.add_separator()
    dpg.add_spacer(height=4)

    # CC shaping is global: range and curve belong to what the dial drives, not
    # to who is breathing into it. The CC numbers stay per device.
    dpg.add_text("CC", color=(140, 140, 140))
    dpg.add_spacer(height=4)
    with dpg.group(horizontal=True):
        add_knob(
            "ui_cc_min", "Min",
            default=0, min_value=0, max_value=127, step=1,
            fmt="%.0f", callback=on_change, size=_KNOB_SIZE, is_int=True,
        )
        dpg.add_spacer(width=10)
        add_knob(
            "ui_cc_max", "Max",
            default=127, min_value=0, max_value=127, step=1,
            fmt="%.0f", callback=on_change, size=_KNOB_SIZE, is_int=True,
        )
        dpg.add_spacer(width=10)
        add_knob(
            "ui_cc_gamma", "Curve",
            default=1.0, min_value=0.1, max_value=4.0, step=0.05,
            fmt="%.2f", callback=on_change, size=_KNOB_SIZE,
        )
