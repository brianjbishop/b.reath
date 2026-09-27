"""
The hub's single calling thread.

hub._on_sample routes MIDI activity and drives per-device runtimes without a
lock, and says so in a comment: it assumes exactly one caller. Playback adds a
second producer alongside the OSC thread. Rather than put a lock on the
real-time MIDI path, every source posts here and one drain thread makes the
calls.

The load-bearing test is test_all_callbacks_run_on_one_thread. If that ever
fails, the hub's lock-free assumption is broken and MIDI routing can misattribute
notes under load.
"""

from __future__ import annotations

import threading
import time

from breath_midi.feed import SampleFeed
from breath_midi.types import BreathSample


def drain(timeout_s: float = 1.0):
    """Give the drain thread a moment; far shorter than the timeout in practice."""
    time.sleep(0.25)


def test_delivers_samples_in_order():
    got: list[BreathSample] = []
    feed = SampleFeed(got.append, lambda u: None, lambda u: None)
    feed.start()
    for i in range(50):
        feed.submit_sample(BreathSample(t=i * 0.02, amp=i / 50, source_id="a"))
    drain()
    feed.stop()
    assert [round(s.t, 3) for s in got] == [round(i * 0.02, 3) for i in range(50)]


def test_all_callbacks_run_on_one_thread():
    """The reason this module exists."""
    threads: set[int] = set()
    note = lambda *_: threads.add(threading.get_ident())
    feed = SampleFeed(note, note, note)
    feed.start()

    def produce(tag: str) -> None:
        for i in range(30):
            feed.submit_new_device(tag)
            feed.submit_sample(BreathSample(t=i * 0.01, amp=0.5, source_id=tag))
            feed.submit_timeout(tag)

    workers = [threading.Thread(target=produce, args=(f"dev{n}",)) for n in range(4)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    drain()
    feed.stop()
    assert len(threads) == 1, f"hub was called from {len(threads)} threads"


def test_ordering_is_preserved_across_event_kinds():
    """A device must be announced before its samples arrive, not after."""
    events: list[str] = []
    feed = SampleFeed(
        lambda s: events.append("sample"),
        lambda u: events.append("new"),
        lambda u: events.append("timeout"),
    )
    feed.start()
    feed.submit_new_device("a")
    feed.submit_sample(BreathSample(t=0.0, amp=0.5, source_id="a"))
    feed.submit_timeout("a")
    drain()
    feed.stop()
    assert events == ["new", "sample", "timeout"]


def test_stop_is_idempotent():
    feed = SampleFeed(lambda s: None, lambda u: None, lambda u: None)
    feed.start()
    feed.stop()
    feed.stop()


def test_start_is_idempotent():
    got: list[BreathSample] = []
    feed = SampleFeed(got.append, lambda u: None, lambda u: None)
    feed.start()
    feed.start()
    feed.submit_sample(BreathSample(t=0.0, amp=0.5, source_id="a"))
    drain()
    feed.stop()
    assert len(got) == 1, "a second start duplicated delivery"


def test_a_raising_callback_does_not_kill_the_drain():
    """One bad device must not silence every other performer."""
    seen: list[BreathSample] = []

    def boom(s: BreathSample) -> None:
        seen.append(s)
        raise RuntimeError("callback blew up")

    feed = SampleFeed(boom, lambda u: None, lambda u: None)
    feed.start()
    for i in range(3):
        feed.submit_sample(BreathSample(t=i, amp=0.5, source_id="a"))
    drain()
    feed.stop()
    assert len(seen) == 3, "drain thread died on the first exception"


def test_submitting_before_start_does_not_raise():
    feed = SampleFeed(lambda s: None, lambda u: None, lambda u: None)
    feed.submit_sample(BreathSample(t=0.0, amp=0.5, source_id="a"))
    feed.stop()


def test_submit_never_blocks_when_the_queue_is_full():
    """
    A full queue must not stall the producer — it is reading a UDP socket, and
    a stalled reader drops real packets rather than replayed ones.
    """
    feed = SampleFeed(lambda s: None, lambda u: None, lambda u: None)  # not started
    start = time.monotonic()
    for i in range(20_000):
        feed.submit_sample(BreathSample(t=i, amp=0.5, source_id="a"))
    assert time.monotonic() - start < 5.0, "submit blocked on a full queue"
