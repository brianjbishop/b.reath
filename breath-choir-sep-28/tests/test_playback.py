"""
Track playback.

Playback is additive, not a mode: recorded performers register as ordinary
devices and mix with live phones. Emitted uuids are namespaced so a recording
can never collide with the phone it was captured from, and loading one track
twice gives two independent performers rather than one fighting itself.
"""

from __future__ import annotations

import time

from breath_midi.feed import SampleFeed
from breath_midi.tracks.playback import TrackPlaybackSource

from .test_track_file import sample_track


def collect(track=None, prefix="pb1", settle=0.5):
    """Run a track to completion, returning what reached the hub callbacks."""
    samples, new, timeouts = [], [], []
    feed = SampleFeed(samples.append, new.append, timeouts.append)
    feed.start()
    src = TrackPlaybackSource(track or sample_track(), feed, prefix=prefix)
    src.start()
    time.sleep(settle)
    src.stop()
    feed.stop()
    return samples, new, timeouts


def test_announces_each_device_before_any_sample():
    samples, new, _ = collect()
    assert new == ["pb1:aaa", "pb1:bbb"]


def test_uuids_are_namespaced_so_a_live_phone_cannot_collide():
    samples, _, _ = collect()
    assert {s.source_id for s in samples} == {"pb1:aaa", "pb1:bbb"}


def test_same_track_twice_gives_independent_performers():
    quiet = SampleFeed(lambda s: None, lambda u: None, lambda u: None)
    a = TrackPlaybackSource(sample_track(), quiet, prefix="pb1")
    b = TrackPlaybackSource(sample_track(), quiet, prefix="pb2")
    assert a.uuid_for(0) != b.uuid_for(0)
    assert a.uuid_for(0) == "pb1:aaa" and b.uuid_for(0) == "pb2:aaa"


def test_replays_every_sample_with_its_amplitude():
    samples, _, _ = collect()
    assert [round(s.amp, 2) for s in samples] == [0.41, 0.23, 0.44]


def test_samples_are_attributed_to_the_right_device():
    samples, _, _ = collect()
    assert [s.source_id for s in samples] == ["pb1:aaa", "pb1:bbb", "pb1:aaa"]


def test_marks_itself_finished_at_the_end():
    quiet = SampleFeed(lambda s: None, lambda u: None, lambda u: None)
    src = TrackPlaybackSource(sample_track(), quiet, prefix="pb1")
    assert not src.is_finished
    src.start()
    time.sleep(0.5)
    assert src.is_finished
    src.stop()


def test_stop_before_the_end_stops_emitting():
    slow = sample_track()
    slow = type(slow)(**{**slow.__dict__,
                         "samples": [(i * 0.2, 0, 0.5) for i in range(20)],
                         "duration_s": 4.0})
    samples = []
    feed = SampleFeed(samples.append, lambda u: None, lambda u: None)
    feed.start()
    src = TrackPlaybackSource(slow, feed, prefix="pb1")
    src.start()
    time.sleep(0.3)
    src.stop()
    count_at_stop = len(samples)
    time.sleep(0.5)
    feed.stop()
    assert len(samples) == count_at_stop, "kept emitting after stop"
    assert count_at_stop < 20


def test_honours_the_recorded_timing():
    """A 0.6s track must take about 0.6s, not run flat out."""
    spaced = sample_track()
    spaced = type(spaced)(**{**spaced.__dict__,
                             "samples": [(0.0, 0, 0.5), (0.6, 0, 0.5)],
                             "duration_s": 0.6})
    quiet = SampleFeed(lambda s: None, lambda u: None, lambda u: None)
    quiet.start()
    src = TrackPlaybackSource(spaced, quiet, prefix="pb1")
    start = time.monotonic()
    src.start()
    while not src.is_finished and time.monotonic() - start < 3.0:
        time.sleep(0.02)
    elapsed = time.monotonic() - start
    src.stop()
    quiet.stop()
    assert 0.5 < elapsed < 1.2, f"took {elapsed:.2f}s for a 0.6s track"


def test_stop_without_start_is_safe():
    quiet = SampleFeed(lambda s: None, lambda u: None, lambda u: None)
    TrackPlaybackSource(sample_track(), quiet, prefix="pb1").stop()
