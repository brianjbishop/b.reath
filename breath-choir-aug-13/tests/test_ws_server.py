"""
WebSocket fan-out tests.

The properties that matter are about the handoff between threads, not about
websockets itself: publish must never block the OSC/MIDI thread, the buffer must
stay bounded under a flood, disconnects must survive that flood, and the JSON
must be exactly what rose_breath/index.html parses.

_drain() is the seam.  It is what the asyncio side calls each tick, so driving it
directly tests the real handoff without needing a browser or an event loop.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from breath_midi.viz.ws_server import BreathWebSocketServer


@pytest.fixture
def server() -> BreathWebSocketServer:
    """Not started — _drain() and publish_* are pure and need no event loop."""
    return BreathWebSocketServer(port=0)


# ── message format: must match what index.html parses ─────────────────────────


def test_sample_message_format(server):
    server.publish_sample("dev-a", 0.4242424242)
    payloads = [json.loads(p) for p in server._drain()]
    assert payloads == [{"uuid": "dev-a", "value": 0.4242}]


def test_disconnect_message_format(server):
    server.publish_disconnect("dev-a")
    msg = json.loads(server._drain()[0])
    # index.html branches on truthy msg.disconnected, then reads msg.uuid.
    assert msg["disconnected"] is True
    assert msg["uuid"] == "dev-a"


def test_payloads_are_byte_identical_to_the_old_bridge(server):
    """
    index.html is unchanged, so the wire format must be too.  These are the exact
    strings stop-and-let-the-rose-smell-v2/osc_ws_bridge.py put on the socket:

        json.dumps({"uuid": uuid, "value": round(value, 4)})
        json.dumps({"uuid": uuid, "value": None, "disconnected": True})
    """
    server.publish_sample("abc-123", 0.56789)
    assert server._drain() == ['{"uuid": "abc-123", "value": 0.5679}']

    server.publish_disconnect("abc-123")
    assert server._drain() == [
        '{"uuid": "abc-123", "value": null, "disconnected": true}'
    ]


def test_disconnects_precede_samples_in_a_tick(server):
    """A stale sample must not resurrect a device that dropped out this tick."""
    server.publish_sample("dev-a", 0.5)
    server.publish_disconnect("dev-a")
    kinds = [json.loads(p).get("disconnected", False) for p in server._drain()]
    assert kinds == [True, False]


# ── bounded under pressure ───────────────────────────────────────────────────


def test_samples_coalesce_to_one_per_device(server):
    """1000 packets from one device between ticks must not queue 1000 messages."""
    for i in range(1000):
        server.publish_sample("dev-a", i / 1000.0)
    payloads = server._drain()
    assert len(payloads) == 1
    # The newest value wins — the visualization lerps toward the latest target.
    assert json.loads(payloads[0])["value"] == 0.999


def test_buffer_is_bounded_by_device_count(server):
    for tick in range(50):
        for dev in range(6):
            for _ in range(200):
                server.publish_sample(f"dev-{dev}", 0.5)
        # Never more than one message per device, regardless of packet rate.
        assert len(server._pending) <= 6
        server._drain()


def test_drain_leaves_buffer_empty(server):
    server.publish_sample("dev-a", 0.1)
    server.publish_disconnect("dev-b")
    server._drain()
    assert server._drain() == []


def test_disconnects_survive_a_sample_flood(server):
    """Disconnects are on their own buffer, so samples cannot crowd them out."""
    server.publish_disconnect("gone")
    for i in range(100_000):
        server.publish_sample(f"dev-{i % 6}", 0.5)
    msgs = [json.loads(p) for p in server._drain()]
    assert any(m.get("disconnected") and m["uuid"] == "gone" for m in msgs)
    assert server.dropped_events == 0


def test_no_clients_still_drains(server):
    """With nothing connected the buffer must not grow without bound."""
    for i in range(500):
        server.publish_sample("dev-a", 0.5)
        server._drain()
    assert server._pending == {}


# ── must never block the OSC/MIDI thread ─────────────────────────────────────


def test_publish_is_fast_enough_for_the_osc_thread(server):
    """
    publish_sample runs per OSC packet on the thread that also does MIDI.  It is
    a dict assignment, so this is really asserting no lock or I/O crept in.
    """
    n = 200_000
    start = time.perf_counter()
    for i in range(n):
        server.publish_sample("dev-a", 0.5)
    elapsed = time.perf_counter() - start
    per_call_us = (elapsed / n) * 1e6
    assert per_call_us < 5.0, f"publish_sample took {per_call_us:.2f}us/call"


def test_publish_never_blocks_when_server_not_running(server):
    """A stopped or failed server must not wedge the caller."""
    for _ in range(1000):
        server.publish_sample("dev-a", 0.5)
        server.publish_disconnect("dev-a")
    assert not server.running


def test_publish_is_safe_from_multiple_threads(server):
    """
    The OSC thread is the only publisher today, but the dict swap in _drain must
    not tear if that ever changes.
    """
    stop = threading.Event()
    errors: list[BaseException] = []

    def publisher(dev: str) -> None:
        try:
            while not stop.is_set():
                server.publish_sample(dev, 0.5)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=publisher, args=(f"d{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for _ in range(200):
        server._drain()
    stop.set()
    for t in threads:
        t.join(timeout=2.0)
    assert errors == []


# ── lifecycle ────────────────────────────────────────────────────────────────


def test_start_and_stop_binds_and_releases_the_port():
    server = BreathWebSocketServer(port=8799)
    server.start()
    try:
        assert server.running
        # Port is really bound: a plain TCP connect must succeed.
        with socket.create_connection(("localhost", 8799), timeout=2.0):
            pass
    finally:
        server.stop()
    assert not server.running
    # And released — a second server can take it.
    again = BreathWebSocketServer(port=8799)
    again.start()
    again.stop()


def test_start_on_a_busy_port_raises():
    """A taken 8765 must fail loudly, not half-start."""
    first = BreathWebSocketServer(port=8798)
    first.start()
    try:
        second = BreathWebSocketServer(port=8798)
        with pytest.raises(OSError):
            second.start()
        assert not second.running
    finally:
        first.stop()
