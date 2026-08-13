"""
Device-card UI smoke tests.

Device cards are built lazily when a phone connects, so simply launching the
app never touches them — a bad DPG tag or a stale reference would only surface
mid-performance.  These build the real cards against fake snapshots inside a
headless DPG context, and step every phase through the rhombus.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from breath_midi.every_breath.hub import DeviceUISnapshot
from breath_midi.types import Phase
from breath_midi.ui.widgets.phase_rhombus import (
    HOLD_BOTTOM,
    HOLD_TOP,
    build_phase_rhombus,
    refresh_phase_rhombus,
    vertex_tag,
)

ALL_PHASES = [Phase.REST, Phase.INHALE, Phase.HOLD, Phase.EXHALE]


@pytest.fixture
def dpg_context():
    dpg.create_context()
    with dpg.window(tag="test_root"):
        pass
    yield "test_root"
    dpg.destroy_context()


def snapshot(uuid: str = "dev-1", phase: Phase = Phase.REST, **kw) -> DeviceUISnapshot:
    defaults = dict(
        uuid=uuid,
        name="Performer 1",
        color=(200, 100, 50),
        inhale_note=54,
        exhale_note=58,
        phase=phase,
        raw_amp=0.5,
        muted=False,
        soloed=False,
        waveform=[0.1, 0.2, 0.3],
        active=True,
        cc_mode=False,
        cc_value=127,
        cons_n=0,
        cons_tolerance=0.3,
        consistent_gate_open=True,
        hold_note=70,
    )
    defaults.update(kw)
    return DeviceUISnapshot(**defaults)


def test_rhombus_creates_all_four_vertices(dpg_context):
    with dpg.group(parent=dpg_context):
        build_phase_rhombus("t1", Phase.INHALE, (200, 100, 50), active=True)
    for v in (Phase.INHALE, HOLD_TOP, Phase.EXHALE, HOLD_BOTTOM):
        assert dpg.does_item_exist(vertex_tag("t1", v)), f"missing vertex for {v}"
    # REST is not on the diamond — it is the cold-start state.
    assert not dpg.does_item_exist(vertex_tag("t1", Phase.REST))


@pytest.mark.parametrize(
    "phase,amp,expected",
    [
        (Phase.REST, 0.5, None),
        (Phase.INHALE, 0.5, Phase.INHALE.value),
        (Phase.EXHALE, 0.5, Phase.EXHALE.value),
        (Phase.HOLD, 0.95, HOLD_TOP),
        (Phase.HOLD, 0.05, HOLD_BOTTOM),
    ],
)
def test_hold_lights_top_or_bottom_by_amplitude(dpg_context, phase, amp, expected):
    """One HOLD state, but the vertex shows which end of the breath it is at."""
    color = (200, 100, 50)
    with dpg.group(parent=dpg_context):
        build_phase_rhombus("t2", Phase.REST, color, active=True)
    refresh_phase_rhombus("t2", phase, color, active=True, amp=amp, peak_band=0.8)

    lit = [
        v
        for v in (Phase.INHALE.value, HOLD_TOP, Phase.EXHALE.value, HOLD_BOTTOM)
        if _is_device_color(vertex_tag("t2", v), color)
    ]
    assert lit == ([] if expected is None else [expected])


def _is_device_color(tag: str, color: tuple[int, int, int]) -> bool:
    """DPG normalises colors to 0–1 floats; compare tolerantly."""
    fill = list(dpg.get_item_configuration(tag)["fill"])
    got = [round(c * 255) if c <= 1.0 else round(c) for c in fill[:3]]
    return got == list(color)


def test_paused_device_dims_every_vertex(dpg_context):
    color = (200, 100, 50)
    with dpg.group(parent=dpg_context):
        build_phase_rhombus("t3", Phase.INHALE, color, active=False)
    for v in (Phase.INHALE.value, HOLD_TOP, Phase.EXHALE.value, HOLD_BOTTOM):
        assert not _is_device_color(vertex_tag("t3", v), color)


def test_refresh_is_safe_when_vertices_absent(dpg_context):
    """A card can be torn down between frames — refresh must not raise."""
    refresh_phase_rhombus("never_built", Phase.INHALE, (1, 2, 3), active=True)


def test_every_breath_card_builds_with_holds(dpg_context):
    """The full device card, including the four note inputs and hold toggles."""
    from breath_midi.ui.every_breath_tab import EveryBreathTab

    from pathlib import Path

    from breath_midi.config.store import ConfigStore

    class FakeRegistry:
        def get(self, uuid):
            return None

    class FakeHub:
        registry = FakeRegistry()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    tab = EveryBreathTab(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(phase=Phase.HOLD)
    tab._build_card(snap, parent=dpg_context, prev_uuid=None, next_uuid=None)

    uuid = snap.uuid
    for tag in (f"eb_inote_{uuid}", f"eb_enote_{uuid}", f"eb_hnote_{uuid}"):
        assert dpg.does_item_exist(tag), f"missing card control {tag}"
    assert dpg.get_value(f"eb_hnote_{uuid}") == 70
    assert dpg.does_item_exist(vertex_tag(f"eb_rh_{uuid}", HOLD_TOP))


def test_group_breath_strip_builds_with_holds(dpg_context):
    """The Group Breath strip is the other lazily-built device view."""
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    from pathlib import Path

    from breath_midi.config.store import ConfigStore

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    # _build_strip parents into this row by tag.
    with dpg.group(parent=dpg_context, tag="gb_strip_row"):
        pass

    panel = GroupBreathBottomPanel(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(uuid="dev-gb", phase=Phase.HOLD)
    panel._build_strip(snap)

    uuid = snap.uuid
    for tag in (f"gb_strip_h_num_{uuid}", f"gb_strip_inh_num_{uuid}"):
        assert dpg.does_item_exist(tag), f"missing strip control {tag}"
    assert dpg.does_item_exist(vertex_tag(f"gb_strip_rh_{uuid}", HOLD_BOTTOM))

    for phase in ALL_PHASES:
        panel._refresh_strips([snapshot(uuid=uuid, phase=phase)])


def test_card_refresh_steps_through_phases(dpg_context):
    """Per-frame refresh must not raise for any phase, including the holds."""
    from breath_midi.ui.every_breath_tab import EveryBreathTab

    from pathlib import Path

    from breath_midi.config.store import ConfigStore

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    tab = EveryBreathTab(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot()
    tab._build_card(snap, parent=dpg_context, prev_uuid=None, next_uuid=None)
    for phase in ALL_PHASES:
        tab._refresh_cards([snapshot(phase=phase)])


# ── Group Breath side panel ──────────────────────────────────────────────────


def test_group_breath_has_collapsible_detection_and_guide(dpg_context):
    """
    The hold controls live in the Group Breath side column, above the Breath
    Guide, and both sections collapse. Built lazily like the rest of that tab,
    so nothing here is exercised by simply launching the app.
    """
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_tab import GroupBreathTab
    from breath_midi.ui.widgets import knob as K

    K._reset_for_tests()

    class FakeHub:
        registry = type(
            "R", (), {"get": lambda self, u: None, "all_entries": lambda self: [],
                      "connected_uuids": lambda self: set()},
        )()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

        def get_ui_snapshot(self):
            return []

    calls: list[int] = []
    tab = GroupBreathTab(  # type: ignore[arg-type]
        hub=FakeHub(), parent_tag=dpg_context, on_change=lambda *_: calls.append(1)
    )
    tab.build()

    assert dpg.does_item_exist("gb_detection_header"), "Detection section missing"
    assert dpg.does_item_exist("gb_guide_header"), "Breath Guide section missing"

    for tag in (
        "ui_hold_enabled", "ui_min_hold_ms", "ui_hold_peak_band",
        "ui_hold_valley_band", "ui_hold_still_tol", "ui_hold_exit_delta",
    ):
        assert dpg.does_item_exist(tag), f"missing control {tag}"

    # Detection must come before the Breath Guide in the column.
    children = dpg.get_item_children("gb_anim_col", 1)
    assert children.index(dpg.get_alias_id("gb_detection_header")) < children.index(
        dpg.get_alias_id("gb_guide_header")
    ), "Detection should sit above the Breath Guide"

    # Turning a knob must reach main_window's apply hook.
    k = K._knobs["ui_hold_peak_band"]
    K._set(k, 0.70)
    assert calls, "knob change did not call on_change"
    assert dpg.get_value("ui_hold_peak_band") == pytest.approx(0.70)
    K._reset_for_tests()


# ── arrow labels on the note fields ──────────────────────────────────────────


def test_arrow_labels_point_the_way_the_breath_moves(dpg_context):
    """
    ↗ inhale, → hold, ↘ exhale. Drawn rather than typed, because DPG's default
    font atlas does not carry those codepoints.
    """
    from breath_midi.ui.widgets.arrow_label import add_arrow_label

    with dpg.group(parent=dpg_context):
        for p, tag in (
            (Phase.INHALE, "lbl_in"),
            (Phase.HOLD, "lbl_hd"),
            (Phase.EXHALE, "lbl_ex"),
        ):
            add_arrow_label(p, tag=tag)

    def tip_tail(tag):
        cfg = dpg.get_item_configuration(tag)
        return tuple(cfg["p1"])[:2], tuple(cfg["p2"])[:2]

    # DPG draws the head at p1, so p1 is the tip.
    (tx, ty), (bx, by) = tip_tail("lbl_in")
    assert tx > bx and ty < by, "inhale should point up and to the right"

    (tx, ty), (bx, by) = tip_tail("lbl_ex")
    assert tx > bx and ty > by, "exhale should point down and to the right"

    (tx, ty), (bx, by) = tip_tail("lbl_hd")
    assert tx > bx and abs(ty - by) < 0.5, "hold should point level to the right"


def test_card_uses_arrow_labels_not_text(dpg_context):
    """The three note fields are labelled by arrows on a real device card."""
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.every_breath_tab import EveryBreathTab

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    tab = EveryBreathTab(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot()
    tab._build_card(snap, parent=dpg_context, prev_uuid=None, next_uuid=None)
    for tag in (
        f"eb_lbl_in_{snap.uuid}",
        f"eb_lbl_ex_{snap.uuid}",
        f"eb_lbl_hd_{snap.uuid}",
    ):
        assert dpg.does_item_exist(tag), f"missing arrow label {tag}"


def test_tolerance_glyph_greys_out_when_n_is_zero(dpg_context):
    """
    Tolerance only means anything while the consistency gate is on. With N=0
    the gate is bypassed, so both the glyph and the field must read as inert.
    """
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel
    from breath_midi.ui.widgets.arrow_label import DIM_COLOR

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    with dpg.group(parent=dpg_context, tag="gb_strip_row"):
        pass
    panel = GroupBreathBottomPanel(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(uuid="dev-tol", cons_n=0)
    panel._build_strip(snap)

    uuid = snap.uuid
    glyph, field = f"gb_strip_tol_lbl_{uuid}", f"gb_strip_cons_tol_{uuid}"
    assert dpg.does_item_exist(glyph), "tolerance glyph missing"

    def glyph_colour():
        child = dpg.get_item_children(glyph, 2)[0]
        c = dpg.get_item_configuration(child)["color"]
        return [round(v * 255) if v <= 1.0 else round(v) for v in c[:3]]

    # N = 0: dim, and the field is not editable.
    assert glyph_colour() == list(DIM_COLOR[:3])
    assert dpg.get_item_configuration(field)["enabled"] is False

    # N = 3: lit, and editable again.
    panel._refresh_strips([snapshot(uuid=uuid, cons_n=3)])
    assert glyph_colour() != list(DIM_COLOR[:3])
    assert dpg.get_item_configuration(field)["enabled"] is True
