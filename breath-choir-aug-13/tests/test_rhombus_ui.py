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
    build_phase_rhombus,
    refresh_phase_rhombus,
    vertex_tag,
)

ALL_PHASES = [
    Phase.REST,
    Phase.INHALE,
    Phase.HOLD_FULL,
    Phase.EXHALE,
    Phase.HOLD_EMPTY,
]


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
        hold_full_note=66,
        hold_empty_note=70,
        hold_full_enabled=False,
        hold_empty_enabled=False,
    )
    defaults.update(kw)
    return DeviceUISnapshot(**defaults)


def test_rhombus_creates_all_four_vertices(dpg_context):
    with dpg.group(parent=dpg_context):
        build_phase_rhombus("t1", Phase.INHALE, (200, 100, 50), active=True)
    for p in (Phase.INHALE, Phase.HOLD_FULL, Phase.EXHALE, Phase.HOLD_EMPTY):
        assert dpg.does_item_exist(vertex_tag("t1", p)), f"missing vertex for {p}"
    # REST is not on the diamond — it is the cold-start state.
    assert not dpg.does_item_exist(vertex_tag("t1", Phase.REST))


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_only_active_phase_vertex_is_lit(dpg_context, phase: Phase):
    color = (200, 100, 50)
    with dpg.group(parent=dpg_context):
        build_phase_rhombus("t2", Phase.REST, color, active=True)
    refresh_phase_rhombus("t2", phase, color, active=True)

    lit = [
        p
        for p in (Phase.INHALE, Phase.HOLD_FULL, Phase.EXHALE, Phase.HOLD_EMPTY)
        if _is_device_color(vertex_tag("t2", p), color)
    ]
    if phase == Phase.REST:
        assert lit == [], "REST must leave every vertex dim"
    else:
        assert lit == [phase], f"expected only {phase} lit, got {lit}"


def _is_device_color(tag: str, color: tuple[int, int, int]) -> bool:
    """DPG normalises colors to 0–1 floats; compare tolerantly."""
    fill = list(dpg.get_item_configuration(tag)["fill"])
    got = [round(c * 255) if c <= 1.0 else round(c) for c in fill[:3]]
    return got == list(color)


def test_paused_device_dims_every_vertex(dpg_context):
    color = (200, 100, 50)
    with dpg.group(parent=dpg_context):
        build_phase_rhombus("t3", Phase.INHALE, color, active=False)
    for p in (Phase.INHALE, Phase.HOLD_FULL, Phase.EXHALE, Phase.HOLD_EMPTY):
        assert not _is_device_color(vertex_tag("t3", p), color)


def test_refresh_is_safe_when_vertices_absent(dpg_context):
    """A card can be torn down between frames — refresh must not raise."""
    refresh_phase_rhombus("never_built", Phase.INHALE, (1, 2, 3), active=True)


def test_every_breath_card_builds_with_holds(dpg_context):
    """The full device card, including the four note inputs and hold toggles."""
    from breath_midi.ui.every_breath_tab import EveryBreathTab

    class FakeRegistry:
        def get(self, uuid):
            return None

    class FakeHub:
        registry = FakeRegistry()

    tab = EveryBreathTab(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(phase=Phase.HOLD_FULL, hold_full_enabled=True)
    tab._build_card(snap, parent=dpg_context, prev_uuid=None, next_uuid=None)

    uuid = snap.uuid
    for tag in (
        f"eb_inote_{uuid}",
        f"eb_enote_{uuid}",
        f"eb_hfnote_{uuid}",
        f"eb_henote_{uuid}",
        f"eb_hfen_{uuid}",
        f"eb_heen_{uuid}",
    ):
        assert dpg.does_item_exist(tag), f"missing card control {tag}"

    assert dpg.get_value(f"eb_hfnote_{uuid}") == 66
    assert dpg.get_value(f"eb_henote_{uuid}") == 70
    assert dpg.get_value(f"eb_hfen_{uuid}") is True
    assert dpg.get_value(f"eb_heen_{uuid}") is False
    assert dpg.does_item_exist(vertex_tag(f"eb_rh_{uuid}", Phase.HOLD_FULL))


def test_group_breath_strip_builds_with_holds(dpg_context):
    """The Group Breath strip is the other lazily-built device view."""
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()

    # _build_strip parents into this row by tag.
    with dpg.group(parent=dpg_context, tag="gb_strip_row"):
        pass

    panel = GroupBreathBottomPanel(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot(uuid="dev-gb", phase=Phase.HOLD_EMPTY, hold_empty_enabled=True)
    panel._build_strip(snap)

    uuid = snap.uuid
    for tag in (
        f"gb_strip_hf_num_{uuid}",
        f"gb_strip_he_num_{uuid}",
        f"gb_strip_hf_en_{uuid}",
        f"gb_strip_he_en_{uuid}",
    ):
        assert dpg.does_item_exist(tag), f"missing strip control {tag}"
    assert dpg.does_item_exist(vertex_tag(f"gb_strip_rh_{uuid}", Phase.HOLD_EMPTY))

    for phase in ALL_PHASES:
        panel._refresh_strips([snapshot(uuid=uuid, phase=phase)])


def test_card_refresh_steps_through_phases(dpg_context):
    """Per-frame refresh must not raise for any phase, including the holds."""
    from breath_midi.ui.every_breath_tab import EveryBreathTab

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()

    tab = EveryBreathTab(FakeHub(), dpg_context)  # type: ignore[arg-type]
    snap = snapshot()
    tab._build_card(snap, parent=dpg_context, prev_uuid=None, next_uuid=None)
    for phase in ALL_PHASES:
        tab._refresh_cards([snapshot(phase=phase)])
