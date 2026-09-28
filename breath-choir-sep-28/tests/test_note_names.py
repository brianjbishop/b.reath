"""
Note names.

The octave convention is the whole point: these labels exist to be matched
against a pad in Ableton, and Ableton numbers octaves differently from
scientific pitch notation. One octave out is worse than no label at all.
"""

from __future__ import annotations

import pytest

from breath_midi.midi.note_names import note_label, note_name


def test_ableton_middle_c():
    """Ableton calls note 60 C3. Scientific pitch calls it C4. Follow Ableton."""
    assert note_name(60) == "C3"


def test_drum_rack_bottom_left_pad():
    """A default Drum Rack starts at C1 = 36. This is the number people look up."""
    assert note_name(36) == "C1"


@pytest.mark.parametrize(
    "note,expected",
    [(54, "F#2"), (55, "G2"), (56, "G#2"), (57, "A2"), (61, "C#3"), (72, "C4")],
)
def test_the_notes_devices_actually_get(note, expected):
    assert note_name(note) == expected


def test_every_note_in_range_is_nameable():
    for n in range(128):
        name = note_name(n)
        assert name[0] in "ABCDEFG"
        assert name[-1].isdigit() or name[-2] == "-"


def test_zero_reads_as_silent():
    """0 is the app's silent sentinel, not a pitch anyone will hear."""
    assert note_label(0) == "silent"


def test_a_real_note_gets_its_name():
    assert note_label(54) == "F#2"


def test_note_name_still_names_zero():
    """note_name is the plain conversion; only note_label knows about silence."""
    assert note_name(0) == "C-2"


# ── in the device strip ──────────────────────────────────────────────────────


def test_the_strip_shows_a_name_beside_each_note():
    """Three numbers, three names, so a drum pad can be matched at a glance."""
    from pathlib import Path

    import dearpygui.dearpygui as dpg

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    from .test_rhombus_ui import snapshot

    dpg.create_context()

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    for tag in ("theme_circle_gray", "theme_circle_yellow", "theme_gate_green"):
        with dpg.theme(tag=tag):
            pass
    with dpg.window(tag="root"):
        with dpg.group(tag="gb_strip_row"):
            pass
        panel = GroupBreathBottomPanel(FakeHub(), "root")  # type: ignore[arg-type]
        snap = snapshot(uuid="dev-n", inhale_note=54, exhale_note=55, hold_note=0)
        panel._build_strip(snap)

    u = snap.uuid
    assert dpg.get_value(f"gb_strip_inh_name_{u}") == "F#2"
    assert dpg.get_value(f"gb_strip_exh_name_{u}") == "G2"
    assert dpg.get_value(f"gb_strip_h_name_{u}") == "silent"
    dpg.destroy_context()


def test_the_name_follows_the_number():
    """Change the note, the name must follow — it is the reason this exists."""
    from pathlib import Path

    import dearpygui.dearpygui as dpg

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    from .test_rhombus_ui import snapshot

    dpg.create_context()

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

        def get_ui_snapshot(self):
            return []

    for tag in ("theme_circle_gray", "theme_circle_yellow", "theme_gate_green"):
        with dpg.theme(tag=tag):
            pass
    with dpg.window(tag="root"):
        with dpg.group(tag="gb_strip_row"):
            pass
        panel = GroupBreathBottomPanel(FakeHub(), "root")  # type: ignore[arg-type]
        snap = snapshot(uuid="dev-f", inhale_note=54)
        panel._build_strip(snap)
        panel._known_uuids = [snap.uuid]

    moved = snapshot(uuid="dev-f", inhale_note=36, exhale_note=60, hold_note=72)
    panel._refresh_strips([moved])
    u = snap.uuid
    assert dpg.get_value(f"gb_strip_inh_name_{u}") == "C1"
    assert dpg.get_value(f"gb_strip_exh_name_{u}") == "C3"
    assert dpg.get_value(f"gb_strip_h_name_{u}") == "C4"
    dpg.destroy_context()
