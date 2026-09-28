"""
Replay a track as extra performers in the choir.

Playback is additive rather than a mode.  Recorded performers register as
ordinary devices and mix with live phones, so they pick up colours, note
assignment, mute and solo for free.  Nothing downstream can tell a recording
from a phone.

When a track ends its devices simply stop sending, and the hub's timeout sweep
drops them and releases their held notes — see EveryBreathHub._sweep_timeouts.
That sweep lives in the hub precisely because this module bypasses the OSC
source, where the timeout used to live: for a while it did not apply here at
all, so finished tracks stayed on screen holding keys down.

Emitted uuids carry a per-load prefix.  A recording stores the uuid of the phone
it was captured from, so without one, replaying a track while that same phone is
in the room would interleave two people's breath into a single detector.  The
prefix also means loading one track twice gives two independent performers,
which is how you thicken a small group.

Tracks do not loop.  A track that ends lets its devices time out, which is the
honest thing for a performer who has stopped breathing into the piece.
"""

from __future__ import annotations

import threading
import time

from breath_midi.feed import SampleFeed
from breath_midi.tracks.file import Track
from breath_midi.types import BreathSample


class TrackPlaybackSource:
    def __init__(self, track: Track, feed: SampleFeed, prefix: str) -> None:
        self._track = track
        self._feed = feed
        self._prefix = prefix
        self._thread: threading.Thread | None = None
        self._running = False
        self._finished = False

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def track(self) -> Track:
        return self._track

    def uuid_for(self, index: int) -> str:
        return f"{self._prefix}:{self._track.devices[index].uuid}"

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._finished = False
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"playback-{self._prefix}"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.5)

    def _run(self) -> None:
        # Announce every device up front rather than on its first sample, so the
        # panel fills at once instead of performers appearing one at a time as
        # each happens to take its first breath.
        for i in range(len(self._track.devices)):
            self._feed.submit_new_device(self.uuid_for(i))

        t0 = time.monotonic()
        for t, index, amp in self._track.samples:
            if not self._running:
                return
            # Sleep against elapsed time rather than accumulating per-sample
            # deltas, so scheduling jitter cannot make the track drift slower
            # than it was recorded.
            wait = t - (time.monotonic() - t0)
            if wait > 0:
                time.sleep(wait)
            if not self._running:
                return
            self._feed.submit_sample(
                BreathSample(
                    t=time.monotonic(),
                    amp=float(amp),
                    source_id=self.uuid_for(index),
                )
            )
        self._finished = True
