from __future__ import annotations

from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, Phase, TriggerEvent, TriggerKind


class HoldOnsetTrigger(TriggerStrategy):
    """
    Fires a note when the FSM latches a hold.

    Note 0 means silent — the hold still happens, it just plays nothing. In the
    multi-device path the note lifecycle is owned by BreathVoice instead; this
    strategy is what Single Breath uses.
    """

    id = "hold_onset"
    display_name = "Hold onset"

    def on_frame(self, frame: FeatureFrame, ctx: TriggerContext) -> list[TriggerEvent]:
        cfg = ctx.config.triggers.hold_onset
        if not cfg.enabled or int(cfg.note) == 0:
            return []
        if not frame.phase_changed or frame.phase_entered != Phase.HOLD:
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
