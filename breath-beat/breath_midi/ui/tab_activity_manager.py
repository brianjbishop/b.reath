from __future__ import annotations

import dearpygui.dearpygui as dpg

# DPG tags for the four circle buttons — must match what _build() creates.
_CIRCLE_TAGS: dict[str, str] = {
    "Single Breath": "circle_single",
    "Every Breath":  "circle_every",
    "Group Breath":  "circle_group",
    "Breath Beat":   "circle_breath_beat",
}

_PORT_8001_TABS = {"Every Breath", "Group Breath", "Breath Beat"}


class TabActivityManager:
    """
    Mutual-exclusion toggle for per-tab process lifecycle.

    Single Breath is independent — it can be active regardless of the
    port-8001 group state.

    Every Breath, Group Breath, and Breath Beat share port 8001 and are
    mutually exclusive with each other: activating any one automatically
    deactivates whichever of the three was previously active.
    """

    def __init__(self, runtime, eb_hub, bb_hub) -> None:
        self._runtime = runtime
        self._eb_hub = eb_hub
        self._bb_hub = bb_hub
        self._active_sb: bool = False          # Single Breath on/off
        self._active_8001: str | None = None   # active port-8001 tab, or None

    # ── public API ────────────────────────────────────────────────────────────

    def toggle(self, tab_name: str) -> None:
        """Called by a circle button click.  Activates or deactivates the tab."""
        if tab_name == "Single Breath":
            if self._active_sb:
                self._deactivate("Single Breath")
            else:
                self._activate("Single Breath")
        else:
            if self._active_8001 == tab_name:
                self._deactivate(tab_name)
            else:
                if self._active_8001 is not None:
                    self._deactivate(self._active_8001)
                self._activate(tab_name)

    @property
    def active_tab(self) -> str | None:
        return self._active_8001

    # ── private lifecycle ─────────────────────────────────────────────────────

    def _activate(self, tab_name: str) -> None:
        if tab_name == "Single Breath":
            self._runtime.start()
            self._active_sb = True
        elif tab_name in ("Every Breath", "Group Breath") and self._eb_hub is not None:
            out_port = self._runtime.config.midi.out_port.strip() or None
            self._eb_hub.start_listening(out_port)
            self._active_8001 = tab_name
        elif tab_name == "Breath Beat" and self._bb_hub is not None:
            out_port = self._runtime.config.midi.out_port.strip() or None
            self._bb_hub.start_listening(out_port)
            self._active_8001 = tab_name
            print("[bb] Breath Beat tab activated")
        self._update_circles()

    def _deactivate(self, tab_name: str) -> None:
        self._send_all_notes_off(tab_name)
        if tab_name == "Single Breath":
            self._runtime.stop()
            self._active_sb = False
        elif tab_name in ("Every Breath", "Group Breath") and self._eb_hub is not None:
            self._eb_hub.stop_listening()
            self._active_8001 = None
        elif tab_name == "Breath Beat" and self._bb_hub is not None:
            self._bb_hub.stop_listening()
            self._active_8001 = None
            print("[bb] Breath Beat tab deactivated")
        self._update_circles()

    # ── MIDI safety ───────────────────────────────────────────────────────────

    def _send_all_notes_off(self, tab_name: str) -> None:
        """
        Send CC 123 (all notes off) on all 16 MIDI channels.
        Prevents stuck notes in Ableton when a tab is deactivated.
        """
        sink = None
        if tab_name == "Single Breath":
            sink = getattr(self._runtime, "midi", None)
        elif tab_name in ("Every Breath", "Group Breath") and self._eb_hub is not None:
            sink = self._eb_hub._midi_sink
        elif tab_name == "Breath Beat" and self._bb_hub is not None:
            sink = self._bb_hub._midi_sink
        if sink is None:
            return
        for ch in range(16):
            try:
                sink.send_cc(ch, 123, 0)
            except Exception:
                pass

    # ── UI sync ───────────────────────────────────────────────────────────────

    def _update_circles(self) -> None:
        """Swap each circle button's theme to reflect the current active state."""
        for name, tag in _CIRCLE_TAGS.items():
            if not dpg.does_item_exist(tag):
                continue
            if name == "Single Breath":
                active = self._active_sb
            else:
                active = (self._active_8001 == name)
            theme = "theme_circle_yellow" if active else "theme_circle_gray"
            dpg.bind_item_theme(tag, theme)
