from __future__ import annotations

import socket
import struct
import threading
import time
from collections.abc import Callable

from breath_midi.types import BreathSample

SampleCb = Callable[[BreathSample], None]
DeviceCb = Callable[[str], None]

_TIMEOUT_CHECK_INTERVAL = 2.0  # seconds between timeout sweeps


def _parse_osc_message(data: bytes) -> tuple[str, list[object]] | None:
    """
    Minimal OSC message parser (address + typed arguments).
    Copied inline from osc_source.py to keep this module self-contained
    and avoid importing a private function.
    """
    if not data or data[0:1] != b"/":
        return None
    try:
        end = data.index(0)
    except ValueError:
        return None
    address = data[:end].decode("ascii", errors="ignore")
    offset = end + 1
    while offset % 4 != 0 and offset < len(data):
        offset += 1
    if offset >= len(data) or data[offset : offset + 1] != b",":
        return address, []
    try:
        tag_end = data.index(0, offset)
    except ValueError:
        return address, []
    tags = data[offset + 1 : tag_end].decode("ascii", errors="ignore")
    offset = tag_end + 1
    while offset % 4 != 0 and offset < len(data):
        offset += 1

    args: list[object] = []
    for tag in tags:
        if tag == "f" and offset + 4 <= len(data):
            args.append(struct.unpack(">f", data[offset : offset + 4])[0])
            offset += 4
        elif tag == "d" and offset + 8 <= len(data):
            args.append(struct.unpack(">d", data[offset : offset + 8])[0])
            offset += 8
        elif tag == "i" and offset + 4 <= len(data):
            args.append(struct.unpack(">i", data[offset : offset + 4])[0])
            offset += 4
    return address, args


class MultiDeviceOscSource:
    """
    Single UDP socket listener that tracks all unique source_ids simultaneously.

    on_new_device_cb(uuid)  — called once when a uuid is seen for the first time
    on_sample_cb(sample)    — called for every valid breath packet
    on_timeout_cb(uuid)     — called when no packet arrives from uuid for timeout_s
    """

    def __init__(
        self,
        port: int,
        on_sample_cb: SampleCb,
        on_new_device_cb: DeviceCb,
        on_timeout_cb: DeviceCb,
        timeout_s: float = 5.0,
    ) -> None:
        self._port = int(port)
        self._on_sample = on_sample_cb
        self._on_new_device = on_new_device_cb
        self._on_timeout = on_timeout_cb
        self._timeout_s = timeout_s

        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

        self._last_seen: dict[str, float] = {}  # uuid → monotonic time
        self._t0: float | None = None
        self._last_timeout_check = 0.0

    def start(self) -> None:
        if self._running:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Deliberately NOT setting SO_REUSEADDR.  On macOS it lets a second
        # process bind the same UDP port successfully, after which the kernel
        # hands each datagram to only one of the two sockets — so a port clash
        # showed up as phones randomly failing to appear rather than as an
        # error.  Without it, bind() raises and the caller reports it.
        self._sock.bind(("0.0.0.0", self._port))
        self._sock.settimeout(0.5)
        self._running = True
        self._t0 = None
        self._last_seen = {}
        self._last_timeout_check = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._last_seen = {}
        self._t0 = None

    def _loop(self) -> None:
        assert self._sock is not None
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(4096)
            except socket.timeout:
                self._check_timeouts()
                continue
            except OSError:
                break

            parsed = _parse_osc_message(data)
            if parsed is None:
                continue
            address, args = parsed
            if not address.startswith("/breath_value/") or not args:
                continue

            uuid = address.split("/")[-1]
            if not uuid:
                continue

            try:
                amp = float(args[0])
            except Exception:
                continue

            now = time.monotonic()
            if self._t0 is None:
                self._t0 = now
            t_rel = now - self._t0

            is_new = uuid not in self._last_seen
            self._last_seen[uuid] = now

            if is_new:
                try:
                    self._on_new_device(uuid)
                except Exception:
                    pass

            try:
                self._on_sample(BreathSample(t=t_rel, amp=amp, source_id=uuid))
            except Exception:
                pass

            # Check timeouts every _TIMEOUT_CHECK_INTERVAL seconds
            if now - self._last_timeout_check >= _TIMEOUT_CHECK_INTERVAL:
                self._check_timeouts()

    def _check_timeouts(self) -> None:
        now = time.monotonic()
        self._last_timeout_check = now
        timed_out = [
            uuid
            for uuid, last in list(self._last_seen.items())
            if (now - last) >= self._timeout_s
        ]
        for uuid in timed_out:
            del self._last_seen[uuid]
            try:
                self._on_timeout(uuid)
            except Exception:
                pass
