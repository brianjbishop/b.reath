from __future__ import annotations

from dataclasses import dataclass

from breath_midi.config.model import DetectionConfig
from breath_midi.types import (
    CycleMetrics,
    FeatureFrame,
    Phase,
    ProcessedSample,
    RollingStats,
)


@dataclass
class _Ema:
    alpha: float
    y: float | None = None

    def update(self, x: float) -> float:
        if self.y is None:
            self.y = x
        else:
            self.y = self.alpha * x + (1.0 - self.alpha) * self.y
        return self.y


class FeatureExtractor:
    def __init__(self, cfg: DetectionConfig):
        self.cfg = cfg
        self._d_smooth = _Ema(alpha=float(cfg.derivative_smoothing_alpha))

        self._last_t: float | None = None
        self._last_amp: float | None = None

        self._phase: Phase = Phase.REST
        self._phase_enter_t: float | None = None

        # cycle tracking
        self._cycle_start_t: float | None = None
        self._cycle_peak: float = 0.0
        self._last_cycle: CycleMetrics | None = None

        # rolling stats
        self._avg_period = _Ema(alpha=0.2)
        self._avg_peak = _Ema(alpha=0.2)

    def update_config(self, cfg: DetectionConfig) -> None:
        self.cfg = cfg
        self._d_smooth.alpha = float(cfg.derivative_smoothing_alpha)

    def update(self, s: ProcessedSample) -> FeatureFrame:
        t = float(s.t)
        amp = float(s.amp_proc)

        d_amp = 0.0
        if self._last_t is not None and self._last_amp is not None:
            dt = max(1e-6, t - self._last_t)
            d_amp = (amp - self._last_amp) / dt
        if self.cfg.derivative_enabled:
            d_amp = self._d_smooth.update(d_amp)
        else:
            d_amp = 0.0

        self._last_t = t
        self._last_amp = amp

        # Update peak within current cycle
        if self._cycle_start_t is None:
            self._cycle_start_t = t
            self._cycle_peak = amp
        else:
            if amp > self._cycle_peak:
                self._cycle_peak = amp

        phase_prev = self._phase
        phase_next = self._next_phase(amp, float(d_amp), phase_prev)
        phase_changed = phase_next != phase_prev

        cycle_completed = False
        cycle: CycleMetrics | None = None

        # Detect cycle completion on inhale onset (REST/EXHALE -> INHALE)
        if phase_changed and phase_next == Phase.INHALE and self._cycle_start_t is not None:
            period = max(1e-6, t - self._cycle_start_t)
            cycle = CycleMetrics(period_s=period, peak_amp=float(self._cycle_peak))
            self._last_cycle = cycle
            cycle_completed = True
            self._cycle_start_t = t
            self._cycle_peak = amp

            self._avg_period.update(period)
            self._avg_peak.update(cycle.peak_amp)

        if phase_changed:
            self._phase = phase_next
            self._phase_enter_t = t

        rolling = RollingStats(
            avg_period_s=self._avg_period.y,
            avg_peak_amp=self._avg_peak.y,
        )

        return FeatureFrame(
            t=t,
            amp=amp,
            d_amp=float(d_amp),
            phase=self._phase,
            phase_changed=phase_changed,
            phase_entered=phase_next if phase_changed else None,
            cycle_completed=cycle_completed,
            cycle=cycle,
            rolling=rolling,
            source_id=s.source_id,
        )

    def _next_phase(self, amp: float, d_amp: float, current: Phase) -> Phase:
        cfg = self.cfg

        h = float(cfg.hysteresis)
        rest_enter = float(cfg.rest_enter_amp)
        slope_enter_abs = max(0.0, float(cfg.slope_enter_abs))
        slope_rest_abs = max(0.0, float(cfg.slope_rest_abs))

        min_phase_s = max(0.0, float(cfg.min_phase_ms) / 1000.0)
        if self._phase_enter_t is not None and self._last_t is not None:
            if (self._last_t - self._phase_enter_t) < min_phase_s:
                return current

        low_enter = max(0.0, rest_enter - h)
        low_stay = rest_enter + h
        flat_enter = max(0.0, slope_rest_abs - h)
        flat_stay = slope_rest_abs + h
        slope_enter = slope_enter_abs + h
        slope_stay = max(0.0, slope_enter_abs - h)

        is_low_enter = amp <= low_enter
        is_low_stay = amp <= low_stay
        is_flat_enter = abs(d_amp) <= flat_enter
        is_flat_stay = abs(d_amp) <= flat_stay
        is_rising_enter = d_amp >= slope_enter
        is_falling_enter = d_amp <= -slope_enter
        is_rising_stay = d_amp >= slope_stay
        is_falling_stay = d_amp <= -slope_stay

        if current == Phase.REST:
            if is_rising_enter:
                return Phase.INHALE
            if is_falling_enter:
                return Phase.EXHALE
            return Phase.REST

        if current == Phase.INHALE:
            if is_low_enter and is_flat_enter:
                return Phase.REST
            if is_falling_enter:
                return Phase.EXHALE
            if is_rising_stay:
                return Phase.INHALE
            if is_low_stay and is_flat_stay:
                return Phase.REST
            return Phase.INHALE

        if current == Phase.EXHALE:
            if is_low_enter and is_flat_enter:
                return Phase.REST
            if is_rising_enter:
                return Phase.INHALE
            if is_falling_stay:
                return Phase.EXHALE
            if is_low_stay and is_flat_stay:
                return Phase.REST
            return Phase.EXHALE

        return Phase.REST

