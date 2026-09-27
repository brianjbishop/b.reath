"""
Recording from the hub.

Recording taps the live sample path. It is refused while a track is playing —
that would only produce a lossy copy of a file that already exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.tracks.file import read_track, write_track
from breath_midi.types import BreathSample

from .test_hold_triggers import base_config
from .test_track_file import sample_track


@pytest.fixture
def hub(tmp_path: Path):
    h = EveryBreathHub(config=base_config(), osc_port=8814)
    h._recordings_dir = tmp_path
    yield h
    for prefix in list(h.playing_tracks):
        h.stop_track(prefix)


def feed(hub, uuid="phone-a", n=5):
    hub.registry.get_or_create(uuid)
    for i in range(n):
        hub._on_sample(BreathSample(t=i * 0.02, amp=i / 10, source_id=uuid))


def test_not_recording_by_default(hub):
    assert hub.is_recording is False


def test_records_live_samples(hub):
    hub.start_recording("take one")
    assert hub.is_recording is True
    feed(hub)
    path = hub.stop_recording()
    assert path is not None and path.exists()
    track = read_track(path)
    assert len(track.samples) == 5
    assert track.source == "recorded"


def test_stop_without_start_returns_none(hub):
    assert hub.stop_recording() is None


def test_stopping_clears_the_recording_state(hub):
    hub.start_recording("take")
    feed(hub)
    hub.stop_recording()
    assert hub.is_recording is False


def test_recording_carries_the_current_dials(hub):
    hub.start_recording("take two")
    feed(hub, n=1)
    track = read_track(hub.stop_recording())
    assert track.detection == hub._config.detection


def test_recording_carries_device_names(hub):
    hub.registry.get_or_create("phone-a")
    hub.registry.set_name("phone-a", "Ana")
    hub.start_recording("named")
    feed(hub)
    track = read_track(hub.stop_recording())
    assert track.devices[0].name == "Ana"


def test_recording_is_refused_while_a_track_plays(hub, tmp_path: Path):
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    hub.load_track(p)
    hub.start_recording("nope")
    assert hub.is_recording is False


def test_an_empty_take_writes_nothing(hub):
    """Hitting record and stop with no one breathing should not litter the folder."""
    hub.start_recording("empty")
    assert hub.stop_recording() is None
    assert list(hub._recordings_dir.glob("*.breath.json")) == []


def test_filename_is_derived_from_the_take_name(hub):
    hub.start_recording("Hive show take 3")
    feed(hub)
    path = hub.stop_recording()
    assert path.name == "Hive show take 3.breath.json"


def test_a_name_with_a_slash_cannot_escape_the_folder(hub):
    hub.start_recording("../../escape")
    feed(hub)
    path = hub.stop_recording()
    assert path.parent == hub._recordings_dir


def test_the_recorded_track_replays(hub):
    """A round trip through the real loader — the point of recording at all."""
    hub.registry.get_or_create("phone-a")
    hub.registry.set_name("phone-a", "Ana")
    hub.start_recording("replayable")
    feed(hub, n=10)
    path = hub.stop_recording()
    prefix = hub.load_track(path)
    assert prefix in hub.playing_tracks
    hub.stop_track(prefix)
