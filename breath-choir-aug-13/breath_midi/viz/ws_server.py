"""
WebSocket broadcaster for the rose_breath browser visualization.

This is the former standalone osc_ws_bridge.py, absorbed into the app.  The
bridge used to sit in front as a man-in-the-middle — phones to 8001, forward to
8002, browser on 8765 — which meant two processes wanting UDP 8001.  Because
multi_osc.py set SO_REUSEADDR, the second bind *succeeded* on macOS and the
kernel split datagrams between them, so it presented as flaky phones rather than
an error.  Now the app is the only listener and simply fans out what it already
receives.

    phones ──8001──►  app  ──┬── MidiRouter ──► DAW
                             └── this ──ws:8765──► browser

Threading
---------
The app has three threads that matter here: DPG owns the main thread, the OSC
receive loop owns another, and this server runs an asyncio loop on a third.

publish_sample() and publish_disconnect() are called from the OSC thread — the
same thread that drives signal processing and MIDI. They must never block, or a
slow or wedged WebSocket client would stall MIDI output mid-performance. So they
do no I/O, take no async locks, and never touch the event loop: they only mutate
a plain dict and deque, which is safe under the GIL and cannot wait.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque

_BROADCAST_HZ = 60.0
# Disconnect events are rare and must not be lost to a flood of samples, so they
# get their own buffer rather than sharing the sample path.
_EVENT_MAXLEN = 256


class BreathWebSocketServer:
    """
    Broadcasts breath values to any connected browser.

    Samples are *coalesced* rather than queued: only the newest value per device
    survives to the next broadcast tick.  This is what "drop under pressure"
    means here, and it is not a compromise — index.html assigns each sample to
    `targetValue` and lerps its rendered value toward it every frame, so an
    intermediate sample that is superseded within 16ms has no visible effect.
    The upshot is a handoff bounded by device count instead of packet rate: a
    phone flood, a stalled browser, or a paused laptop cannot grow it.
    """

    def __init__(self, port: int, host: str = "localhost") -> None:
        self._port = int(port)
        self._host = host

        # Written from the OSC thread, drained by the asyncio thread.
        self._pending: dict[str, float] = {}
        self._events: deque[dict[str, object]] = deque(maxlen=_EVENT_MAXLEN)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._clients: set = set()
        self._running = False
        self._started = threading.Event()
        self._start_error: BaseException | None = None
        self._dropped_events = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self, timeout_s: float = 5.0) -> None:
        """
        Start the server thread and block until the port is bound.

        Raises whatever the bind raised — an already-used 8765 must fail loudly
        here rather than leaving a half-running server behind.
        """
        if self._running:
            return
        self._start_error = None
        self._started.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name="breath-ws", daemon=True
        )
        self._thread.start()

        if not self._started.wait(timeout_s):
            self._running = False
            raise TimeoutError(f"WebSocket server did not start within {timeout_s}s")
        if self._start_error is not None:
            self._running = False
            err = self._start_error
            self._start_error = None
            raise err

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        loop = self._loop
        if loop is not None:
            # The loop lives on another thread; this is the only safe way to
            # reach into it, and it is called once per stop rather than per packet.
            loop.call_soon_threadsafe(loop.stop)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._loop = None
        self._clients = set()
        self._pending.clear()
        self._events.clear()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def dropped_events(self) -> int:
        """Disconnect notices lost to a full buffer.  Should stay at zero."""
        return self._dropped_events

    # ── called from the OSC thread — must never block ─────────────────────────

    def publish_sample(self, uuid: str, value: float) -> None:
        # Single dict assignment: atomic under the GIL, no lock, cannot wait.
        # A superseded value is simply overwritten before it is ever sent.
        self._pending[uuid] = value

    def publish_disconnect(self, uuid: str) -> None:
        if len(self._events) == _EVENT_MAXLEN:
            self._dropped_events += 1
        self._events.append({"uuid": uuid, "value": None, "disconnected": True})

    # ── asyncio side ──────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as exc:  # pragma: no cover — surfaced via _start_error
            self._start_error = exc
            self._started.set()

    async def _serve(self) -> None:
        import websockets

        self._loop = asyncio.get_running_loop()
        try:
            server = await websockets.serve(self._handler, self._host, self._port)
        except Exception as exc:
            self._start_error = exc
            self._started.set()
            return

        self._started.set()
        print(f"[viz] WebSocket serving on ws://{self._host}:{self._port}")
        try:
            await self._broadcast_loop()
        finally:
            server.close()

    async def _handler(self, websocket) -> None:
        self._clients.add(websocket)
        print(f"[viz] Browser connected ({len(self._clients)} client(s))")
        try:
            await websocket.wait_closed()
        finally:
            self._clients.discard(websocket)
            print(f"[viz] Browser disconnected ({len(self._clients)} client(s))")

    async def _broadcast_loop(self) -> None:
        interval = 1.0 / _BROADCAST_HZ
        while self._running:
            await asyncio.sleep(interval)
            for payload in self._drain():
                await self._send(payload)

    def _drain(self) -> list[str]:
        """
        Take everything buffered since the last tick, as JSON strings.

        Disconnects go out before samples so a device that dropped out cannot be
        resurrected by a stale sample buffered in the same tick.
        """
        out: list[str] = []
        while self._events:
            out.append(json.dumps(self._events.popleft()))
        if self._pending:
            # Swap rather than iterate-and-clear: the OSC thread may be writing
            # concurrently, and rebinding is atomic so no sample is half-read.
            batch, self._pending = self._pending, {}
            for uuid, value in batch.items():
                out.append(json.dumps({"uuid": uuid, "value": round(value, 4)}))
        return out

    async def _send(self, payload: str) -> None:
        if not self._clients:
            return
        results = await asyncio.gather(
            *(client.send(payload) for client in list(self._clients)),
            return_exceptions=True,
        )
        # A client that errored is already closing; _handler removes it. Swallow
        # here so one bad browser cannot stop the broadcast for the others.
        for result in results:
            if isinstance(result, BaseException):
                continue
