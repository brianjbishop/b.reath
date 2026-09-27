"""
Loading tracks into the hub.

A loaded track adds performers to the choir rather than replacing the live
input, so these hubs never bind a UDP port — playback needs none.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.tracks.file import write_track

from .test_hold_triggers import base_config
from .test_track_file import sample_track


@pytest.fixture
def hub():
    h = EveryBreathHub(config=base_config(), osc_port=8813)
    yield h
    for prefix in list(h.playing_tracks):
        h.stop_track(prefix)


@pytest.fixture
def track_path(tmp_path: Path) -> Path:
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    return p


def test_loading_registers_its_devices(hub, track_path):
    prefix = hub.load_track(track_path)
    time.sleep(0.4)
    uuids = {e.uuid for e in hub.registry.all_entries()}
    assert f"{prefix}:aaa" in uuids and f"{prefix}:bbb" in uuids


def test_devices_carry_their_recorded_names(hub, track_path):
    hub.load_track(track_path)
    time.sleep(0.4)
    names = {e.name for e in hub.registry.all_entries()}
    assert "Ana" in names and "Bo" in names


def test_devices_carry_their_recorded_colours(hub, track_path):
    hub.load_track(track_path)
    time.sleep(0.4)
    colors = {e.color for e in hub.registry.all_entries()}
    assert (220, 120, 90) in colors


def test_two_loads_of_one_track_do_not_collide(hub, track_path):
    a = hub.load_track(track_path)
    b = hub.load_track(track_path)
    assert a != b
    time.sleep(0.4)
    uuids = {e.uuid for e in hub.registry.all_entries()}
    assert {f"{a}:aaa", f"{b}:aaa"} <= uuids


def test_loading_does_not_change_detection_config(hub, track_path):
    """The Ableton rule: the clip does not reconfigure the instrument."""
    before = hub._config.detection
    hub.load_track(track_path)
    time.sleep(0.3)
    assert hub._config.detection == before


def test_playing_tracks_lists_what_is_loaded(hub, track_path):
    assert hub.playing_tracks == []
    prefix = hub.load_track(track_path)
    assert hub.playing_tracks == [prefix]
    hub.stop_track(prefix)
    assert hub.playing_tracks == []


def test_stopping_disconnects_its_devices(hub, track_path):
    prefix = hub.load_track(track_path)
    time.sleep(0.4)
    hub.stop_track(prefix)
    still_connected = {
        e.uuid for e in hub.registry.all_entries()
        if e.uuid.startswith(f"{prefix}:") and e.uuid in hub.registry.connected_uuids()
    }
    assert still_connected == set()


def test_stopping_an_unknown_prefix_is_safe(hub):
    hub.stop_track("pb99")


def test_a_malformed_track_is_refused_with_a_message(hub, tmp_path: Path):
    bad = tmp_path / "bad.breath.json"
    bad.write_text("{ not json")
    with pytest.raises(ValueError):
        hub.load_track(bad)
    assert hub.playing_tracks == []


def test_the_feed_stops_once_the_last_track_does(hub, track_path):
    prefix = hub.load_track(track_path)
    assert hub._feed is not None
    hub.stop_track(prefix)
    assert hub._feed is None, "drain thread outlived the last producer"
