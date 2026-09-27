"""
Capturing live breath into a track.

The recorder is a tap, not a source: it copies what goes past the hub's sample
path. It stores the raw amplitude the phone sent and nothing the detector made
of it, so a recording can be replayed later against different dials.
"""

from __future__ import annotations

import time

from breath_midi.tracks.recorder import TrackRecorder

from .test_presets import make_det


def test_records_samples_in_order():
    r = TrackRecorder(make_det(), name="take 1")
    for i in range(5):
        r.note("phone-a", i / 10)
        time.sleep(0.005)
    assert r.sample_count == 5
    track = r.to_track()
    assert [round(a, 2) for _, _, a in track.samples] == [0.0, 0.1, 0.2, 0.3, 0.4]
    times = [t for t, _, _ in track.samples]
    assert times == sorted(times)


def test_first_sample_is_at_time_zero():
    """Timestamps are relative to the first sample, not to process start."""
    r = TrackRecorder(make_det(), name="take 1")
    time.sleep(0.05)
    r.note("phone-a", 0.5)
    assert r.to_track().samples[0][0] == 0.0


def test_devices_are_indexed_in_first_seen_order():
    r = TrackRecorder(make_det(), name="take 1")
    r.note("b", 0.1)
    r.note("a", 0.2)
    r.note("b", 0.3)
    track = r.to_track()
    assert [d.uuid for d in track.devices] == ["b", "a"]
    assert [i for _, i, _ in track.samples] == [0, 1, 0]


def test_device_metadata_is_carried_through():
    r = TrackRecorder(make_det(), name="take 1")
    r.note("a", 0.1)
    r.set_device_meta("a", "Ana", (10, 20, 30), 54, 55)
    d = r.to_track().devices[0]
    assert (d.name, d.color, d.inhale_note, d.exhale_note) == ("Ana", (10, 20, 30), 54, 55)


def test_a_device_with_no_metadata_still_records():
    """Metadata arrives at stop; a device must not be lost for lacking it."""
    r = TrackRecorder(make_det(), name="take 1")
    r.note("unknown-phone", 0.4)
    d = r.to_track().devices[0]
    assert d.uuid == "unknown-phone"
    assert d.name


def test_metadata_for_a_device_that_never_sent_is_ignored():
    r = TrackRecorder(make_det(), name="take 1")
    r.note("a", 0.1)
    r.set_device_meta("ghost", "Ghost", (1, 2, 3), 60, 61)
    assert [d.uuid for d in r.to_track().devices] == ["a"]


def test_records_the_dials_it_was_given():
    det = make_det(inhale_exit_delta=0.09, min_hold_ms=900)
    r = TrackRecorder(det, name="take 1")
    r.note("a", 0.1)
    assert r.to_track().detection == det


def test_source_is_recorded():
    r = TrackRecorder(make_det(), name="take 1")
    r.note("a", 0.1)
    assert r.to_track().source == "recorded"


def test_duration_reflects_the_last_sample():
    r = TrackRecorder(make_det(), name="take 1")
    r.note("a", 0.1)
    time.sleep(0.15)
    r.note("a", 0.2)
    assert r.to_track().duration_s > 0.1


def test_an_empty_recording_produces_an_empty_track():
    r = TrackRecorder(make_det(), name="take 1")
    track = r.to_track()
    assert track.samples == [] and track.devices == []
    assert track.duration_s == 0.0
