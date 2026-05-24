#!/usr/bin/env python3
"""
osc_ws_bridge.py  —  OSC-to-WebSocket bridge for rose-breath visualization.

HOW TO RUN:
    python osc_ws_bridge.py

    Activate the breath-choir venv first (python-osc and websockets are already
    installed there), or install standalone:
        pip install python-osc websockets

PHONES:
    Phones must be connected to the TP-Link router.
    Configure TOTEM to send OSC to this Mac's static IP on port 8001.
    OSC format:  /breath_value/<uuid>  →  float 0.0 – 1.0

BROWSER:
    Open rose_breath/index.html in a browser — it connects to ws://localhost:8765.
"""

import asyncio
import json
import time

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
import websockets

OSC_PORT       = 8001   # phones send here
WS_PORT        = 8765   # browser connects here
FORWARD_PORT   = 8002   # breath-choir MIDI app listens here
DEVICE_TIMEOUT = 5.0   # seconds before a silent device is considered gone

connected_clients: set = set()
active_devices:   dict = {}   # uuid -> monotonic timestamp of last message


async def broadcast(message: str) -> None:
    if not connected_clients:
        return
    await asyncio.gather(
        *(client.send(message) for client in connected_clients),
        return_exceptions=True,
    )


async def ws_handler(websocket) -> None:
    connected_clients.add(websocket)
    print(f"[WS]  Browser connected    ({len(connected_clients)} client(s))")
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)
        print(f"[WS]  Browser disconnected  ({len(connected_clients)} client(s))")


async def timeout_loop() -> None:
    while True:
        await asyncio.sleep(1.0)
        now     = time.monotonic()
        expired = [u for u, t in list(active_devices.items()) if now - t > DEVICE_TIMEOUT]
        for uuid in expired:
            del active_devices[uuid]
            print(f"[-] Device timed out:   {uuid}")
            await broadcast(json.dumps({"uuid": uuid, "value": None, "disconnected": True}))


async def main() -> None:
    loop = asyncio.get_running_loop()
    forwarder = SimpleUDPClient("127.0.0.1", FORWARD_PORT)

    def osc_handler(address: str, *args) -> None:
        # address = /breath_value/<uuid>
        parts = address.strip("/").split("/")
        if len(parts) < 2:
            return
        uuid  = parts[1]
        value = float(args[0]) if args else 0.0

        is_new = uuid not in active_devices
        active_devices[uuid] = time.monotonic()

        if is_new:
            print(f"[+] Device connected:   {uuid}")

        forwarder.send_message(address, value)
        loop.create_task(broadcast(json.dumps({"uuid": uuid, "value": round(value, 4)})))

    dispatcher = Dispatcher()
    dispatcher.map("/breath_value/*", osc_handler)

    transport, _ = await AsyncIOOSCUDPServer(
        ("0.0.0.0", OSC_PORT), dispatcher, loop
    ).create_serve_endpoint()
    print(f"[OSC] Listening on UDP  port {OSC_PORT}")

    async with websockets.serve(ws_handler, "localhost", WS_PORT):
        print(f"[WS]  Serving on         ws://localhost:{WS_PORT}")
        print()
        print("Waiting for devices…  (Ctrl+C to stop)")
        await timeout_loop()

    transport.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBridge stopped.")
