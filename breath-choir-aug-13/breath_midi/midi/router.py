from __future__ import annotations

from breath_midi.config.model import ConfigModel
from breath_midi.midi.base import MidiSink
from breath_midi.types import TriggerEvent, TriggerKind


class MidiRouter:
    def __init__(self, cfg: ConfigModel, midi: MidiSink):
        self.cfg = cfg
        self.midi = midi

    def update_config(self, cfg: ConfigModel) -> None:
        self.cfg = cfg

    def handle(self, event: TriggerEvent) -> None:
        ch = int(self.cfg.midi.channel)
        if event.kind == TriggerKind.NOTE_ON:
            note = int((event.meta or {}).get("note", 60))
            vel = int(event.value) if isinstance(event.value, (int, float)) else int(self.cfg.midi.default_velocity)
            if vel < 0:
                vel = 0
            if vel > 127:
                vel = 127
            self.midi.send_note_on(ch, note, vel)
            return

        if event.kind == TriggerKind.NOTE_OFF:
            note = int((event.meta or {}).get("note", 60))
            vel = int(event.value) if isinstance(event.value, (int, float)) else 0
            if vel < 0:
                vel = 0
            if vel > 127:
                vel = 127
            self.midi.send_note_off(ch, note, vel)
            return

        if event.kind == TriggerKind.CC:
            cc = int((event.meta or {}).get("cc", 1))
            value = int(event.value) if isinstance(event.value, (int, float)) else 0
            if value < 0:
                value = 0
            if value > 127:
                value = 127
            self.midi.send_cc(ch, cc, value)
            return

