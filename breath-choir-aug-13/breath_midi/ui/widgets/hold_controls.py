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
_HINT_COLOR = (140, 140, 140)


def build_hold_controls(on_change: Callable) -> None:
    """Build the detection controls into the current DPG container."""
    dpg.add_text("Exit — how far the breath must move to end a phase",
                 color=_HINT_COLOR)
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
    dpg.add_text(
        "In exit waits on the slow exhale, so\nit wants the smaller number.",
        color=_HINT_COLOR,
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
    dpg.add_spacer(height=4)
    dpg.add_text(
        "A hold is declared only above Peak\nor below Valley. Close the gap to\nallow a hold anywhere.",
        color=_HINT_COLOR,
    )
