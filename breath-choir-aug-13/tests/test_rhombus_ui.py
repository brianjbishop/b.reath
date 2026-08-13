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
    HOLD_PEAK,
    HOLD_VALLEY,
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
    for v in (Phase.INHALE, HOLD_PEAK, Phase.EXHALE, HOLD_VALLEY):
        assert dpg.does_item_exist(vertex_tag("t1", v)), f"missing vertex for {v}"
    # REST is not on the diamond — it is the cold-start state.
    assert not dpg.does_item_exist(vertex_tag("t1", Phase.REST))


@pytest.mark.parametrize(
    "phase,amp,expected",
    [
        (Phase.REST, 0.5, None),
        (Phase.INHALE, 0.5, Phase.INHALE.value),
        (Phase.EXHALE, 0.5, Phase.EXHALE.value),
        (Phase.HOLD, 0.95, HOLD_PEAK),   # held at the top -> right vertex
        (Phase.HOLD, 0.05, HOLD_VALLEY), # held at the bottom -> left vertex
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
        for v in (Phase.INHALE.value, HOLD_PEAK, Phase.EXHALE.value, HOLD_VALLEY)
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
    for v in (Phase.INHALE.value, HOLD_PEAK, Phase.EXHALE.value, HOLD_VALLEY):
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
    assert dpg.does_item_exist(vertex_tag(f"eb_rh_{uuid}", HOLD_PEAK))


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
    assert dpg.does_item_exist(vertex_tag(f"gb_strip_rh_{uuid}", HOLD_VALLEY))

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
        "ui_hold_enabled", "ui_phase_stickiness", "ui_hold_peak_band",
        "ui_hold_valley_band", "ui_hold_still_tol",
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


def test_rhombus_orientation_inhale_top_exhale_bottom(dpg_context):
    """
    Rising to the top, falling to the bottom, holds either side. Read
    clockwise that is the whole cycle: in, hold, out, hold.
    """
    from breath_midi.ui.widgets.phase_rhombus import _points

    size = 60
    c = size / 2.0
    pts = _points(size)
    assert pts[Phase.INHALE.value][1] < c, "inhale should be at the top"
    assert pts[Phase.EXHALE.value][1] > c, "exhale should be at the bottom"
    assert pts[HOLD_PEAK][0] > c and abs(pts[HOLD_PEAK][1] - c) < 0.5, \
        "peak hold should be the right vertex"
    assert pts[HOLD_VALLEY][0] < c and abs(pts[HOLD_VALLEY][1] - c) < 0.5, \
        "valley hold should be the left vertex"


def test_strip_gate_is_a_button_beside_note(dpg_context):
    """Gate moved out of the rhombus row and in with M / S / Note."""
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    for tag in ("theme_circle_gray", "theme_circle_yellow", "theme_gate_green"):
        with dpg.theme(tag=tag):
            pass
    with dpg.group(parent=dpg_context, tag="gb_strip_row"):
        pass

    panel = GroupBreathBottomPanel(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(uuid="dev-g", cons_n=3, consistent_gate_open=True)
    panel._build_strip(snap)

    gate = f"gb_strip_gate_{snap.uuid}"
    assert dpg.does_item_exist(gate)
    assert dpg.get_item_configuration(gate)["label"] == "Gate"
    # The old dot is gone.
    assert not dpg.does_item_exist(f"gb_strip_gate_rect_{snap.uuid}")


def test_strip_name_is_editable_on_double_click(dpg_context):
    """Double-click swaps the label for an input; Enter commits the new name."""
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    renamed: list[tuple[str, str]] = []

    class FakeRegistry:
        def get(self, uuid):
            return type("E", (), {"name": "Performer 1"})()

    class FakeHub:
        registry = FakeRegistry()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

        def set_name(self, uuid, name):
            renamed.append((uuid, name))

    for tag in ("theme_circle_gray", "theme_circle_yellow", "theme_gate_green"):
        with dpg.theme(tag=tag):
            pass
    with dpg.group(parent=dpg_context, tag="gb_strip_row"):
        pass

    panel = GroupBreathBottomPanel(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(uuid="dev-n")
    panel._build_strip(snap)
    label, editor = f"gb_strip_name_{snap.uuid}", f"gb_strip_name_edit_{snap.uuid}"

    # Starts as a label.
    assert dpg.is_item_shown(label) and not dpg.is_item_shown(editor)

    panel._begin_rename(snap.uuid)
    assert dpg.is_item_shown(editor) and not dpg.is_item_shown(label)

    dpg.set_value(editor, "Alto 2")
    panel._on_name_commit(snap.uuid)
    assert renamed == [(snap.uuid, "Alto 2")]
    assert dpg.is_item_shown(label) and not dpg.is_item_shown(editor)
    assert dpg.get_value(label) == "Alto 2"


def test_blank_rename_is_ignored(dpg_context):
    """An empty box should not wipe the device name."""
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    renamed: list = []

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: type("E", (), {"name": "X"})()})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

        def set_name(self, uuid, name):
            renamed.append(name)

    for tag in ("theme_circle_gray", "theme_circle_yellow", "theme_gate_green"):
        with dpg.theme(tag=tag):
            pass
    with dpg.group(parent=dpg_context, tag="gb_strip_row"):
        pass
    panel = GroupBreathBottomPanel(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(uuid="dev-b")
    panel._build_strip(snap)
    panel._begin_rename(snap.uuid)
    dpg.set_value(f"gb_strip_name_edit_{snap.uuid}", "   ")
    panel._on_name_commit(snap.uuid)
    assert renamed == []


def test_enter_commits_an_open_rename(dpg_context):
    """
    The input already sets on_enter, but that did not fire for a widget that
    gets shown and hidden — only clicking away committed. A global key handler
    makes it deterministic, so this drives that path directly.
    """
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    saved: list[tuple[str, str]] = []

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: type("E", (), {"name": "old"})()})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

        def set_name(self, uuid, name):
            saved.append((uuid, name))

    for tag in ("theme_circle_gray", "theme_circle_yellow", "theme_gate_green"):
        with dpg.theme(tag=tag):
            pass
    with dpg.group(parent=dpg_context, tag="gb_strip_row"):
        pass

    panel = GroupBreathBottomPanel(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(uuid="dev-e")
    panel._build_strip(snap)
    panel._built_uuids = [snap.uuid]

    panel._begin_rename(snap.uuid)
    dpg.set_value(f"gb_strip_name_edit_{snap.uuid}", "Tenor 1")
    panel._commit_open_rename()          # what the Enter key handler calls

    assert saved == [(snap.uuid, "Tenor 1")]
    assert not dpg.is_item_shown(f"gb_strip_name_edit_{snap.uuid}")


def test_enter_with_no_rename_open_is_harmless(dpg_context):
    from pathlib import Path

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    panel = GroupBreathBottomPanel(FakeHub(), dpg_context)  # type: ignore[arg-type]
    panel._commit_open_rename()   # must not raise


def test_breath_guide_holds_for_the_configured_beats():
    """Hold beats pause the circle; zero collapses back to plain in/out."""
    from breath_midi.ui.group_breath_animation import _NEXT_PHASE, GroupBreathAnimation

    assert _NEXT_PHASE == {
        "inhale": "hold_full",
        "hold_full": "exhale",
        "exhale": "hold_empty",
        "hold_empty": "inhale",
    }

    anim = GroupBreathAnimation()
    anim._bpm = 60.0          # one beat per second
    anim._inhale_beats = 2
    anim._exhale_beats = 2

    anim._hold_beats = 0
    spb = 1.0
    assert anim._phase_duration(spb, "hold_full") == 0.0
    assert anim._phase_duration(spb, "inhale") == 2.0

    anim._hold_beats = 3
    assert anim._phase_duration(spb, "hold_full") == 3.0
    assert anim._phase_duration(spb, "hold_empty") == 3.0


def test_track_buttons_are_mirrored_arrows(dpg_context):
    """Import points into the tray, export points out of it."""
    from breath_midi.ui.widgets.tray_icon import tray_button

    with dpg.group(parent=dpg_context):
        tray_button("t_imp", into_tray=True)
        tray_button("t_exp", into_tray=False)

    def head_and_tail(tag):
        arrows = [c for c in dpg.get_item_children(tag, 2)
                  if dpg.get_item_type(c).endswith("mvDrawArrow")]
        cfg = dpg.get_item_configuration(arrows[0])
        return tuple(cfg["p1"])[:2], tuple(cfg["p2"])[:2]

    (hx, hy), (tx, ty) = head_and_tail("t_imp")
    assert hy > ty, "import arrow should point down into the tray"
    (hx, hy), (tx, ty) = head_and_tail("t_exp")
    assert hy < ty, "export arrow should point up out of the tray"
