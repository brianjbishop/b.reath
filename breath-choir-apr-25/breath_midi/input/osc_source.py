from __future__ import annotations

import socket
import struct
import threading
import time

from breath_midi.input.base import BreathInputSource, SampleCallback
from breath_midi.types import BreathSample


def _parse_osc_message(data: bytes) -> tuple[str, list[object]] | None:
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
        else:
            # ignore unsupported tags
            pass
    return address, args


class OscBreathInput(BreathInputSource):
    def __init__(self, port: int, source_filter: str = "all"):
        self.port = int(port)
        self.source_filter = source_filter
        self._cb: SampleCallback | None = None

        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._t0: float | None = None

    def start(self, callback: SampleCallback) -> None:
        if self._running:
            return
        self._cb = callback
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.settimeout(0.5)

        self._running = True
        self._t0 = None
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
        self._t0 = None

    def _loop(self) -> None:
        assert self._cb is not None
        assert self._sock is not None
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            parsed = _parse_osc_message(data)
            if parsed is None:
                continue
            address, args = parsed
            if not address.startswith("/breath_value/") or not args:
                continue

            source_id = address.split("/")[-1]
            if self.source_filter != "all" and source_id != self.source_filter:
                continue

            try:
                amp = float(args[0])
            except Exception:
                continue

            now = time.monotonic()
            if self._t0 is None:
                self._t0 = now
            t_rel = now - self._t0
            self._cb(BreathSample(t=t_rel, amp=amp, source_id=source_id))

