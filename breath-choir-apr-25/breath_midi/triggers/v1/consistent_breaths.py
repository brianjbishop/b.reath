from __future__ import annotations

from breath_midi.triggers.base import TriggerContext, TriggerStrategy
from breath_midi.types import FeatureFrame, TriggerEvent, TriggerKind


def _within_tol(value: float, avg: float, kind: str, tol: float) -> bool:
    if avg <= 0:
        return False
    if kind == "relative":
        return abs(value - avg) <= abs(tol) * avg
    return abs(value - avg) <= abs(tol)


class ConsistentBreathsTrigger(TriggerStrategy):
    id = "consistent_breaths"
    display_name = "N consistent breaths"

    def on_frame(self, frame: FeatureFrame, ctx: TriggerContext) -> list[TriggerEvent]:
        cfg = ctx.config.triggers.consistent_breaths
        ctx.state["consistent_target"] = int(cfg.n)
        held_key = "consistent_key_held"
        held = bool(ctx.state.get(held_key, False))
        if not cfg.enabled:
            if held:
                ctx.state[held_key] = False
                ctx.state["consistent_streak"] = 0
                return [
                    TriggerEvent(
                        name=self.id,
                        kind=TriggerKind.NOTE_OFF,
                        t=frame.t,
                        value=0,
                        meta={"note": int(cfg.note), "n": int(cfg.n)},
                    )
                ]
            return []
        if not frame.cycle_completed or frame.cycle is None:
            return []

        avg_period = frame.rolling.avg_period_s
        avg_peak = frame.rolling.avg_peak_amp
        if avg_period is None or avg_peak is None:
            return []

        # Wait for a few cycles so averages are meaningful
        cycles_seen = int(ctx.state.get("consistent_cycles_seen", 0))
        cycles_seen += 1
        ctx.state["consistent_cycles_seen"] = cycles_seen
        if cycles_seen < int(cfg.min_cycles_before_eval):
            return []

        ok_period = _within_tol(
            value=float(frame.cycle.period_s),
            avg=float(avg_period),
            kind=str(cfg.period_tol_kind),
            tol=float(cfg.period_tol_value),
        )
        ok_peak = _within_tol(
            value=float(frame.cycle.peak_amp),
            avg=float(avg_peak),
            kind=str(cfg.peak_tol_kind),
            tol=float(cfg.peak_tol_value),
        )

        streak = int(ctx.state.get("consistent_streak", 0))
        if ok_period and ok_peak:
            streak += 1
        else:
            streak = 0
        ctx.state["consistent_streak"] = streak
        ctx.state["consistent_target"] = int(cfg.n)

        if streak >= int(cfg.n):
            if held:
                return []
            ctx.state[held_key] = True
            return [
                TriggerEvent(
                    name=self.id,
                    kind=TriggerKind.NOTE_ON,
                    t=frame.t,
                    value=int(cfg.velocity),
                    meta={"note": int(cfg.note), "n": int(cfg.n)},
                )
            ]
        if held:
            ctx.state[held_key] = False
            return [
                TriggerEvent(
                    name=self.id,
                    kind=TriggerKind.NOTE_OFF,
                    t=frame.t,
                    value=0,
                    meta={"note": int(cfg.note), "n": int(cfg.n)},
                )
            ]
        return []

