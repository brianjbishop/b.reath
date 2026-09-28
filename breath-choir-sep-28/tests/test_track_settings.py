"""
A track carries its devices' settings, and loading restores them.

The trap this guards: registry.get_or_create auto-assigns notes and a colour to
any device it has not seen, counting up from _next_index. A loaded track has to
override all of it, or a performer comes back with whatever number happened to
be next rather than the one they were recorded with.

It went unnoticed because the generated tracks use 54/55, 56/57 ... which is
exactly what the auto-assigner produces. Every device here is deliberately given
settings the auto-assigner would never choose.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.tracks.file import Track, TrackDevice, read_track, write_track

from .test_hold_triggers import base_config
from .test_presets import make_det


@pytest.fixture
def hub():
    h = EveryBreathHub(config=base_config(), osc_port=8818)
    yield h
    h.stop_all_tracks()


def odd_track(path: Path) -> Path:
    """Nothing here matches what a fresh device would be given."""
    write_track(path, Track(
        name="odd", created="now", duration_s=0.1, source="recorded",
        detection=make_det(),
        devices=[
            TrackDevice("a", "Ana", (11, 22, 33), 90, 91, 9,
                        hold_note=95, cons_n=5, cons_tolerance=0.42),
            TrackDevice("b", "Bo", (44, 55, 66), 100, 101, 12,
                        hold_note=0, cons_n=3, cons_tolerance=0.11),
        ],
        samples=[(0.0, 0, 0.5), (0.0, 1, 0.5)],
    ))
    return path


def test_every_setting_round_trips_through_the_file(tmp_path: Path):
    track = read_track(odd_track(tmp_path / "t.breath.json"))
    a, b = track.devices
    assert (a.inhale_note, a.exhale_note, a.hold_note) == (90, 91, 95)
    assert (a.midi_channel, a.cons_n) == (9, 5)
    assert a.cons_tolerance == pytest.approx(0.42)
    assert (b.hold_note, b.cons_n) == (0, 3)


def test_loading_restores_the_notes_not_the_auto_assigned_ones(hub, tmp_path: Path):
    """The actual bug: 90/91 must survive, not become 54/55."""
    prefix = hub.load_track(odd_track(tmp_path / "t.breath.json"))
    time.sleep(0.3)
    entry = hub.registry.get(f"{prefix}:a")
    assert (entry.inhale_note, entry.exhale_note) == (90, 91)


def test_loading_restores_the_hold_note(hub, tmp_path: Path):
    prefix = hub.load_track(odd_track(tmp_path / "t.breath.json"))
    time.sleep(0.3)
    assert hub.registry.get(f"{prefix}:a").hold_note == 95
    assert hub.registry.get(f"{prefix}:b").hold_note == 0, "silent hold was overwritten"


def test_loading_restores_the_gate_and_tolerance(hub, tmp_path: Path):
    prefix = hub.load_track(odd_track(tmp_path / "t.breath.json"))
    time.sleep(0.3)
    entry = hub.registry.get(f"{prefix}:a")
    assert entry.cons_n == 5
    assert entry.cons_tolerance == pytest.approx(0.42)


def test_loading_restores_name_colour_and_channel(hub, tmp_path: Path):
    prefix = hub.load_track(odd_track(tmp_path / "t.breath.json"))
    time.sleep(0.3)
    entry = hub.registry.get(f"{prefix}:a")
    assert entry.name == "Ana"
    assert entry.color == (11, 22, 33)
    assert entry.midi_channel == 9


def test_the_live_runtime_uses_the_restored_notes(hub, tmp_path: Path):
    """Restoring the entry is not enough — the voice has to be built from it."""
    prefix = hub.load_track(odd_track(tmp_path / "t.breath.json"))
    time.sleep(0.3)
    voice = hub._runtimes[f"{prefix}:a"]._voice
    assert voice._channel == 8                      # channel 9, zero based
    assert 90 in voice._notes.values()


def test_a_track_without_the_newer_fields_still_loads(hub, tmp_path: Path):
    """Additive fields: an older file must keep working, with sane defaults."""
    import json

    p = odd_track(tmp_path / "t.breath.json")
    raw = json.loads(p.read_text())
    for d in raw["devices"]:
        for key in ("hold_note", "cons_n", "cons_tolerance"):
            d.pop(key, None)
    p.write_text(json.dumps(raw))

    track = read_track(p)
    assert track.devices[0].hold_note == 0
    assert track.devices[0].cons_n == 0
