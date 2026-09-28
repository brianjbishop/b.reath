"""
Device timeout, over the merged stream.

The timeout used to live inside MultiDeviceOscSource, which meant it only ever
applied to phones. Playback posts to the feed directly and bypassed it entirely,
so a track's performers never disappeared, never released their held notes, and
the dropout track never dropped out.

It now belongs to the hub, which sees every sample from every source, so one
rule covers phones and tracks alike.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.tracks.file import Track, TrackDevice, write_track
from breath_midi.types import BreathSample

from .test_hold_triggers import base_config
from .test_presets import make_det

# Short enough to test in a moment, long enough to be a real gap.
FAST_TIMEOUT = 0.6


@pytest.fixture
def hub():
    h = EveryBreathHub(config=base_config(), osc_port=8816)
    h.set_device_timeout(FAST_TIMEOUT)
    yield h
    h.stop_all_tracks()


def tiny_track(path: Path, seconds: float = 0.1) -> Path:
    write_track(path, Track(
        name="tiny", created="now", duration_s=seconds, source="generated",
        detection=make_det(),
        devices=[TrackDevice("x", "Ghost", (200, 100, 100), 54, 55)],
        samples=[(0.0, 0, 0.5), (seconds, 0, 0.6)],
    ))
    return path


def test_a_finished_track_lets_its_devices_go(hub, tmp_path: Path):
    """The reported bug: performers from an ended track stayed on screen."""
    hub.load_track(tiny_track(tmp_path / "t.breath.json"))
    time.sleep(0.3)
    assert hub.registry.connected_uuids(), "never connected in the first place"
    time.sleep(FAST_TIMEOUT + 0.8)
    assert hub.registry.connected_uuids() == set(), "finished track still connected"


def test_a_finished_track_releases_its_held_notes(hub, tmp_path: Path):
    """The worse half: a performer stopping mid-inhale left a key down."""
    hub.load_track(tiny_track(tmp_path / "t.breath.json"))
    time.sleep(0.3)
    uuid = next(iter(hub.registry.connected_uuids()))
    time.sleep(FAST_TIMEOUT + 0.8)
    runtime = hub._runtimes.get(uuid)
    assert runtime is not None
    assert runtime._voice.sounding_note is None, "a note is still held down"


def test_a_live_phone_still_times_out(hub):
    """The behaviour that already worked must keep working."""
    hub.registry.get_or_create("phone-a")
    hub._ensure_midi_sink()
    hub._on_new_device("phone-a")
    hub._ensure_feed()
    hub._on_sample(BreathSample(t=0.0, amp=0.5, source_id="phone-a"))
    assert "phone-a" in hub.registry.connected_uuids()
    time.sleep(FAST_TIMEOUT + 0.8)
    assert "phone-a" not in hub.registry.connected_uuids()


def test_a_device_that_keeps_sending_is_kept(hub):
    hub.registry.get_or_create("phone-a")
    hub._ensure_midi_sink()
    hub._on_new_device("phone-a")
    hub._ensure_feed()
    deadline = time.monotonic() + (FAST_TIMEOUT + 0.6)
    while time.monotonic() < deadline:
        hub._on_sample(BreathSample(t=0.0, amp=0.5, source_id="phone-a"))
        time.sleep(0.05)
    assert "phone-a" in hub.registry.connected_uuids(), "dropped a live device"


def test_a_device_that_comes_back_reconnects(hub):
    """A phone that drops and returns must come back, not stay gone."""
    hub.registry.get_or_create("phone-a")
    hub._ensure_midi_sink()
    hub._on_new_device("phone-a")
    hub._ensure_feed()
    hub._on_sample(BreathSample(t=0.0, amp=0.5, source_id="phone-a"))
    time.sleep(FAST_TIMEOUT + 0.8)
    assert "phone-a" not in hub.registry.connected_uuids()

    hub._on_new_device("phone-a")
    hub._on_sample(BreathSample(t=0.0, amp=0.5, source_id="phone-a"))
    assert "phone-a" in hub.registry.connected_uuids(), "did not come back"


def test_the_dropout_track_actually_drops_out(hub, tmp_path: Path):
    """
    The shipped track promises this and never delivered it.

    Two performers; the second stops early. With a short timeout the gap in the
    file is long enough that the second must disappear while the first plays on.
    """
    path = tmp_path / "drop.breath.json"
    write_track(path, Track(
        name="drop", created="now", duration_s=3.0, source="generated",
        detection=make_det(),
        devices=[TrackDevice("stay", "Stayer", (1, 2, 3), 54, 55),
                 TrackDevice("go", "Leaver", (4, 5, 6), 56, 57)],
        # Interleaved by time, the way real arrivals are — read_track rejects
        # a file whose timestamps go backwards, which is how this was caught.
        samples=sorted(
            [(i * 0.05, 0, 0.5) for i in range(60)]          # stays 3s
            + [(i * 0.05, 1, 0.5) for i in range(6)],        # stops at 0.3s
            key=lambda row: (row[0], row[1]),
        ),
    ))
    prefix = hub.load_track(path)
    time.sleep(0.4)
    assert f"{prefix}:go" in hub.registry.connected_uuids()
    time.sleep(FAST_TIMEOUT + 0.8)
    connected = hub.registry.connected_uuids()
    assert f"{prefix}:go" not in connected, "Leaver never left"
    assert f"{prefix}:stay" in connected, "Stayer left too"
