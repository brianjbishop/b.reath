from __future__ import annotations

from dataclasses import dataclass

import mido
import time

from breath_midi.midi.activity_bus import MidiActivityBus, MidiActivityEvent
from breath_midi.midi.base import MidiSink


@dataclass
class MidiStatus:
    open: bool
    out_port_name: str


class MidoMidiSink(MidiSink):
    def __init__(
        self,
        activity_bus: MidiActivityBus | None = None,
        source_id: str = "local",
    ) -> None:
        self._port: mido.ports.BaseOutput | None = None
        self._port_name: str = ""
        self._activity_bus = activity_bus
        self._source_id = source_id

    def set_activity_source_id(self, source_id: str) -> None:
        self._source_id = str(source_id)

    def _emit(self, msg: mido.Message) -> None:
        bus = self._activity_bus
        if bus is None:
            return
        mono = time.monotonic()
        ch = int(getattr(msg, "channel", 0))
        if msg.type == "note_on":
            bus.publish(
                MidiActivityEvent(
                    kind="note_on",
                    channel=ch,
                    source_id=self._source_id,
                    mono_t=mono,
                    note=int(msg.note),
                    velocity=int(msg.velocity),
                )
            )
        elif msg.type == "note_off":
            bus.publish(
                MidiActivityEvent(
                    kind="note_off",
                    channel=ch,
                    source_id=self._source_id,
                    mono_t=mono,
                    note=int(msg.note),
                    velocity=int(msg.velocity),
                )
            )
        elif msg.type == "control_change":
            bus.publish(
                MidiActivityEvent(
                    kind="control_change",
                    channel=ch,
                    source_id=self._source_id,
                    mono_t=mono,
                    control=int(msg.control),
                    value=int(msg.value),
                )
            )

    @staticmethod
    def list_outputs() -> list[str]:
        try:
            return list(mido.get_output_names())
        except Exception:
            return []

    def open(self, out_port: str | None = None) -> None:  # type: ignore[override]
        if self._port is not None:
            return
        if out_port:
            self._port = mido.open_output(out_port)
            self._port_name = out_port
        else:
            self._port = mido.open_output()
            self._port_name = str(getattr(self._port, "name", ""))

    def close(self) -> None:
        if self._port is None:
            return
        try:
            for ch in range(16):
                m120 = mido.Message("control_change", channel=ch, control=120, value=0)
                m123 = mido.Message("control_change", channel=ch, control=123, value=0)
                self._port.send(m120)
                self._port.send(m123)
        except Exception:
            pass
        try:
            self._port.close()
        finally:
            self._port = None
            self._port_name = ""

    def status(self) -> MidiStatus:
        return MidiStatus(open=self._port is not None, out_port_name=self._port_name)

    def send_note_on(self, channel: int, note: int, velocity: int) -> None:
        if self._port is None:
            return
        msg = mido.Message(
            "note_on",
            channel=int(channel),
            note=int(note),
            velocity=int(velocity),
        )
        self._port.send(msg)
        self._emit(msg)

    def send_note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        if self._port is None:
            return
        msg = mido.Message(
            "note_off",
            channel=int(channel),
            note=int(note),
            velocity=int(velocity),
        )
        self._port.send(msg)
        self._emit(msg)

    def send_cc(self, channel: int, cc: int, value: int) -> None:
        if self._port is None:
            return
        msg = mido.Message(
            "control_change",
            channel=int(channel),
            control=int(cc),
            value=int(value),
        )
        self._port.send(msg)
        self._emit(msg)
