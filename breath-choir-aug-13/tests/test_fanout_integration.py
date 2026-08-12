"""
End-to-end fan-out: real UDP packets in, real WebSocket frames out.

This is the test that would have caught the original bug. It runs a real
EveryBreathHub, sends real OSC datagrams at its socket, and reads frames off a
real WebSocket client — one process, no bridge, no 8002 hop.

Ports are non-default so a running copy of the app does not collide with the
suite.
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import threading
import time
from dataclasses import replace

import pytest

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.every_breath.multi_osc import MultiDeviceOscSource

from .test_hold_triggers import base_config

OSC_PORT = 8811
WS_PORT = 8812


def osc_packet(uuid: str, value: float) -> bytes:
    """Minimal OSC message: /breath_value/<uuid> with one float."""
    addr = f"/breath_value/{uuid}".encode()
    addr += b"\0" * (4 - len(addr) % 4)
    tags = b",f"
    tags += b"\0" * (4 - len(tags) % 4)
    return addr + tags + struct.pack(">f", value)


def send(value: float, uuid: str = "phone-1", port: int = OSC_PORT) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(osc_packet(uuid, value), ("127.0.0.1", port))
    finally:
        sock.close()


@pytest.fixture
def hub():
    cfg = base_config()
    cfg = replace(cfg, viz=replace(cfg.viz, ws_port=WS_PORT))
    h = EveryBreathHub(config=cfg, osc_port=OSC_PORT)
    h.start_listening()
    yield h
    h.stop_listening()


def collect_frames(count: int, timeout_s: float = 6.0) -> list[dict]:
    """Connect a WebSocket client and gather up to `count` messages."""
    import websockets

    frames: list[dict] = []

    async def run() -> None:
        async with websockets.connect(f"ws://localhost:{WS_PORT}") as ws:
            # Give the hub a moment, then push traffic from a helper thread so
            # the datagrams arrive while this client is actually connected.
            threading.Thread(target=_pump, daemon=True).start()
            deadline = time.monotonic() + timeout_s
            while len(frames) < count and time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                frames.append(json.loads(raw))

    def _pump() -> None:
        for i in range(60):
            send(0.1 + (i % 8) * 0.1)
            time.sleep(0.02)

    asyncio.run(run())
    return frames


def test_osc_packet_reaches_the_browser(hub):
    frames = collect_frames(count=3)
    assert frames, "no WebSocket frames arrived — fan-out is broken"
    samples = [f for f in frames if not f.get("disconnected")]
    assert samples, f"no sample frames in {frames}"
    for f in samples:
        assert f["uuid"] == "phone-1"
        assert 0.0 <= f["value"] <= 1.0


def test_device_registers_in_the_grid_too(hub):
    """The same packets must still drive the device registry and MIDI path."""
    for _ in range(5):
        send(0.5)
        time.sleep(0.02)
    time.sleep(0.5)
    entries = hub.registry.all_entries()
    assert [e.uuid for e in entries] == ["phone-1"]
    assert "phone-1" in hub.registry.connected_uuids()


def test_websocket_client_can_come_and_go(hub):
    """A browser reload must not disturb the hub."""
    first = collect_frames(count=2)
    second = collect_frames(count=2)
    assert first and second
    assert hub._listening


def test_no_browser_connected_is_harmless(hub):
    """Packets with nothing watching must not accumulate or raise."""
    for i in range(200):
        send(0.5)
    time.sleep(0.5)
    assert hub._ws is not None
    assert len(hub._ws._pending) <= 1
    assert hub._listening


# ── the original bug: a second bind must now fail loudly ─────────────────────


def test_second_osc_bind_is_refused(hub):
    """
    With SO_REUSEADDR gone, a second listener on the OSC port must raise instead
    of silently splitting datagrams with the first.
    """
    clash = MultiDeviceOscSource(
        port=OSC_PORT,
        on_sample_cb=lambda s: None,
        on_new_device_cb=lambda u: None,
        on_timeout_cb=lambda u: None,
    )
    with pytest.raises(OSError):
        clash.start()
    clash.stop()


def test_hub_start_raises_on_busy_osc_port(hub):
    """A second hub on the same port must fail rather than half-start."""
    cfg = base_config()
    cfg = replace(cfg, viz=replace(cfg.viz, ws_enabled=False))
    second = EveryBreathHub(config=cfg, osc_port=OSC_PORT)
    with pytest.raises(OSError):
        second.start_listening()
    assert not second._listening


def test_reusaddr_is_not_set_on_the_osc_socket(hub):
    sock = hub._source._sock
    assert sock is not None
    assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0


# ── disconnect propagation reuses the hub's own timeout ──────────────────────


def test_timeout_notifies_the_browser():
    """
    The hub's existing 5s device timeout is what tells the browser a phone is
    gone — no second timer.  Driving _on_timeout directly keeps this fast.
    """
    cfg = base_config()
    cfg = replace(cfg, viz=replace(cfg.viz, ws_port=WS_PORT + 1))
    h = EveryBreathHub(config=cfg, osc_port=OSC_PORT + 1)
    h.start_listening()
    try:
        h._on_timeout("phone-gone")
        msgs = [json.loads(p) for p in h._ws._drain()]
        assert msgs == [{"uuid": "phone-gone", "value": None, "disconnected": True}]
    finally:
        h.stop_listening()


def test_ws_disabled_leaves_midi_path_working():
    cfg = base_config()
    cfg = replace(cfg, viz=replace(cfg.viz, ws_enabled=False))
    h = EveryBreathHub(config=cfg, osc_port=OSC_PORT + 2)
    h.start_listening()
    try:
        assert h._ws is None
        for _ in range(5):
            send(0.5, port=OSC_PORT + 2)
            time.sleep(0.02)
        time.sleep(0.5)
        assert [e.uuid for e in h.registry.all_entries()] == ["phone-1"]
    finally:
        h.stop_listening()


def test_busy_ws_port_does_not_take_down_listening():
    """Losing the visualization must never cost you MIDI."""
    from breath_midi.viz.ws_server import BreathWebSocketServer

    blocker = BreathWebSocketServer(port=WS_PORT + 3)
    blocker.start()
    cfg = base_config()
    cfg = replace(cfg, viz=replace(cfg.viz, ws_port=WS_PORT + 3))
    h = EveryBreathHub(config=cfg, osc_port=OSC_PORT + 3)
    try:
        h.start_listening()
        assert h._listening, "MIDI listening must survive a busy WS port"
        assert h._ws is None
        assert h.viz_error is not None and str(WS_PORT + 3) in h.viz_error
    finally:
        h.stop_listening()
        blocker.stop()
