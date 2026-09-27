from __future__ import annotations

import asyncio
import struct
import threading
import time
from dataclasses import dataclass
from uuid import UUID

# Import bleak FIRST — PyObjC type registrations must happen before
# other frameworks load conflicting types.
from bleak import BleakClient, BleakScanner

from breath_midi.input.base import BreathInputSource, SampleCallback
from breath_midi.types import BreathSample


BREATH_CHAR_UUID = "2C9E2E89-C488-4B7E-A6AB-5C37A99916DB"
SERVICE_UUID = "E4BE43E9-BFC5-49BE-B072-3622A0CE8410"


@dataclass(frozen=True)
class BleDevice:
    label: str
    address: str


class BleBreathInput(BreathInputSource):
    def __init__(self, auto_connect: bool = True, address: str = ""):
        self.auto_connect = bool(auto_connect)
        self.address = str(address)

        self._cb: SampleCallback | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        self._client: BleakClient | None = None
        self._running = False

        self._status_lock = threading.Lock()
        self._status = "disconnected"
        self._connected = False
        self._last_rx_monotonic = 0.0
        self._rx_count = 0
        self._rx_t0 = 0.0
        self._rx_hz = 0.0

    # ---- status (for UI)
    def status(self) -> tuple[str, bool, float]:
        with self._status_lock:
            return (self._status, self._connected, float(self._rx_hz))

    def start(self, callback: SampleCallback) -> None:
        if self._running:
            return
        self._cb = callback
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        loop = self._loop
        if loop and loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._async_disconnect(), loop)
                # Give the disconnect a moment to finish so we don't leave
                # pending tasks behind when the event loop stops.
                try:
                    fut.result(timeout=2.0)
                except Exception:
                    pass
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=2.0)
            except Exception:
                pass
        self._loop = None

    def scan(self, timeout_s: float = 4.0) -> list[BleDevice]:
        loop = self._loop
        if loop is None or not loop.is_running():
            return []
        fut = asyncio.run_coroutine_threadsafe(self._async_scan(timeout_s), loop)
        try:
            return fut.result(timeout=timeout_s + 2.0)
        except Exception:
            return []

    def connect(self, address: str) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        self.address = address
        asyncio.run_coroutine_threadsafe(self._async_connect(address), loop)

    def disconnect(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        fut = asyncio.run_coroutine_threadsafe(self._async_disconnect(), loop)
        try:
            fut.result(timeout=3.0)
        except Exception:
            pass

    # ---- internal loop
    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        if self.auto_connect:
            self._loop.create_task(self._auto_connect_task())
        try:
            self._loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                for t in pending:
                    t.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass

    async def _auto_connect_task(self) -> None:
        # allow UI to come up
        await asyncio.sleep(0.5)
        if not self._running:
            return
        if not self.auto_connect:
            return
        if self.address:
            await self._async_connect(self.address)
            return

        # scan for first matching device
        with self._status_lock:
            self._status = "scanning"
        found_device = None

        def on_detect(device, adv_data):
            nonlocal found_device
            if found_device is None:
                found_device = (device, adv_data)

        scanner = BleakScanner(detection_callback=on_detect, service_uuids=[SERVICE_UUID])
        try:
            await scanner.start()
            for _ in range(50):
                if found_device or not self._running:
                    break
                await asyncio.sleep(0.1)
            await scanner.stop()
        except Exception as e:
            with self._status_lock:
                self._status = f"scan_error: {e}"
            return

        if not found_device:
            with self._status_lock:
                self._status = "no_device_found"
            return

        d, adv = found_device
        self.address = d.address
        await self._async_connect(d.address)

    async def _async_scan(self, timeout_s: float) -> list[BleDevice]:
        with self._status_lock:
            self._status = "scanning"
        devices: list[BleDevice] = []
        try:
            found = await BleakScanner.discover(
                timeout=float(timeout_s), return_adv=True, service_uuids=[SERVICE_UUID]
            )
            for _addr, (d, adv) in found.items():
                local_name = (adv.local_name or d.name or "Unknown").strip()
                label = f"TOTEM ({local_name})"
                devices.append(BleDevice(label=label, address=d.address))
            with self._status_lock:
                self._status = f"found_{len(devices)}"
        except Exception as e:
            with self._status_lock:
                self._status = f"scan_error: {e}"
        return devices

    async def _async_connect(self, address: str) -> None:
        with self._status_lock:
            self._status = "connecting"
        try:
            await self._async_disconnect()
        except Exception:
            pass

        try:
            self._client = BleakClient(address, disconnected_callback=self._on_disconnect)
            await self._client.connect()
            await self._client.start_notify(BREATH_CHAR_UUID, self._on_notify)
            with self._status_lock:
                self._connected = True
                self._status = "connected"
                self._rx_count = 0
                self._rx_t0 = time.monotonic()
                self._rx_hz = 0.0
        except Exception as e:
            with self._status_lock:
                self._connected = False
                self._status = f"connect_error: {e}"

    async def _async_disconnect(self) -> None:
        if self._client is None:
            with self._status_lock:
                self._connected = False
                self._status = "disconnected"
            return
        try:
            await self._client.disconnect()
        finally:
            self._client = None
            with self._status_lock:
                self._connected = False
                self._status = "disconnected"

    def _on_disconnect(self, _client) -> None:
        with self._status_lock:
            self._connected = False
            self._status = "disconnected"

    def _on_notify(self, _sender, data: bytearray) -> None:
        if not self._running or self._cb is None:
            return
        if len(data) < 28:
            return
        uuid_bytes = bytes(data[:16])
        device_uuid = str(UUID(bytes=uuid_bytes))
        _t_rel = struct.unpack(">d", data[16:24])[0]
        breath_value = float(struct.unpack(">f", data[24:28])[0])

        # locally re-time to monotonic so downstream has a consistent base
        now = time.monotonic()
        if self._last_rx_monotonic == 0.0:
            self._last_rx_monotonic = now
            self._t_origin = now  # type: ignore[attr-defined]
        t_rel = now - getattr(self, "_t_origin", now)

        # rx rate estimate
        with self._status_lock:
            self._rx_count += 1
            elapsed = now - self._rx_t0
            if elapsed >= 1.0:
                self._rx_hz = self._rx_count / elapsed
                self._rx_count = 0
                self._rx_t0 = now

        self._cb(BreathSample(t=t_rel, amp=breath_value, source_id=device_uuid))

