from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from breath_midi.config.model import ConfigModel
from breath_midi.types import FeatureFrame, TriggerEvent


@dataclass
class TriggerContext:
    config: ConfigModel
    state: dict[str, Any] = field(default_factory=dict)


class TriggerStrategy(ABC):
    id: str
    display_name: str

    @abstractmethod
    def on_frame(self, frame: FeatureFrame, ctx: TriggerContext) -> list[TriggerEvent]: ...

