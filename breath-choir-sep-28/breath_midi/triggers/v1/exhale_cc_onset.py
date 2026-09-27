from __future__ import annotations

from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, Phase, TriggerEvent, TriggerKind


class ExhaleCcOnsetTrigger(TriggerStrategy):
    """
    Fires a single CC message on exhale phase entry.

    One shot on phase transition — not continuous.
    Debounced using the same debounce_ms as exhale_onset.
    CC number and value are mutable at runtime via set_cc().
    """

    id = "exhale_cc_onset"
    display_name = "Exhale CC onset"

    def __init__(self, cc_number: int = 2, cc_value: int = 127) -> None:
        self._cc_number = cc_number
        self._cc_value = cc_value

    def set_cc(self, cc_number: int, cc_value: int) -> None:
        """Update CC number and value — safe to call from UI thread under DeviceRuntime lock."""
        self._cc_number = cc_number
        self._cc_value = cc_value

    def on_frame(self, frame: FeatureFrame, ctx: TriggerContext) -> list[TriggerEvent]:
        # Reuse exhale_onset config for enabled flag and debounce_ms.
        cfg = ctx.config.triggers.exhale_onset
        if not cfg.enabled:
            return []
        if not frame.phase_changed or frame.phase_entered != Phase.EXHALE:
            return []

        key = "exhale_cc_onset_last_t"
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
