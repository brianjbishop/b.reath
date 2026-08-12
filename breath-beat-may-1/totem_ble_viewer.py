#!/usr/bin/env python3
"""
TOTEM Breath Receiver (Dear PyGui)

Receives computed breath values from the TOTEM iOS app via BLE or OSC and displays
a live scrolling plot of the last 15 seconds.

This version uses Dear PyGui (no Qt) to avoid macOS Qt platform plugin issues.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from uuid import UUID

import dearpygui.dearpygui as dpg

# Import bleak FIRST — PyObjC type registrations must happen before
# other frameworks load conflicting types.
from bleak import BleakClient, BleakScanner


# BLE constants
BREATH_CHAR_UUID = "2C9E2E89-C488-4B7E-A6AB-5C37A99916DB"
SERVICE_UUID = "E4BE43E9-BFC5-49BE-B072-3622A0CE8410"

WINDOW_SECONDS = 15.0
DEFAULT_OSC_PORT = 8000


def parse_osc_message(data: bytes) -> tuple[str, list[object]] | None:
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


@dataclass(frozen=True)
class BleDevice:
    label: str
    address: str


class BleManager:
    def __init__(self, on_sample):
        self._on_sample = on_sample
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: BleakClient | None = None

        self._lock = threading.Lock()
        self._status = "disconnected"
        self._connected = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        loop = self._loop
        if loop and loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._async_disconnect(), loop)
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

    def status(self) -> tuple[str, bool]:
        with self._lock:
            return (self._status, self._connected)

    def scan(self) -> list[BleDevice]:
        loop = self._loop
        if loop is None or not loop.is_running():
            return []
        fut = asyncio.run_coroutine_threadsafe(self._async_scan(), loop)
        try:
            return fut.result(timeout=6.0)
        except Exception:
            return []

    def connect(self, address: str) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._async_connect(address), loop)

    def disconnect(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._async_disconnect(), loop)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
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

    async def _async_scan(self) -> list[BleDevice]:
        with self._lock:
            self._status = "scanning"
        devices: list[BleDevice] = []
        try:
            found = await BleakScanner.discover(
                timeout=4.0, return_adv=True, service_uuids=[SERVICE_UUID]
            )
            for _addr, (d, adv) in found.items():
                local_name = (adv.local_name or d.name or "Unknown").strip()
                label = f"TOTEM ({local_name})"
                devices.append(BleDevice(label=label, address=d.address))
            with self._lock:
                self._status = f"found_{len(devices)}"
        except Exception as e:
            with self._lock:
                self._status = f"scan_error: {e}"
        return devices

    async def _async_connect(self, address: str) -> None:
        with self._lock:
            self._status = "connecting"
        try:
            await self._async_disconnect()
        except Exception:
            pass

        try:
            self._client = BleakClient(address, disconnected_callback=self._on_disconnect)
            await self._client.connect()
            await self._client.start_notify(BREATH_CHAR_UUID, self._on_notify)
            with self._lock:
                self._connected = True
                self._status = "connected"
        except Exception as e:
            with self._lock:
                self._connected = False
                self._status = f"connect_error: {e}"

    async def _async_disconnect(self) -> None:
        if self._client is None:
            with self._lock:
                self._connected = False
                self._status = "disconnected"
            return
        try:
            await self._client.disconnect()
        finally:
            self._client = None
            with self._lock:
                self._connected = False
                self._status = "disconnected"

    def _on_disconnect(self, _client) -> None:
        with self._lock:
            self._connected = False
            self._status = "disconnected"

    def _on_notify(self, _sender, data: bytearray) -> None:
        if len(data) < 28:
            return
        uuid_bytes = bytes(data[:16])
        device_uuid = str(UUID(bytes=uuid_bytes))
        _t_rel = struct.unpack(">d", data[16:24])[0]
        breath_value = float(struct.unpack(">f", data[24:28])[0])
        self._on_sample(device_uuid, breath_value)


class OscManager:
    def __init__(self, on_sample):
        self._on_sample = on_sample
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._port = DEFAULT_OSC_PORT

    def start(self, port: int) -> None:
        if self._running:
            return
        self._port = int(port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self._port))
        self._sock.settimeout(0.5)
        self._running = True
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

    def is_running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        assert self._sock is not None
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = parse_osc_message(data)
            if parsed is None:
                continue
            address, args = parsed
            if address.startswith("/breath_value/") and args:
                device_uuid = address.split("/")[-1]
                try:
                    breath_value = float(args[0])
                except Exception:
                    continue
                self._on_sample(device_uuid, breath_value)


class AppState:
    def __init__(self):
        self.lock = threading.Lock()

        self.mode: str = "ble"  # "ble" or "osc"
        self.status: str = "disconnected"
        self.connected: bool = False

        self.device_uuid: str = "--"
        self.latest_value: float = 0.0

        self.times: deque[float] = deque(maxlen=1600)
        self.values: deque[float] = deque(maxlen=1600)
        self._t0: float | None = None
        self._last_rx: float = 0.0

        self._rx_count: int = 0
        self._rx_t0: float = time.monotonic()
        self.rx_hz: float = 0.0

        self.ble_devices: list[BleDevice] = []
        self.ble_selected_addr: str = ""

    def on_sample(self, device_uuid: str, value: float) -> None:
        now = time.monotonic()
        with self.lock:
            if self._last_rx > 0 and (now - self._last_rx) > 1.0:
                self.times.clear()
                self.values.clear()
                self._t0 = None
            self._last_rx = now

            if self._t0 is None:
                self._t0 = now
            t_rel = now - self._t0

            self.device_uuid = device_uuid
            self.latest_value = float(value)
            self.times.append(t_rel)
            self.values.append(float(value))

            # trim to window
            cutoff = t_rel - WINDOW_SECONDS
            while self.times and self.times[0] < cutoff:
                self.times.popleft()
                self.values.popleft()

            # rx rate
            self._rx_count += 1
            elapsed = now - self._rx_t0
            if elapsed >= 1.0:
                self.rx_hz = self._rx_count / elapsed
                self._rx_count = 0
                self._rx_t0 = now


def main() -> None:
    state = AppState()
    ble = BleManager(on_sample=state.on_sample)
    osc = OscManager(on_sample=state.on_sample)

    ble.start()

    dpg.create_context()
    dpg.create_viewport(title="TOTEM Breath Receiver", width=980, height=560)
    dpg.setup_dearpygui()

    # UI IDs
    with dpg.window(label="TOTEM Breath Receiver", tag="main", width=960, height=520):
        with dpg.group(horizontal=True):
            dpg.add_text("Mode:")

            def on_mode_change(_sender, app_data, user_data):
                mode = "ble" if user_data == "ble" else "osc"
                with state.lock:
                    state.mode = mode
                    state.status = "disconnected" if mode == "ble" else "osc_stopped"
                    state.connected = False
                if mode == "ble":
                    osc.stop()
                else:
                    ble.disconnect()

            dpg.add_radio_button(
                items=["ble", "osc"],
                default_value="ble",
                horizontal=True,
                callback=on_mode_change,
            )

            dpg.add_spacer(width=12)
            dpg.add_text("Status:", color=(180, 180, 180))
            dpg.add_text("--", tag="status_text")
            dpg.add_spacer(width=12)
            dpg.add_text("RX:", color=(180, 180, 180))
            dpg.add_text("--", tag="rx_text")

        with dpg.group(horizontal=True):
            # BLE row
            def on_ble_scan():
                devs = ble.scan()
                with state.lock:
                    state.ble_devices = devs
                items = [f"{d.label} [{d.address}]" for d in devs] if devs else []
                dpg.configure_item("ble_combo", items=items)

            def on_ble_connect():
                selected = dpg.get_value("ble_combo")
                addr = ""
                with state.lock:
                    for d in state.ble_devices:
                        label = f"{d.label} [{d.address}]"
                        if label == selected:
                            addr = d.address
                            break
                if addr:
                    ble.connect(addr)

            def on_ble_disconnect():
                ble.disconnect()

            dpg.add_button(label="Scan", callback=lambda: on_ble_scan(), tag="ble_scan_btn")
            dpg.add_combo([], width=320, tag="ble_combo")
            dpg.add_button(label="Connect", callback=lambda: on_ble_connect(), tag="ble_connect_btn")
            dpg.add_button(label="Disconnect", callback=lambda: on_ble_disconnect(), tag="ble_disconnect_btn")

            dpg.add_spacer(width=16)

            # OSC row
            dpg.add_text("Port:")
            dpg.add_input_int(tag="osc_port", default_value=DEFAULT_OSC_PORT, width=90, min_value=1, max_value=65535)

            def on_osc_toggle():
                port = int(dpg.get_value("osc_port"))
                if osc.is_running():
                    osc.stop()
                else:
                    osc.start(port)

            dpg.add_button(label="Listen/Stop", callback=lambda: on_osc_toggle(), tag="osc_toggle_btn")

        dpg.add_separator()

        with dpg.group(horizontal=True):
            dpg.add_text("Device UUID:", color=(180, 180, 180))
            dpg.add_text("--", tag="uuid_text")
            dpg.add_spacer(width=12)
            dpg.add_text("Breath:", color=(180, 180, 180))
            dpg.add_text("0.0000", tag="value_text")

        # Plot
        with dpg.plot(label="Computed Breath Value", height=380, width=-1):
            dpg.add_plot_legend()
            dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="xaxis")
            dpg.add_plot_axis(dpg.mvYAxis, label="Breath", tag="yaxis")
            dpg.set_axis_limits("yaxis", -0.05, 1.05)
            dpg.add_line_series([], [], label="breath", parent="yaxis", tag="series")

    dpg.show_viewport()

    # Main loop
    while dpg.is_dearpygui_running():
        with state.lock:
            mode = state.mode
            # Pull BLE status for UI
            ble_status, ble_connected = ble.status()
            if mode == "ble":
                state.status = ble_status
                state.connected = ble_connected
            else:
                state.status = "osc_listening" if osc.is_running() else "osc_stopped"
                state.connected = osc.is_running()

            ts = list(state.times)
            vs = list(state.values)
            uuid = state.device_uuid
            val = state.latest_value
            rx_hz = state.rx_hz
            status = state.status

        # Update UI controls visibility (mode toggle row style)
        is_ble = mode == "ble"
        dpg.configure_item("ble_scan_btn", show=is_ble)
        dpg.configure_item("ble_combo", show=is_ble)
        dpg.configure_item("ble_connect_btn", show=is_ble)
        dpg.configure_item("ble_disconnect_btn", show=is_ble)

        dpg.configure_item("osc_port", show=not is_ble)
        dpg.configure_item("osc_toggle_btn", show=not is_ble)

        dpg.set_value("status_text", status)
        dpg.set_value("rx_text", f"{rx_hz:.0f} Hz")
        dpg.set_value("uuid_text", uuid)
        dpg.set_value("value_text", f"{val:.4f}")

        if ts:
            latest = ts[-1]
            if latest <= WINDOW_SECONDS:
                dpg.set_axis_limits("xaxis", 0.0, WINDOW_SECONDS)
            else:
                dpg.set_axis_limits("xaxis", latest - WINDOW_SECONDS, latest)
            dpg.set_value("series", [ts, vs])

        dpg.render_dearpygui_frame()

        # Light throttle: DPG will typically vsync; keep loop stable.
        time.sleep(0.001)

    # Cleanup
    osc.stop()
    ble.stop()
    dpg.destroy_context()


if __name__ == "__main__":
    main()
