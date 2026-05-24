#!/usr/bin/env python3
"""
TOTEM breath receiver + visualizer.

- Listens for OSC packets on /breath_value/<uuid>.
- Each unique address gets its own column: warm-white (inhale=1.0) -> black (exhale=0.0).
- Streams silent for >1s are dropped and the column disappears.
- "Show QR" button pops a QR code encoding {"ip":..., "port":..., "name":...}
  for the TOTEM app to scan.

Requires (all already installed in this env):
    python-osc, qrcode, Pillow  (tkinter comes with Python)
If you ever need to reinstall:
    pip install python-osc "qrcode[pil]" pillow
"""

import json
import socket
import threading
import time
import tkinter as tk

import qrcode
from PIL import ImageTk
from pythonosc import dispatcher, osc_server

PORT = 8000
TIMEOUT_S = 1.0
REFRESH_MS = 33  # ~30 fps
WARM_WHITE = (255, 224, 188)   # (R,G,B) at full inhale
BLACK = (0, 0, 0)              # at full exhale
VIZ_NAME = "Breath Viz"


def local_ip() -> str:
    """Best-effort: get the outbound-facing IP on the current network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def lerp_rgb(v: float, a, b) -> str:
    v = max(0.0, min(1.0, v))
    r, g, bl = (int(a[i] + (b[i] - a[i]) * v) for i in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"


class Streams:
    """Thread-safe map of address -> (value, last_update_ts)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, float]] = {}

    def update(self, key: str, value: float):
        with self._lock:
            self._data[key] = (value, time.monotonic())

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            for k in [k for k, (_, t) in self._data.items() if now - t > TIMEOUT_S]:
                del self._data[k]
            # Preserve insertion order (Python 3.7+ dicts) for stable column order.
            return list(self._data.items())


class App:
    def __init__(self, root: tk.Tk, streams: Streams, port: int):
        self.root = root
        self.streams = streams
        self.port = port
        self._qr_image_ref = None  # keep a reference so Tk doesn't GC the image

        root.title(f"TOTEM Breath Viz — port {port}")
        root.geometry("900x650")
        root.configure(bg="black")

        self.canvas = tk.Canvas(root, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        btn = tk.Button(
            root, text="Show QR", command=self.show_qr,
            font=("Helvetica", 14, "bold"), pady=8,
        )
        btn.pack(side="bottom", fill="x")

        self.root.after(REFRESH_MS, self._refresh)

    def _refresh(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            self.root.after(REFRESH_MS, self._refresh)
            return

        items = self.streams.snapshot()
        if not items:
            self.canvas.create_text(
                w // 2, h // 2,
                text=f"Waiting for breath packets on {local_ip()}:{self.port}",
                fill="#303030", font=("Helvetica", 16),
            )
        else:
            n = len(items)
            col_w = w / n
            for i, (address, (value, _ts)) in enumerate(items):
                color = lerp_rgb(value, BLACK, WARM_WHITE)
                self.canvas.create_rectangle(
                    i * col_w, 0, (i + 1) * col_w, h,
                    fill=color, outline="",
                )
                # Short label: last path component, truncated.
                label = address.rsplit("/", 1)[-1][:8]
                self.canvas.create_text(
                    i * col_w + col_w / 2, h - 24,
                    text=f"{label}  {value:.3f}",
                    fill="#6a6a6a", font=("Helvetica", 11),
                )

        self.root.after(REFRESH_MS, self._refresh)

    def show_qr(self):
        ip = local_ip()
        payload = json.dumps(
            {"ip": ip, "port": self.port, "name": VIZ_NAME},
            separators=(",", ":"),
        )
        img = qrcode.make(payload).resize((420, 420))

        top = tk.Toplevel(self.root)
        top.title("Scan with TOTEM app")
        top.configure(bg="white")
        top.geometry("520x640")

        self._qr_image_ref = ImageTk.PhotoImage(img)  # keep a strong ref
        tk.Label(top, image=self._qr_image_ref, bg="white").pack(pady=20)
        tk.Label(
            top, text=f"{ip}:{self.port}",
            font=("Helvetica", 20, "bold"), bg="white",
        ).pack()
        tk.Label(
            top, text=payload,
            font=("Menlo", 11), bg="white", fg="#606060",
            wraplength=480, justify="center",
        ).pack(pady=14)
        tk.Button(
            top, text="Close", command=top.destroy,
            font=("Helvetica", 13),
        ).pack(pady=10)


def make_handler(streams: Streams):
    def handler(address: str, *args):
        if not args:
            return
        try:
            value = float(args[0])
        except (TypeError, ValueError):
            return
        streams.update(address, value)
    return handler


def main():
    streams = Streams()
    disp = dispatcher.Dispatcher()
    disp.set_default_handler(make_handler(streams))

    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", PORT), disp)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"OSC listening on 0.0.0.0:{PORT} — local IP {local_ip()}")

    root = tk.Tk()
    App(root, streams, PORT)
    try:
        root.mainloop()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
