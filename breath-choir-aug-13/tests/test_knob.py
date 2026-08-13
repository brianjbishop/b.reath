"""
Rotary knob widget tests.

The knob is drawn rather than a native DPG control, so two things need
guarding: the value must stay readable through the ordinary
dpg.get_value/set_value path the rest of the app uses, and the drag/scroll
arithmetic must clamp instead of running off the end of the range.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from breath_midi.ui.widgets import knob as K


@pytest.fixture
def ctx():
    dpg.create_context()
    K._reset_for_tests()
    with dpg.window(tag="root"):
        pass
    yield "root"
    dpg.destroy_context()
    K._reset_for_tests()


def make(ctx, tag="k", default=0.5, lo=0.0, hi=1.0, step=0.01, **kw):
    calls: list[float] = []
    with dpg.group(parent=ctx):
        K.add_knob(
            tag, "Test",
            default=default, min_value=lo, max_value=hi, step=step,
            callback=lambda: calls.append(float(dpg.get_value(tag))),
            **kw,
        )
    return tag, calls


# ── value binding ────────────────────────────────────────────────────────────


def test_value_is_readable_through_dpg_get_value(ctx):
    tag, _ = make(ctx, default=0.42)
    assert dpg.get_value(tag) == pytest.approx(0.42)


def test_external_set_value_then_refresh_repaints(ctx):
    """load_into_ui() writes with set_value; the knob must follow."""
    tag, _ = make(ctx, default=0.2)
    dpg.set_value(tag, 0.9)
    K.refresh_knobs()
    assert K._knobs[tag].last_drawn == pytest.approx(0.9)


def test_arc_and_pointer_exist(ctx):
    tag, _ = make(ctx)
    assert dpg.does_item_exist(f"{tag}__knob")
    assert dpg.does_item_exist(f"{tag}__arc")
    assert dpg.does_item_exist(f"{tag}__ptr")


# ── scroll ───────────────────────────────────────────────────────────────────


def test_scroll_up_increases_by_one_step(ctx):
    tag, calls = make(ctx, default=0.50, step=0.01)
    k = K._knobs[tag]
    K._set(k, dpg.get_value(tag) + 1 * k.step)
    assert dpg.get_value(tag) == pytest.approx(0.51)
    assert calls == [pytest.approx(0.51)]


def test_scroll_down_decreases(ctx):
    tag, _ = make(ctx, default=0.50, step=0.01)
    k = K._knobs[tag]
    K._set(k, dpg.get_value(tag) - 1 * k.step)
    assert dpg.get_value(tag) == pytest.approx(0.49)


def test_scroll_clamps_at_both_ends(ctx):
    tag, _ = make(ctx, default=0.99, step=0.01)
    k = K._knobs[tag]
    for _ in range(50):
        K._set(k, dpg.get_value(tag) + k.step)
    assert dpg.get_value(tag) == pytest.approx(1.0)
    for _ in range(500):
        K._set(k, dpg.get_value(tag) - k.step)
    assert dpg.get_value(tag) == pytest.approx(0.0)


# ── drag ─────────────────────────────────────────────────────────────────────


def test_drag_up_increases(ctx):
    """Dragging up raises the value, as in every DAW."""
    tag, _ = make(ctx, default=0.5)
    k = K._knobs[tag]
    K._active_tag = tag
    k.drag_start_value = 0.5
    K._on_drag(None, [0, 0.0, -55.0])  # 55px up = quarter of a full sweep
    assert dpg.get_value(tag) == pytest.approx(0.75, abs=0.01)


def test_drag_down_decreases(ctx):
    tag, _ = make(ctx, default=0.5)
    k = K._knobs[tag]
    K._active_tag = tag
    k.drag_start_value = 0.5
    K._on_drag(None, [0, 0.0, 55.0])
    assert dpg.get_value(tag) == pytest.approx(0.25, abs=0.01)


def test_drag_is_anchored_not_cumulative(ctx):
    """DPG reports drag delta from the press, so re-applying must not compound."""
    tag, _ = make(ctx, default=0.5)
    k = K._knobs[tag]
    K._active_tag = tag
    k.drag_start_value = 0.5
    for _ in range(5):
        K._on_drag(None, [0, 0.0, -22.0])
    assert dpg.get_value(tag) == pytest.approx(0.6, abs=0.01)


def test_drag_clamps(ctx):
    tag, _ = make(ctx, default=0.5)
    k = K._knobs[tag]
    K._active_tag = tag
    k.drag_start_value = 0.5
    K._on_drag(None, [0, 0.0, -9999.0])
    assert dpg.get_value(tag) == pytest.approx(1.0)


def test_release_stops_dragging(ctx):
    tag, _ = make(ctx, default=0.5)
    K._active_tag = tag
    K._on_release(None, None)
    assert K._active_tag is None
    K._on_drag(None, [0, 0.0, -100.0])  # must be ignored
    assert dpg.get_value(tag) == pytest.approx(0.5)


# ── ranges and formatting ────────────────────────────────────────────────────


def test_non_unit_range(ctx):
    tag, _ = make(ctx, tag="ms", default=1500, lo=0, hi=5000, step=50, is_int=True, fmt="%.0f")
    k = K._knobs[tag]
    K._set(k, 1500 + k.step)
    assert dpg.get_value(tag) == pytest.approx(1550)


def test_int_knob_stays_whole(ctx):
    tag, _ = make(ctx, tag="i", default=10, lo=0, hi=100, step=1, is_int=True, fmt="%.0f")
    k = K._knobs[tag]
    K._set(k, 10.4)
    assert float(dpg.get_value(tag)).is_integer()


def test_callback_not_fired_when_value_unchanged(ctx):
    tag, calls = make(ctx, default=1.0, step=0.01)
    k = K._knobs[tag]
    K._set(k, 2.0)  # clamps to 1.0, i.e. no change
    assert calls == []


def test_detection_tab_knobs_build_and_bind():
    """The four real controls, built the way main_window builds them."""
    dpg.create_context()
    K._reset_for_tests()
    try:
        with dpg.window(tag="w"):
            with dpg.group(horizontal=True):
                K.add_knob("ui_hold_peak_band", "Peak", default=0.80,
                           min_value=0.0, max_value=1.0, step=0.01)
                K.add_knob("ui_hold_valley_band", "Valley", default=0.20,
                           min_value=0.0, max_value=1.0, step=0.01)
                K.add_knob("ui_hold_still_tol", "Still tol", default=0.05,
                           min_value=0.0, max_value=0.5, step=0.005, fmt="%.3f")
                K.add_knob("ui_hold_exit_delta", "Exit", default=0.15,
                           min_value=0.0, max_value=1.0, step=0.01, fmt="%.3f")
        assert dpg.get_value("ui_hold_peak_band") == pytest.approx(0.80)
        assert dpg.get_value("ui_hold_valley_band") == pytest.approx(0.20)
        assert dpg.get_value("ui_hold_still_tol") == pytest.approx(0.05)
        assert dpg.get_value("ui_hold_exit_delta") == pytest.approx(0.15)
    finally:
        dpg.destroy_context()
        K._reset_for_tests()


# ── drawn geometry ───────────────────────────────────────────────────────────


def test_pointer_sweeps_left_to_right_through_the_top(ctx):
    """
    At minimum the pointer aims lower-left, at half it aims straight up, at
    maximum lower-right — a hardware pot with its gap at the bottom.
    """
    tag, _ = make(ctx, default=0.0)
    k = K._knobs[tag]
    centre = k.size / 2.0

    def pointer_tip(value: float) -> tuple[float, float]:
        dpg.set_value(tag, value)
        K._redraw(k, force=True)
        return tuple(dpg.get_item_configuration(f"{tag}__ptr")["p2"])[:2]

    x0, y0 = pointer_tip(0.0)
    xh, yh = pointer_tip(0.5)
    x1, y1 = pointer_tip(1.0)

    assert x0 < centre and y0 > centre, "min should point lower-left"
    assert abs(xh - centre) < 1.0 and yh < centre, "half should point straight up"
    assert x1 > centre and y1 > centre, "max should point lower-right"


def test_value_arc_grows_with_value(ctx):
    tag, _ = make(ctx, default=0.0)
    k = K._knobs[tag]

    def arc_len(value: float) -> int:
        dpg.set_value(tag, value)
        K._redraw(k, force=True)
        return len(dpg.get_item_configuration(f"{tag}__arc")["points"])

    assert arc_len(0.0) < arc_len(0.5) < arc_len(1.0)


def test_hover_hit_test_does_not_raise(ctx):
    """
    _hovered() runs on every click and wheel event. It cannot be exercised
    without a real cursor, but it must at least be safe to call headlessly.
    """
    make(ctx)
    assert K._hovered() is None


# ── config round-trip for the derived timings ────────────────────────────────


def test_saving_config_with_none_overrides_does_not_raise(tmp_path):
    """
    Autosave runs on every parameter change, and TOML has no null. The
    detection overrides are None by default, so a naive dump raised TypeError
    and took the app down the first time a knob moved.
    """
    import shutil
    from dataclasses import replace
    from pathlib import Path

    from breath_midi.config.store import ConfigStore

    src = Path(__file__).parent.parent / "config.toml"
    dst = tmp_path / "config.toml"
    shutil.copy(src, dst)

    store = ConfigStore(dst)
    cfg = store.load()
    assert cfg.detection.min_hold_ms_override is None, "expected the None default"

    store.save(cfg)  # must not raise
    again = store.load()
    assert again == cfg, "config did not survive a save/load round trip"


def test_stickiness_drives_the_three_timings(tmp_path):
    import shutil
    from dataclasses import replace
    from pathlib import Path

    from breath_midi.config.store import ConfigStore

    src = Path(__file__).parent.parent / "config.toml"
    dst = tmp_path / "config.toml"
    shutil.copy(src, dst)
    store = ConfigStore(dst)
    cfg = store.load()

    low = replace(cfg.detection, phase_stickiness=0.0)
    high = replace(cfg.detection, phase_stickiness=1.0)
    assert low.min_phase_ms < high.min_phase_ms
    assert low.min_hold_ms < high.min_hold_ms
    assert low.hold_exit_delta < high.hold_exit_delta

    # And it persists.
    store.save(replace(cfg, detection=replace(cfg.detection, phase_stickiness=0.8)))
    assert store.load().detection.phase_stickiness == pytest.approx(0.8)


def test_an_explicit_pin_beats_stickiness(tmp_path):
    from dataclasses import replace
    from pathlib import Path

    from breath_midi.config.store import ConfigStore

    cfg = ConfigStore(Path(__file__).parent.parent / "config.toml").load()
    pinned = replace(cfg.detection, phase_stickiness=1.0, min_hold_ms_override=900)
    assert pinned.min_hold_ms == 900
