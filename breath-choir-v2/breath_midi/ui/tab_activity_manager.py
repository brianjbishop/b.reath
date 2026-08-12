from __future__ import annotations

import dearpygui.dearpygui as dpg

# DPG tags for the three circle buttons — must match what _build() creates.
_CIRCLE_TAGS: dict[str, str] = {
    "Single Breath": "circle_single",
    "Every Breath":  "circle_every",
    "Group Breath":  "circle_group",
}


class TabActivityManager:
    """
    Mutual-exclusion toggle for per-tab process lifecycle.

    Tracks which tab is currently active (if any) and enforces the rule
    that only one tab may be active at a time.  The circles in the UI
    are the only way to activate or deactivate a tab — navigating the
    tab bar has no effect on this state.
    """

    def __init__(self, runtime, eb_hub) -> None:
        self._runtime = runtime
        self._eb_hub = eb_hub
        self._active: str | None = None   # None = all tabs off

    # ── public API ────────────────────────────────────────────────────────────

    def toggle(self, tab_name: str) -> None:
        """Called by a circle button click.  Activates or deactivates the tab."""
        if self._active == tab_name:
            self._deactivate(tab_name)
        else:
            if self._active is not None:
                self._deactivate(self._active)
            self._activate(tab_name)

    @property
    def active_tab(self) -> str | None:
        return self._active

    # ── private lifecycle ─────────────────────────────────────────────────────

    def _activate(self, tab_name: str) -> None:
        if tab_name == "Single Breath":
            self._runtime.start()
        elif tab_name in ("Every Breath", "Group Breath") and self._eb_hub is not None:
            out_port = self._runtime.config.midi.out_port.strip() or None
            self._eb_hub.start_listening(out_port)
        self._active = tab_name
        self._update_circles()

    def _deactivate(self, tab_name: str) -> None:
        self._send_all_notes_off(tab_name)
        if tab_name == "Single Breath":
            self._runtime.stop()
        elif tab_name in ("Every Breath", "Group Breath") and self._eb_hub is not None:
            # Mutual exclusion guarantees the other hub-sharing tab is already
            # inactive, so stopping the listener here is always safe.
            self._eb_hub.stop_listening()
        self._active = None
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
            theme = (
                "theme_circle_yellow"
                if self._active == name
                else "theme_circle_gray"
            )
            dpg.bind_item_theme(tag, theme)
