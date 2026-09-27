from __future__ import annotations

import json
import socket

import dearpygui.dearpygui as dpg
import qrcode
from PIL import Image

_QR_TEX_TAG = "qr_popup_texture"
_QR_REG_TAG = "qr_popup_registry"
_QR_WIN_TAG = "qr_popup_win"
_QR_ADDR_TAG = "qr_popup_addr"
_QR_PAYLOAD_TAG = "qr_popup_payload"
_QR_SIZE = 300

# The texture and the window are built once and then reused for the rest of the
# session.  Neither is ever deleted, and that is the whole point.
#
# This used to delete the texture registry on close and rebuild it on the next
# open.  Both happen inside DPG callbacks, which run *during* a frame, so the
# Metal backend could still be holding the texture it was told to free — the
# app died with EXC_BAD_ACCESS inside ImGui_ImplMetal_RenderDrawData ->
# setFragmentTexture: -> objc_retain, on a dangling pointer.  It was a hard
# segfault, so Python never raised and nothing reached the log; it just
# vanished, usually within a minute of someone pressing Show QR.
#
# A dynamic texture can have its pixels replaced in place with set_value, so
# there is no free and nothing for the renderer to dangle on.
_built = False


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _blank() -> list[float]:
    return [1.0] * (_QR_SIZE * _QR_SIZE * 4)


def _qr_pixels(payload: str) -> list[float]:
    """Render the QR straight to DPG's float RGBA format — no temp file."""
    img = qrcode.make(payload).convert("RGBA")
    img = img.resize((_QR_SIZE, _QR_SIZE), resample=Image.Resampling.NEAREST)
    return [b / 255.0 for b in img.tobytes()]


def _ensure_built() -> None:
    global _built
    if _built:
        return
    if not dpg.does_item_exist(_QR_REG_TAG):
        with dpg.texture_registry(tag=_QR_REG_TAG):
            dpg.add_dynamic_texture(
                width=_QR_SIZE, height=_QR_SIZE, default_value=_blank(), tag=_QR_TEX_TAG
            )
    if not dpg.does_item_exist(_QR_WIN_TAG):
        with dpg.window(
            label="Scan with TOTEM app",
            tag=_QR_WIN_TAG,
            modal=True,
            show=False,
            width=_QR_SIZE + 80,
            pos=[100, 80],
            on_close=_hide,
        ):
            dpg.add_image(_QR_TEX_TAG)
            dpg.add_spacer(height=6)
            dpg.add_text("", tag=_QR_ADDR_TAG, color=(80, 160, 220))
            dpg.add_text("", tag=_QR_PAYLOAD_TAG, color=(120, 120, 120), wrap=_QR_SIZE + 40)
            dpg.add_spacer(height=8)
            dpg.add_button(label="Close", width=-1, callback=_hide)
    _built = True


def _hide(*_args) -> None:
    """Hide, never delete — see the note above."""
    if dpg.does_item_exist(_QR_WIN_TAG):
        dpg.configure_item(_QR_WIN_TAG, show=False)


def show_qr_popup(port: int, app_name: str) -> None:
    _ensure_built()

    ip = _local_ip()
    payload = json.dumps({"ip": ip, "port": port, "name": app_name}, separators=(",", ":"))

    dpg.set_value(_QR_TEX_TAG, _qr_pixels(payload))
    dpg.set_value(_QR_ADDR_TAG, f"{ip}:{port}")
    dpg.set_value(_QR_PAYLOAD_TAG, payload)

    dpg.configure_item(_QR_WIN_TAG, show=True)
    dpg.focus_item(_QR_WIN_TAG)


def _reset_for_tests() -> None:
    """DPG state does not survive destroy_context(); mirror that here."""
    global _built
    _built = False
