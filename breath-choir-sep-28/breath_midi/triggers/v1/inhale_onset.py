from __future__ import annotations

from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, Phase, TriggerEvent, TriggerKind


class InhaleOnsetTrigger(TriggerStrategy):
    id = "inhale_onset"
    display_name = "Inhale onset"

    def on_frame(self, frame: FeatureFrame, ctx: TriggerContext) -> list[TriggerEvent]:
        cfg = ctx.config.triggers.inhale_onset
        if not cfg.enabled:
            return []
        if not frame.phase_changed or frame.phase_entered != Phase.INHALE:
            return []

        key = "inhale_onset_last_t"
        last_t = ctx.state.get(key)
        if isinstance(last_t, (int, float)):
            if (frame.t - float(last_t)) * 1000.0 < float(cfg.debounce_ms):
                return []
        ctx.state[key] = frame.t

        return [
            TriggerEvent(
                name=self.id,
                kind=TriggerKind.NOTE_ON,
                t=frame.t,
                value=int(cfg.velocity),
                meta={"note": int(cfg.note)},
            )
        ]

