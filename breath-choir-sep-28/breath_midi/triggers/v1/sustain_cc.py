from __future__ import annotations

import math

from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, Phase, TriggerEvent, TriggerKind


def _apply_curve(x01: float, kind: str, gamma: float) -> float:
    x01 = 0.0 if x01 < 0.0 else 1.0 if x01 > 1.0 else x01
    if kind == "linear":
        return x01
    if kind == "gamma":
        g = max(1e-3, float(gamma))
        return math.pow(x01, g)
    return x01


class _SustainCcBase(TriggerStrategy):
    phase: Phase

    def _cc_params(self, ctx: TriggerContext) -> tuple[bool, int, int, int, str, float]:
        raise NotImplementedError

    def on_frame(self, frame: FeatureFrame, ctx: TriggerContext) -> list[TriggerEvent]:
        enabled, cc, vmin, vmax, curve_kind, curve_gamma = self._cc_params(ctx)
        if not enabled:
            return []
        if frame.phase != self.phase:
            return []

        # rate limit (use midi.cc_rate_hz)
        min_dt = 1.0 / max(1.0, float(ctx.config.midi.cc_rate_hz))
        key = f"{self.id}_last_cc_t"
        last = ctx.state.get(key)
        if isinstance(last, (int, float)) and (frame.t - float(last)) < min_dt:
            return []
        ctx.state[key] = frame.t

        x = _apply_curve(frame.amp, curve_kind, curve_gamma)
        value = int(round(vmin + x * (vmax - vmin)))
        if value < 0:
            value = 0
        if value > 127:
            value = 127

        return [
            TriggerEvent(
                name=self.id,
                kind=TriggerKind.CC,
                t=frame.t,
                value=value,
                meta={"cc": cc},
            )
        ]


class InhaleSustainCcTrigger(_SustainCcBase):
    id = "inhale_sustain"
    display_name = "Inhale sustain (CC)"
    phase = Phase.INHALE

    def _cc_params(self, ctx: TriggerContext):
        c = ctx.config.triggers.inhale_sustain
        return (c.enabled, int(c.cc), int(c.min_value), int(c.max_value), c.curve_kind, float(c.curve_gamma))


class ExhaleSustainCcTrigger(_SustainCcBase):
    id = "exhale_sustain"
    display_name = "Exhale sustain (CC)"
    phase = Phase.EXHALE

    def _cc_params(self, ctx: TriggerContext):
        c = ctx.config.triggers.exhale_sustain
        return (c.enabled, int(c.cc), int(c.min_value), int(c.max_value), c.curve_kind, float(c.curve_gamma))

