from __future__ import annotations

from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, Phase, TriggerEvent, TriggerKind


class HoldCcOnsetTrigger(TriggerStrategy):
    """
    Fires a single CC message when the FSM latches a hold.

    One shot on the transition, not continuous. Reuses the hold onset config for
    its enabled flag and debounce_ms, exactly as the inhale and exhale CC
    triggers reuse theirs.
    """

    id = "hold_cc_onset"
    display_name = "Hold CC onset"

    def __init__(self, cc_number: int = 1, cc_value: int = 127) -> None:
        self._cc_number = cc_number
        self._cc_value = cc_value

    def set_cc(self, cc_number: int, cc_value: int) -> None:
        """Update CC number and value — safe to call from UI thread under DeviceRuntime lock."""
        self._cc_number = cc_number
        self._cc_value = cc_value

    def on_frame(self, frame: FeatureFrame, ctx: TriggerContext) -> list[TriggerEvent]:
        cfg = ctx.config.triggers.hold_onset
        if not cfg.enabled or int(self._cc_number) == 0:
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
                kind=TriggerKind.CC,
                t=frame.t,
                value=self._cc_value,
                meta={"cc": self._cc_number},
            )
        ]
