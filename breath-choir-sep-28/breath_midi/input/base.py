from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from breath_midi.types import BreathSample


SampleCallback = Callable[[BreathSample], None]


class BreathInputSource(ABC):
    @abstractmethod
    def start(self, callback: SampleCallback) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

