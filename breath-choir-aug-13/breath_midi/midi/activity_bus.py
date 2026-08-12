from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

MidiActivityKind = Literal["note_on", "note_off", "control_change"]


@dataclass(frozen=True)
class MidiActivityEvent:
    kind: MidiActivityKind
    channel: int
    source_id: str
    mono_t: float
    note: int | None = None
    velocity: int | None = None
    control: int | None = None
    value: int | None = None


class MidiActivityBus:
    """Thread-safe buffer for outgoing MIDI. Publishers append from any thread;
    the UI thread calls drain() once per frame to process all pending events.
    Optional subscribe() callbacks are invoked from drain() (UI thread) per event.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf: list[MidiActivityEvent] = []
        self._subscribers: list[Callable[[MidiActivityEvent], None]] = []

    def subscribe(self, fn: Callable[[MidiActivityEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(fn)
                except ValueError:
                    pass

        return unsubscribe

    def publish(self, event: MidiActivityEvent) -> None:
        with self._lock:
            self._buf.append(event)

    def drain(self) -> list[MidiActivityEvent]:
        with self._lock:
            out = self._buf
            self._buf = []
            subs = tuple(self._subscribers)
        for e in out:
            for fn in subs:
                fn(e)
        return out
