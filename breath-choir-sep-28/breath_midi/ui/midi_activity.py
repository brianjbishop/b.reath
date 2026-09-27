from __future__ import annotations

import dearpygui.dearpygui as dpg

from breath_midi.config.model import ConfigModel
from breath_midi.midi.activity_bus import MidiActivityEvent


def key_trigger_specs(cfg: ConfigModel) -> list[tuple[str, str, int]]:
    """(row_id, label, note) for enabled key triggers, stable order."""
    t = cfg.triggers
    rows: list[tuple[str, str, int]] = []
    if t.inhale_onset.enabled:
        rows.append(("inhale_onset", "Inhale", int(t.inhale_onset.note)))
    if t.exhale_onset.enabled:
        rows.append(("exhale_onset", "Exhale", int(t.exhale_onset.note)))
    if t.consistent_breaths.enabled:
        rows.append(
            ("consistent_breaths", "Consistent Breaths", int(t.consistent_breaths.note))
        )
    return rows


def sustain_cc_specs(cfg: ConfigModel) -> list[tuple[str, str, int]]:
    """(row_id, label, cc_number) for enabled sustain rows."""
    t = cfg.triggers
    rows: list[tuple[str, str, int]] = []
    if t.inhale_sustain.enabled:
        rows.append(("inhale_sustain", "Inhale Sustain", int(t.inhale_sustain.cc)))
    if t.exhale_sustain.enabled:
        rows.append(("exhale_sustain", "Exhale Sustain", int(t.exhale_sustain.cc)))
    return rows


def labels_for_note(cfg: ConfigModel, channel: int, note: int) -> str | None:
    if int(channel) != int(cfg.midi.channel):
        return None
    labels = [lab for _rid, lab, n in key_trigger_specs(cfg) if int(n) == int(note)]
    if not labels:
        return None
    return ", ".join(labels)


def _note_display(cfg: ConfigModel, note: int) -> str:
    if cfg.ui.midi_activity.show_note_name:
        names = (
            "C",
            "C#",
            "D",
            "D#",
            "E",
            "F",
            "F#",
            "G",
            "G#",
            "A",
            "A#",
            "B",
        )
        o = note // 12 - 1
        return f"{note} ({names[note % 12]}{o})"
    return str(int(note))


class MidiActivityVisualizer:
    """Dear PyGui MIDI key/CC activity strip; state from MidiActivityEvent + ConfigModel."""

    def __init__(self, parent: int | str) -> None:
        self._parent = parent
        self._cfg: ConfigModel | None = None
        self._row_ids: list[str] = []
        self._cc_row_ids: list[str] = []
        self._held: set[str] = set()
        self._velocity: dict[str, int] = {}
        self._cc_value: dict[str, int] = {}
        self._theme_dim: int | str = 0
        self._theme_lit: int | str = 0

    def sync_config(self, cfg: ConfigModel) -> None:
        ma = cfg.ui.midi_activity
        self._cfg = cfg

        for tname in ("midi_viz_theme_dim", "midi_viz_theme_lit"):
            if dpg.does_item_exist(tname):
                dpg.delete_item(tname)

        with dpg.theme(tag="midi_viz_theme_dim"):
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, ma.held_dim_rgba)
        with dpg.theme(tag="midi_viz_theme_lit"):
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, ma.held_lit_rgba)
        self._theme_dim = "midi_viz_theme_dim"
        self._theme_lit = "midi_viz_theme_lit"

        ch = dpg.get_item_children(self._parent, slot=1)
        if ch:
            for c in list(ch):
                dpg.delete_item(c)

        self._row_ids = []
        self._cc_row_ids = []
        self._held.clear()
        self._velocity.clear()
        self._cc_value.clear()

        specs = key_trigger_specs(cfg)
        cc_specs = sustain_cc_specs(cfg)
        led_h = max(18, ma.velocity_bar_h + 10)

        for rid, label, note in specs:
            self._row_ids.append(rid)
            with dpg.group(horizontal=True, parent=self._parent):
                with dpg.group(width=120):
                    dpg.add_text(label)
                with dpg.group(width=92):
                    dpg.add_text(_note_display(cfg, note), tag=f"midi_viz_note_{rid}")
                led = dpg.add_child_window(
                    width=22,
                    height=led_h,
                    border=True,
                    no_scrollbar=True,
                    tag=f"midi_viz_led_{rid}",
                )
                dpg.bind_item_theme(led, self._theme_dim)
                dpg.add_progress_bar(
                    default_value=0.0,
                    width=120,
                    height=ma.velocity_bar_h,
                    tag=f"midi_viz_vel_{rid}",
                )

        if cc_specs:
            dpg.add_spacer(height=6, parent=self._parent)
            dpg.add_text("Sustain CC", color=(180, 180, 180), parent=self._parent)
            for rid, label, _cc in cc_specs:
                self._cc_row_ids.append(rid)
                self._cc_value[rid] = 0
                with dpg.group(horizontal=True, parent=self._parent):
                    with dpg.group(width=120):
                        dpg.add_text(label)
                    dpg.add_progress_bar(
                        default_value=0.0,
                        width=-1,
                        height=ma.cc_bar_h,
                        tag=f"midi_viz_cc_{rid}",
                    )

    def process_events(self, events: list[MidiActivityEvent], cfg: ConfigModel) -> None:
        if not self._row_ids:
            return
        ch_midi = int(cfg.midi.channel)
        note_to_rids: dict[int, list[str]] = {}
        for rid, _lab, n in key_trigger_specs(cfg):
            note_to_rids.setdefault(int(n), []).append(rid)

        for e in events:
            if e.channel != ch_midi:
                continue
            if e.kind == "note_on" and e.note is not None and e.velocity is not None:
                for rid in note_to_rids.get(int(e.note), []):
                    self._held.add(rid)
                    self._velocity[rid] = int(e.velocity)
                    self._apply_row_ui(rid, cfg)
            elif e.kind == "note_off" and e.note is not None:
                for rid in note_to_rids.get(int(e.note), []):
                    self._held.discard(rid)
                    self._apply_row_ui(rid, cfg)
            elif e.kind == "control_change" and e.control is not None and e.value is not None:
                for rid, _lab, ccn in sustain_cc_specs(cfg):
                    if int(ccn) == int(e.control):
                        self._cc_value[rid] = int(e.value)
                        self._apply_cc_ui(rid, cfg)

    def _apply_row_ui(self, rid: str, _cfg: ConfigModel) -> None:
        led_tag = f"midi_viz_led_{rid}"
        vel_tag = f"midi_viz_vel_{rid}"
        if not dpg.does_item_exist(led_tag):
            return
        theme = self._theme_lit if rid in self._held else self._theme_dim
        dpg.bind_item_theme(led_tag, theme)
        v = self._velocity.get(rid, 0)
        dpg.set_value(vel_tag, min(1.0, max(0.0, v / 127.0)))

    def _apply_cc_ui(self, rid: str, _cfg: ConfigModel) -> None:
        tag = f"midi_viz_cc_{rid}"
        if not dpg.does_item_exist(tag):
            return
        v = self._cc_value.get(rid, 0)
        dpg.set_value(tag, min(1.0, max(0.0, v / 127.0)))

    def reset_state(self) -> None:
        self._held.clear()
        self._velocity.clear()
        for rid in self._cc_row_ids:
            self._cc_value[rid] = 0
        if self._cfg is None:
            return
        cfg = self._cfg
        for rid in self._row_ids:
            self._apply_row_ui(rid, cfg)
        for rid in self._cc_row_ids:
            self._apply_cc_ui(rid, cfg)
