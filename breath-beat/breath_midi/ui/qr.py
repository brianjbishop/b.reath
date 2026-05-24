from __future__ import annotations

import json
import os
import socket
import tempfile

import dearpygui.dearpygui as dpg
import qrcode
from PIL import Image

_QR_TEX_TAG = "qr_popup_texture"
_QR_REG_TAG = "qr_popup_registry"
_QR_WIN_TAG = "qr_popup_win"
_QR_SIZE = 300


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def show_qr_popup(port: int, app_name: str) -> None:
    if dpg.does_item_exist(_QR_WIN_TAG):
        dpg.focus_item(_QR_WIN_TAG)
        return

    ip = _local_ip()
    payload = json.dumps({"ip": ip, "port": port, "name": app_name}, separators=(",", ":"))

    img = qrcode.make(payload).convert("RGBA")
    img = img.resize((_QR_SIZE, _QR_SIZE), resample=Image.Resampling.NEAREST)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
    try:
        img.save(tmp_path)
        w, h, _, data = dpg.load_image(tmp_path)
    finally:
        os.unlink(tmp_path)

    if dpg.does_item_exist(_QR_REG_TAG):
        dpg.delete_item(_QR_REG_TAG)

    with dpg.texture_registry(tag=_QR_REG_TAG):
        dpg.add_static_texture(width=w, height=h, default_value=data, tag=_QR_TEX_TAG)

    def _on_close() -> None:
        if dpg.does_item_exist(_QR_WIN_TAG):
            dpg.delete_item(_QR_WIN_TAG)
        if dpg.does_item_exist(_QR_REG_TAG):
            dpg.delete_item(_QR_REG_TAG)

    with dpg.window(
        label="Scan with TOTEM app",
        tag=_QR_WIN_TAG,
        modal=True,
        width=_QR_SIZE + 80,
        pos=[100, 80],
        on_close=_on_close,
    ):
        dpg.add_image(_QR_TEX_TAG)
        dpg.add_spacer(height=6)
        dpg.add_text(f"{ip}:{port}", color=(80, 160, 220))
        dpg.add_text(payload, color=(120, 120, 120), wrap=_QR_SIZE + 40)
        dpg.add_spacer(height=8)
        dpg.add_button(label="Close", width=-1, callback=_on_close)
