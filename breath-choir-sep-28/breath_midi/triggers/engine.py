from __future__ import annotations

import time
from dataclasses import dataclass

from breath_midi.config.model import ConfigModel
from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, TriggerEvent


@dataclass
class StrategyEntry:
    strategy: TriggerStrategy
    enabled: bool = True


class TriggerEngine:
    def __init__(self, cfg: ConfigModel, strategies: list[TriggerStrategy]):
        self.cfg = cfg
        self._ctx = TriggerContext(config=cfg)
        self._entries = [StrategyEntry(strategy=s, enabled=True) for s in strategies]

    def update_config(self, cfg: ConfigModel) -> None:
        self.cfg = cfg
        self._ctx.config = cfg

    def on_frame(self, frame: FeatureFrame) -> list[TriggerEvent]:
        events: list[TriggerEvent] = []
        for entry in self._entries:
            if not entry.enabled:
                continue
            try:
                events.extend(entry.strategy.on_frame(frame, self._ctx))
            except Exception:
                # v1: keep engine resilient; UI can show missing triggers later
                continue
        # Keep a small rolling list for UI
        now = time.monotonic()
        self._ctx.state.setdefault("_recent", [])
        recent: list[TriggerEvent] = self._ctx.state["_recent"]
        recent.extend(events)
        # prune > 2s old
        self._ctx.state["_recent"] = [e for e in recent if (now - e.t) <= 2.0]  # type: ignore[operator]
        return events

    def recent_events(self) -> list[TriggerEvent]:
        recent = self._ctx.state.get("_recent", [])
        if isinstance(recent, list):
            return list(recent)
        return []

    def consistent_status(self) -> tuple[int, int, bool]:
        streak = int(self._ctx.state.get("consistent_streak", 0))
        target = int(self._ctx.state.get("consistent_target", 0))
        held = bool(self._ctx.state.get("consistent_key_held", False))
        return (streak, target, held)

