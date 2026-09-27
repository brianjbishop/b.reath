"""
Which network are we on?

Answering "are the phones going to reach us" by **gateway MAC address** rather
than by Wi-Fi SSID. Modern macOS will not hand out the SSID without Location
Services permission — `networksetup -getairportnetwork` just reports "not
associated" — whereas the router's MAC is in the ARP table and needs nothing.
It is also stricter: two routers can share an SSID, but the MAC is that
specific box.

Polled on a background thread. The lookup shells out, and doing that on the UI
thread would stutter the frame loop.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass

_POLL_SECONDS = 3.0
_MAC_RE = re.compile(r"(?:[0-9a-f]{1,2}:){5}[0-9a-f]{1,2}", re.I)


@dataclass(frozen=True)
class NetworkIdentity:
    ip: str = ""
    gateway_ip: str = ""
    gateway_mac: str = ""

    @property
    def online(self) -> bool:
        return bool(self.ip and self.gateway_mac)


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout
    except Exception:
        return ""


def _normalise_mac(mac: str) -> str:
    """arp prints 'b0:b3:69:2b:90:3f' but drops leading zeros, e.g. '0:1c:...'."""
    parts = mac.lower().split(":")
    return ":".join(p.rjust(2, "0") for p in parts)


def read_identity() -> NetworkIdentity:
    """One synchronous lookup. Cheap, but not cheap enough for a frame."""
    gateway_ip = ""
    for line in _run(["netstat", "-rn"]).splitlines():
        if line.startswith("default"):
            fields = line.split()
            if len(fields) >= 2 and fields[1].count(".") == 3:
                gateway_ip = fields[1]
                break
    if not gateway_ip:
        return NetworkIdentity()

    ip = _run(["ipconfig", "getifaddr", "en0"]).strip()
    if not ip:
        for iface in ("en1", "en2"):
            ip = _run(["ipconfig", "getifaddr", iface]).strip()
            if ip:
                break

    mac = ""
    match = _MAC_RE.search(_run(["arp", "-n", gateway_ip]))
    if match:
        mac = _normalise_mac(match.group(0))
    return NetworkIdentity(ip=ip, gateway_ip=gateway_ip, gateway_mac=mac)


class NetworkWatcher:
    """Keeps a current NetworkIdentity, refreshed off the UI thread."""

    def __init__(self, expected_mac: str = "") -> None:
        self._expected = _normalise_mac(expected_mac) if expected_mac else ""
        self._identity = NetworkIdentity()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="net-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            identity = read_identity()
            with self._lock:
                self._identity = identity
            self._stop.wait(_POLL_SECONDS)

    @property
    def identity(self) -> NetworkIdentity:
        with self._lock:
            return self._identity

    @property
    def expected_mac(self) -> str:
        return self._expected

    def set_expected(self, mac: str) -> None:
        self._expected = _normalise_mac(mac) if mac else ""

    def learn_current(self) -> str:
        """Adopt whatever router we are on now as the expected one."""
        mac = self.identity.gateway_mac
        if mac:
            self._expected = mac
        return mac

    @property
    def on_expected_network(self) -> bool:
        """Unconfigured means we cannot know, so this stays False."""
        if not self._expected:
            return False
        return self.identity.gateway_mac == self._expected
