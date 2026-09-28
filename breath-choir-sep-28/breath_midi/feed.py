"""
The hub's single calling thread.

EveryBreathHub._on_sample sets the MIDI activity source and drives per-device
runtimes without taking a lock, and documents why: it is always called from the
single OSC receive thread, so the calls are naturally sequential.  The comment
there ends by saying that if the threading model ever changes, the assumption
MUST be revisited.

Playing a track alongside live phones changes it — playback is a second
producer.  The options were to lock the real-time MIDI path, which costs time on
exactly the path that must not stall, or to keep one caller.  This keeps one
caller: every source posts events here, and a single drain thread makes the
calls in order.  The hub's assumption stays literally true.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from breath_midi.types import BreathSample

_NEW, _SAMPLE, _TIMEOUT, _STOP = 0, 1, 2, 3

# ~160s of one device at 50Hz.  Large enough that it is never reached in
# practice, bounded so a stalled consumer cannot exhaust memory.
_MAXSIZE = 8192


class SampleFeed:
    """
    Serialises every source onto one thread.

    submit_* are safe to call from any thread and never block.  The callbacks
    are only ever invoked from the drain thread.
    """

    def __init__(
        self,
        on_sample: Callable[[BreathSample], None],
        on_new_device: Callable[[str], None],
        on_timeout: Callable[[str], None],
        on_idle: Callable[[], None] | None = None,
        idle_interval_s: float = 0.25,
    ) -> None:
        self._on_sample = on_sample
        self._on_new_device = on_new_device
        self._on_timeout = on_timeout
        # Called from the drain thread on a timer, busy or not.  The device
        # timeout sweep rides on this: it has to run when nothing is arriving,
        # which is precisely when a device has gone quiet.
        self._on_idle = on_idle
        self._idle_interval_s = float(idle_interval_s)
        self._q: queue.Queue = queue.Queue(maxsize=_MAXSIZE)
        self._thread: threading.Thread | None = None
        self._running = False

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._drain, daemon=True, name="sample-feed"
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        # Wake the blocking get() so the thread can notice and exit.
        try:
            self._q.put_nowait((_STOP, None))
        except queue.Full:
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)

    # ── producers: any thread, never blocking ────────────────────────────────

    def _put(self, kind: int, payload) -> None:
        try:
            self._q.put_nowait((kind, payload))
        except queue.Full:
            # Dropping the newest sample beats stalling a producer that is
            # reading a UDP socket — a blocked reader loses live packets, which
            # matters more than a replayed one.
            pass

    def submit_sample(self, sample: BreathSample) -> None:
        self._put(_SAMPLE, sample)

    def submit_new_device(self, uuid: str) -> None:
        self._put(_NEW, uuid)

    def submit_timeout(self, uuid: str) -> None:
        self._put(_TIMEOUT, uuid)

    # ── the one consumer ─────────────────────────────────────────────────────

    def _drain(self) -> None:
        next_idle = time.monotonic() + self._idle_interval_s
        while True:
            try:
                kind, payload = self._q.get(timeout=self._idle_interval_s)
            except queue.Empty:
                kind, payload = None, None
            else:
                if kind == _STOP or not self._running:
                    return

            now = time.monotonic()
            if self._on_idle is not None and now >= next_idle:
                next_idle = now + self._idle_interval_s
                try:
                    self._on_idle()
                except Exception as exc:
                    print(f"[SampleFeed] idle callback raised: {exc!r}")

            if kind is None:
                if not self._running:
                    return
                continue
            try:
                if kind == _SAMPLE:
                    self._on_sample(payload)
                elif kind == _NEW:
                    self._on_new_device(payload)
                elif kind == _TIMEOUT:
                    self._on_timeout(payload)
            except Exception as exc:
                # One misbehaving device must not silence every other performer.
                print(f"[SampleFeed] callback raised: {exc!r}")
