from __future__ import annotations

from abc import ABC, abstractmethod


class MidiSink(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def send_note_on(self, channel: int, note: int, velocity: int) -> None: ...

    @abstractmethod
    def send_note_off(self, channel: int, note: int, velocity: int = 0) -> None: ...

    @abstractmethod
    def send_cc(self, channel: int, cc: int, value: int) -> None: ...

