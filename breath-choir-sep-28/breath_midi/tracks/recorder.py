"""
Capture live breath into a track.

A tap, not a source: the recorder sits beside the hub's sample path and copies
what goes past.  It stores the raw amplitude the phone sent and never anything
the detector made of it, so a recording can be replayed against different dials
later — which is the whole reason to keep one.

Timestamps are taken when the sample arrives and are relative to the first one,
so a take starts at zero however long the app has been running.  They are never
regularised onto a fixed grid: the hold detector measures stillness in time, and
a tidied-up recording would misreport which holds a dial setting finds.
"""

from __future__ import annotations

import time
from datetime import datetime

from breath_midi.config.model import DetectionConfig
from breath_midi.tracks.file import Track, TrackDevice

# What a device is called if the take ends before its metadata is collected.
_FALLBACK_COLOR = (170, 170, 170)


class TrackRecorder:
    def __init__(self, detection: DetectionConfig, name: str) -> None:
        self._detection = detection
        self._name = name
        self._t0: float | None = None
        self._order: list[str] = []
        self._index: dict[str, int] = {}
        self._meta: dict[str, TrackDevice] = {}
        self._samples: list[tuple[float, int, float]] = []

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def name(self) -> str:
        return self._name

    def note(self, uuid: str, amp: float) -> None:
        """Called from the hub's sample path.  Must stay cheap."""
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now
        index = self._index.get(uuid)
        if index is None:
            index = len(self._order)
            self._index[uuid] = index
            self._order.append(uuid)
        self._samples.append((now - self._t0, index, float(amp)))

    def set_device_meta(
        self,
        uuid: str,
        name: str,
        color,
        inhale_note: int,
        exhale_note: int,
        midi_channel: int = 1,
        hold_note: int = 0,
        cons_n: int = 0,
        cons_tolerance: float = 0.30,
        cc_mode: bool = False,
        breath_cc: int = 74,
    ) -> None:
        """
        Attach names, colours and notes, normally once at stop.

        Metadata for a device that never sent anything is kept but unused — the
        device list is built from what actually breathed.
        """
        self._meta[uuid] = TrackDevice(
            uuid=uuid,
            name=str(name),
            color=tuple(int(c) for c in color),
            inhale_note=int(inhale_note),
            exhale_note=int(exhale_note),
            midi_channel=int(midi_channel),
            hold_note=int(hold_note),
            cons_n=int(cons_n),
            cons_tolerance=float(cons_tolerance),
            cc_mode=bool(cc_mode),
            breath_cc=max(0, min(127, int(breath_cc))),
        )

    def to_track(self) -> Track:
        devices = [
            self._meta.get(
                uuid, TrackDevice(uuid, uuid, _FALLBACK_COLOR, 54, 55, 1)
            )
            for uuid in self._order
        ]
        duration = max((t for t, _, _ in self._samples), default=0.0)
        return Track(
            name=self._name,
            created=datetime.now().isoformat(timespec="seconds"),
            duration_s=duration,
            source="recorded",
            detection=self._detection,
            devices=devices,
            samples=self._samples,
        )
