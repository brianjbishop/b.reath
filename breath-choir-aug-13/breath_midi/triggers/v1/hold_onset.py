from __future__ import annotations

from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, Phase, TriggerEvent, TriggerKind


class _HoldOnsetTrigger(TriggerStrategy):
    """
    Fires a note on entry to a hold phase.

    Shared by the two holds because they differ only in which phase they watch
    and which config block they read — unlike inhale/exhale, which were written
    out separately before there was a second pair to share with.
    """

    phase: Phase
    config_key: str

    def on_frame(self, frame: FeatureFrame, ctx: TriggerContext) -> list[TriggerEvent]:
        cfg = getattr(ctx.config.triggers, self.config_key)
        if not cfg.enabled:
            return []
        if not frame.phase_changed or frame.phase_entered != self.phase:
            return []

        key = f"{self.id}_last_t"
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


class HoldFullOnsetTrigger(_HoldOnsetTrigger):
    id = "hold_full_onset"
    display_name = "Hold (full) onset"
    phase = Phase.HOLD_FULL
    config_key = "hold_full_onset"


class HoldEmptyOnsetTrigger(_HoldOnsetTrigger):
    id = "hold_empty_onset"
    display_name = "Hold (empty) onset"
    phase = Phase.HOLD_EMPTY
    config_key = "hold_empty_onset"
