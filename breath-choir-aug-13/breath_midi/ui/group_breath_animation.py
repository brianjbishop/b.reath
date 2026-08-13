from __future__ import annotations

import dearpygui.dearpygui as dpg

_MIN_R: float = 20.0
_MAX_R: float = 90.0
_CANVAS_W: int = 200
_CANVAS_H: int = 200
_CENTER: tuple[float, float] = (100.0, 100.0)

_COLOR_INHALE = (100, 180, 255, 220)
_COLOR_EXHALE = (255, 140, 80, 220)
_COLOR_STOPPED = (60, 60, 60, 220)


class GroupBreathAnimation:
    """
    Self-contained breath guide animation panel.

    Renders a pulsing circle that grows on inhale and shrinks on exhale,
    driven entirely by an internal timer updated via update(dt).
    No OSC data, no MIDI output.

    build() must be called once inside an active DPG context.
    update(dt) is called every frame with delta time in seconds.
    stop() resets the circle and can be called externally (e.g. on tab toggle off).
    """

    def __init__(self) -> None:
        self._bpm: float = 60.0
        self._inhale_beats: int = 4
        self._exhale_beats: int = 4
        self._running: bool = False
        self._phase: str = "inhale"   # "inhale" | "exhale"
        self._phase_t: float = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build all DPG widgets.  Called once inside the parent context."""
        dpg.add_spacer(height=4)

        # ── Pulsing circle ────────────────────────────────────────────────────
        with dpg.drawlist(
            tag="gb_anim_drawlist",
            width=_CANVAS_W,
            height=_CANVAS_H,
        ):
            dpg.draw_circle(
                center=_CENTER,
                radius=_MIN_R,
                color=_COLOR_STOPPED,
                fill=_COLOR_STOPPED,
                tag="gb_anim_circle",
            )

        # Phase label (inhale / exhale)
        dpg.add_text("", tag="gb_anim_phase_label", color=(180, 180, 180))

        dpg.add_spacer(height=12)
        dpg.add_separator()
        dpg.add_spacer(height=8)

        # ── BPM controls ──────────────────────────────────────────────────────
        dpg.add_text("BPM", color=(160, 160, 160))
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="-",
                tag="gb_anim_bpm_minus",
                width=24,
                callback=self._on_bpm_minus,
            )
            dpg.add_input_int(
                tag="gb_anim_bpm",
                default_value=int(self._bpm),
                min_value=20,
                max_value=240,
                step=0,
                width=60,
                on_enter=True,
                callback=self._on_bpm_change,
            )
            dpg.add_button(
                label="+",
                tag="gb_anim_bpm_plus",
                width=24,
                callback=self._on_bpm_plus,
            )

        dpg.add_spacer(height=8)

        # ── Beat counts ───────────────────────────────────────────────────────
        with dpg.group(horizontal=True):
            dpg.add_text("In beats:")
            dpg.add_input_int(
                tag="gb_anim_inhale_beats",
                default_value=self._inhale_beats,
                min_value=1,
                max_value=16,
                step=0,
                width=50,
                on_enter=True,
                callback=self._on_inhale_beats_change,
            )

        with dpg.group(horizontal=True):
            dpg.add_text("Ex beats:")
            dpg.add_input_int(
                tag="gb_anim_exhale_beats",
                default_value=self._exhale_beats,
                min_value=1,
                max_value=16,
                step=0,
                width=50,
                on_enter=True,
                callback=self._on_exhale_beats_change,
            )

        dpg.add_spacer(height=12)

        # ── Start / Stop ──────────────────────────────────────────────────────
        dpg.add_button(
            label="Start",
            tag="gb_anim_start_stop",
            width=-1,
            callback=self._on_start_stop,
        )

    # ── per-frame update ──────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        """Advance animation by dt seconds.  No-op when stopped."""
        if not self._running:
            return

        bpm = max(20.0, self._bpm)
        spb = 60.0 / bpm  # seconds per beat
        inh_dur = spb * self._inhale_beats
        exh_dur = spb * self._exhale_beats

        self._phase_t += dt

        # Drain complete phase durations (handles any dt size safely)
        while True:
            dur = inh_dur if self._phase == "inhale" else exh_dur
            if self._phase_t < dur:
                break
            self._phase_t -= dur
            self._phase = "exhale" if self._phase == "inhale" else "inhale"

        # Compute interpolation fraction and radius
        dur = inh_dur if self._phase == "inhale" else exh_dur
        raw = (self._phase_t / dur) if dur > 0.0 else 0.0
        t_frac = raw if self._phase == "inhale" else (1.0 - raw)
        radius = _MIN_R + t_frac * (_MAX_R - _MIN_R)

        self._update_circle(radius)

        if dpg.does_item_exist("gb_anim_phase_label"):
            dpg.set_value("gb_anim_phase_label", self._phase)

    # ── public control ────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Stop the animation and reset to resting state."""
        self._running = False
        self._phase = "inhale"
        self._phase_t = 0.0
        self._update_circle(_MIN_R, stopped=True)
        if dpg.does_item_exist("gb_anim_phase_label"):
            dpg.set_value("gb_anim_phase_label", "")
        if dpg.does_item_exist("gb_anim_start_stop"):
            dpg.configure_item("gb_anim_start_stop", label="Start")

    # ── private helpers ───────────────────────────────────────────────────────

    def _update_circle(self, radius: float, stopped: bool = False) -> None:
        if not dpg.does_item_exist("gb_anim_circle"):
            return
        if stopped:
            color = _COLOR_STOPPED
        elif self._phase == "inhale":
            color = _COLOR_INHALE
        else:
            color = _COLOR_EXHALE
        dpg.configure_item("gb_anim_circle", radius=radius, fill=color, color=color)

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _on_bpm_minus(self) -> None:
        self._bpm = max(20.0, self._bpm - 1.0)
        if dpg.does_item_exist("gb_anim_bpm"):
            dpg.set_value("gb_anim_bpm", int(round(self._bpm)))

    def _on_bpm_plus(self) -> None:
        self._bpm = min(240.0, self._bpm + 1.0)
        if dpg.does_item_exist("gb_anim_bpm"):
            dpg.set_value("gb_anim_bpm", int(round(self._bpm)))

    def _on_bpm_change(self, sender, app_data, user_data) -> None:
        self._bpm = float(max(20, min(240, int(app_data))))

    def _on_inhale_beats_change(self, sender, app_data, user_data) -> None:
        self._inhale_beats = max(1, min(16, int(app_data)))

    def _on_exhale_beats_change(self, sender, app_data, user_data) -> None:
        self._exhale_beats = max(1, min(16, int(app_data)))

    def _on_start_stop(self) -> None:
        if self._running:
            self.stop()
        else:
            self._running = True
            self._phase = "inhale"
            self._phase_t = 0.0
            if dpg.does_item_exist("gb_anim_start_stop"):
                dpg.configure_item("gb_anim_start_stop", label="Stop")
