from __future__ import annotations

from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, Phase, TriggerEvent, TriggerKind


class _HoldCcOnsetTrigger(TriggerStrategy):
    """
    Fires a single CC message on entry to a hold phase.

    One shot on phase transition — not continuous.  Reuses the matching hold
    onset config for its enabled flag and debounce_ms, exactly as the inhale and
    exhale CC triggers reuse theirs.
    """

    phase: Phase
    config_key: str

    def __init__(self, cc_number: int = 1, cc_value: int = 127) -> None:
        self._cc_number = cc_number
        self._cc_value = cc_value

    def set_cc(self, cc_number: int, cc_value: int) -> None:
        """Update CC number and value — safe to call from UI thread under DeviceRuntime lock."""
        self._cc_number = cc_number
        self._cc_value = cc_value

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
                kind=TriggerKind.CC,
                t=frame.t,
                value=self._cc_value,
                meta={"cc": self._cc_number},
            )
        ]


class HoldFullCcOnsetTrigger(_HoldCcOnsetTrigger):
    id = "hold_full_cc_onset"
    display_name = "Hold (full) CC onset"
    phase = Phase.HOLD_FULL
    config_key = "hold_full_onset"


class HoldEmptyCcOnsetTrigger(_HoldCcOnsetTrigger):
    id = "hold_empty_cc_onset"
    display_name = "Hold (empty) CC onset"
    phase = Phase.HOLD_EMPTY
    config_key = "hold_empty_onset"
