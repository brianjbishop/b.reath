from __future__ import annotations

import colorsys
import threading
from dataclasses import dataclass, replace

GOLDEN_RATIO_CONJUGATE = 0.618033988749895

# F#maj7 note pairs (inhale, exhale) assigned to devices in order.
# When more devices connect than pairs exist, the sequence repeats one
# octave higher (octave_offset = 12 per full cycle).
_DEVICE_NOTE_PAIRS: list[tuple[int, int]] = [
    (54, 58),
    (61, 65),
    (73, 77),
    (85, 89),
    (97, 101),
    (109, 113),
]


def generate_device_color(index: int) -> tuple[int, int, int]:
    """
    Generate a visually distinct RGB color for a given device index.
    Uses the Golden Ratio Conjugate to spread hues evenly across
    the color wheel regardless of how many devices connect.
    Saturation and lightness are fixed to ensure colors are vivid
    and readable on a dark background.
    """
    hue = (index * GOLDEN_RATIO_CONJUGATE) % 1.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.75)
    return (int(r * 255), int(g * 255), int(b * 255))


@dataclass(frozen=True)
class DeviceEntry:
    uuid: str
    inhale_note: int
    exhale_note: int
    display_order: int
    color: tuple[int, int, int]
    name: str
    muted: bool = False
    soloed: bool = False
    cc_mode: bool = False
    cc_value: int = 127
    cons_n: int = 3
    cons_tolerance: float = 0.30


class DeviceRegistry:
    """
    Session-scoped registry mapping UUID → DeviceEntry.
    Persists across hub stop/start within the same session.
    Thread-safe for concurrent OSC thread reads/writes and UI thread reads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, DeviceEntry] = {}
        self._connected: set[str] = set()
        # Total devices ever seen this session — drives stable color/note assignment.
        # Never decremented so colors/notes are stable across disconnect/reconnect.
        self._next_index: int = 0

    def get_or_create(self, uuid: str) -> tuple[DeviceEntry, bool]:
        """Return (entry, is_new). If new, assigns notes/color from _next_index."""
        with self._lock:
            if uuid in self._entries:
                return self._entries[uuid], False
            idx = self._next_index
            self._next_index += 1
            pair_idx = idx % len(_DEVICE_NOTE_PAIRS)
            octave_offset = (idx // len(_DEVICE_NOTE_PAIRS)) * 12
            inhale_note = _DEVICE_NOTE_PAIRS[pair_idx][0] + octave_offset
            exhale_note = _DEVICE_NOTE_PAIRS[pair_idx][1] + octave_offset
            entry = DeviceEntry(
                uuid=uuid,
                inhale_note=inhale_note,
                exhale_note=exhale_note,
                display_order=idx,
                color=generate_device_color(idx),
                name=uuid[:15],
            )
            self._entries[uuid] = entry
            return entry, True

    def get(self, uuid: str) -> DeviceEntry | None:
        with self._lock:
            return self._entries.get(uuid)

    def all_entries(self) -> list[DeviceEntry]:
        """Return all entries sorted by display_order."""
        with self._lock:
            return sorted(self._entries.values(), key=lambda e: e.display_order)

    def connected_uuids(self) -> set[str]:
        with self._lock:
            return set(self._connected)

    def mark_connected(self, uuid: str) -> None:
        with self._lock:
            self._connected.add(uuid)

    def mark_disconnected(self, uuid: str) -> None:
        with self._lock:
            self._connected.discard(uuid)

    def mark_all_disconnected(self) -> None:
        with self._lock:
            self._connected.clear()

    def set_name(self, uuid: str, name: str) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], name=name)

    def set_inhale_note(self, uuid: str, note: int) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], inhale_note=note)

    def set_exhale_note(self, uuid: str, note: int) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], exhale_note=note)

    def set_color(self, uuid: str, color: tuple[int, int, int]) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], color=color)

    def set_muted(self, uuid: str, muted: bool) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], muted=muted)

    def set_cc_mode(self, uuid: str, cc_mode: bool) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], cc_mode=cc_mode)

    def set_cc_value(self, uuid: str, cc_value: int) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], cc_value=cc_value)

    def set_cons_n(self, uuid: str, n: int) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], cons_n=n)

    def set_cons_tolerance(self, uuid: str, tol: float) -> None:
        with self._lock:
            if uuid in self._entries:
                self._entries[uuid] = replace(self._entries[uuid], cons_tolerance=tol)

    def set_soloed(self, uuid: str, soloed: bool) -> None:
        """Solo this device and un-solo all others, or clear solo if soloed=False."""
        with self._lock:
            for uid in self._entries:
                new_soloed = (uid == uuid) if soloed else False
                self._entries[uid] = replace(self._entries[uid], soloed=new_soloed)

    def is_any_soloed(self) -> bool:
        with self._lock:
            return any(e.soloed for e in self._entries.values())

    def swap_order(self, uuid_a: str, uuid_b: str) -> None:
        with self._lock:
            if uuid_a in self._entries and uuid_b in self._entries:
                a = self._entries[uuid_a]
                b = self._entries[uuid_b]
                self._entries[uuid_a] = replace(a, display_order=b.display_order)
                self._entries[uuid_b] = replace(b, display_order=a.display_order)
