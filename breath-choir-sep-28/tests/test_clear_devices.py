"""
Clearing the device list.

Devices are kept after they disconnect on purpose: a performer whose phone
drops should come back to their own name, notes and channel rather than as a
stranger. That is right for a phone and wrong for the leftovers of a track that
finished, which is why this exists rather than the list clearing itself.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.tracks.file import write_track
from breath_midi.types import BreathSample

from .test_hold_triggers import base_config
from .test_track_file import sample_track


@pytest.fixture
def hub():
    h = EveryBreathHub(config=base_config(), osc_port=8817)
    h.set_device_timeout(0.6)
    yield h
    h.stop_all_tracks()


@pytest.fixture
def track_path(tmp_path: Path) -> Path:
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    return p


def test_clears_devices_from_a_finished_track(hub, track_path):
    hub.load_track(track_path)
    time.sleep(1.6)                       # play out, then time out
    assert hub.registry.all_entries(), "nothing to clear"
    gone = hub.clear_devices()
    assert gone == 2
    assert hub.registry.all_entries() == []


def test_clearing_stops_whatever_is_playing(hub, track_path):
    hub.load_track(track_path)
    hub.clear_devices()
    assert hub.playing_tracks == []


def test_a_live_phone_is_left_alone(hub):
    """Clearing a device that is still sending would only rename it a moment later."""
    hub._ensure_midi_sink()
    hub._ensure_feed()
    hub._on_new_device("phone-a")
    hub.registry.set_name("phone-a", "Ana")
    hub.set_midi_channel("phone-a", 7)
    hub._on_sample(BreathSample(t=0, amp=0.5, source_id="phone-a"))

    assert hub.clear_devices() == 0
    entry = hub.registry.get("phone-a")
    assert entry is not None and entry.name == "Ana" and entry.midi_channel == 7


def test_clears_a_phone_that_has_gone(hub):
    hub._ensure_midi_sink()
    hub._ensure_feed()
    hub._on_new_device("phone-a")
    hub._on_sample(BreathSample(t=0, amp=0.5, source_id="phone-a"))
    time.sleep(1.4)                       # let it time out
    assert hub.clear_devices() == 1
    assert hub.registry.get("phone-a") is None


def test_clearing_releases_held_notes(hub, track_path):
    hub.load_track(track_path)
    time.sleep(0.4)
    uuids = list(hub._runtimes)
    voices = [hub._runtimes[u]._voice for u in uuids]
    hub.clear_devices()
    assert all(v.sounding_note is None for v in voices), "a note survived the clear"


def test_clearing_twice_is_safe(hub, track_path):
    hub.load_track(track_path)
    time.sleep(1.6)
    hub.clear_devices()
    assert hub.clear_devices() == 0


def test_clearing_an_empty_list_is_safe(hub):
    assert hub.clear_devices() == 0


def test_a_cleared_device_can_come_back_fresh(hub):
    hub._ensure_midi_sink()
    hub._ensure_feed()
    hub._on_new_device("phone-a")
    hub.registry.set_name("phone-a", "Ana")
    hub._on_sample(BreathSample(t=0, amp=0.5, source_id="phone-a"))
    time.sleep(1.4)
    hub.clear_devices()

    hub._on_new_device("phone-a")
    entry = hub.registry.get("phone-a")
    assert entry is not None, "device did not come back"
    assert entry.name != "Ana", "cleared device kept its old name"
