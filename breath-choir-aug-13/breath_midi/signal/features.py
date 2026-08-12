from __future__ import annotations

from collections import deque
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

        # Rolling (t, amp) window used for hold detection, cleared on every
        # phase change so a hold must be established within the current phase.
        # See _held_flat() for why this measures amplitude, not slope.
        self._amp_window: deque[tuple[float, float]] = deque()

        # Amplitude at the moment HOLD latched.  The hold is measured against
        # this, not against the moving signal, so upstream renormalisation
        # drift cannot end it.  None whenever the phase is not HOLD.
        self._hold_latch_amp: float | None = None

        # cycle tracking
        self._cycle_anchored: bool = False
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

        # Hold-detection window.  Keep one sample at or before the boundary so
        # the span can be measured exactly, and drop anything older.
        self._amp_window.append((t, amp))
        window_s = self._hold_window_s()
        while len(self._amp_window) >= 2 and self._amp_window[1][0] <= (t - window_s):
            self._amp_window.popleft()

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

        # A cycle runs from one inhale onset to the next, so it can only be
        # measured once an inhale has actually been seen.  The cycle clock is
        # started at the first sample (see above), which is not an inhale — the
        # first onset therefore only anchors the cycle rather than completing
        # one.  Without this the first "cycle" reports a period of a single
        # sample and that value pollutes the rolling average the
        # consistent-breaths gate reads.
        if phase_changed and phase_next == Phase.INHALE and self._cycle_start_t is not None:
            if self._cycle_anchored:
                period = max(1e-6, t - self._cycle_start_t)
                cycle = CycleMetrics(period_s=period, peak_amp=float(self._cycle_peak))
                self._last_cycle = cycle
                cycle_completed = True

                self._avg_period.update(period)
                self._avg_peak.update(cycle.peak_amp)

            self._cycle_anchored = True
            self._cycle_start_t = t
            self._cycle_peak = amp

        if phase_changed:
            self._phase = phase_next
            self._phase_enter_t = t
            # Anchor the hold where it started, and drop the anchor on the way
            # out so the next hold measures from its own starting point.
            self._hold_latch_amp = amp if phase_next == Phase.HOLD else None
            # NOTE: the hold window is deliberately *not* cleared here.  It used
            # to be, to stop one phase's samples bleeding into the next — but
            # that made holds impossible to detect on real data: noise makes the
            # phase flip between inhale and exhale while the performer sits
            # still, and each flip reset the window before it could ever
            # accumulate min_hold_ms.  The band test and hold_exit_delta already
            # prevent the bleed-through that clearing was there to stop.

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

    def _hold_window_s(self) -> float:
        return max(0.0, float(self.cfg.min_hold_ms) / 1000.0)

    def _held_flat(self) -> bool:
        """
        True when the breath has sat inside the peak or valley band, barely
        moving, for a full min_hold_ms window.

        Two conditions, and both matter:

        *Stillness* is measured as amplitude excursion over the window rather
        than as a small derivative.  The derivative is EMA-smoothed, so it
        lags — after a two-second inhale the smoothed slope needs roughly
        300ms to decay below any flat threshold, which would silently shorten
        every detected hold and make short ones undetectable.  Excursion is
        also just what "holding your breath" means.

        *Position* is what makes a hold deliberate.  Requiring the breath to be
        near the top or the bottom of its range rejects a hesitation halfway
        up an inhale, which the earlier arrival-phase rule wrongly accepted.
        The incoming value is already normalised per device upstream, so these
        bands adapt to each performer without extra machinery.
        """
        cfg = self.cfg
        if not cfg.hold_enabled:
            return False

        # No holds until a full breath cycle has been seen.  The bands are
        # positions within the performer's range, and until they have breathed
        # in and out once there is no range to speak of — upstream min/max
        # normalisation reports exactly 1.0 while its buffer fills, because the
        # newest sample *is* the running maximum.  That is perfectly still and
        # sits in the peak band, so without this guard the first breath of
        # every session latches a hold.
        if self._last_cycle is None:
            return False

        window_s = self._hold_window_s()
        if window_s <= 0.0 or len(self._amp_window) < 2:
            return False

        t_now = self._amp_window[-1][0]
        # The window must actually span min_hold_ms — otherwise we would call a
        # hold the moment a phase begins, before there is evidence either way.
        if (t_now - self._amp_window[0][0]) < window_s:
            return False

        amps = [a for _, a in self._amp_window]
        if (max(amps) - min(amps)) > max(0.0, float(cfg.hold_still_tol)):
            return False

        # Judge position on the whole window, not just the latest sample, so a
        # single noisy spike out of the band cannot cancel a genuine hold.
        mid = (max(amps) + min(amps)) / 2.0
        return mid >= float(cfg.hold_peak_band) or mid <= float(cfg.hold_valley_band)

    def _next_phase(self, amp: float, d_amp: float, current: Phase) -> Phase:
        cfg = self.cfg

        h = float(cfg.hysteresis)
        slope_enter_abs = max(0.0, float(cfg.slope_enter_abs))

        slope_enter = slope_enter_abs + h

        is_rising_enter = d_amp >= slope_enter
        is_falling_enter = d_amp <= -slope_enter

        t_now = self._last_t
        held_flat = self._held_flat()

        min_phase_s = max(0.0, float(cfg.min_phase_ms) / 1000.0)
        if self._phase_enter_t is not None and t_now is not None:
            if (t_now - self._phase_enter_t) < min_phase_s:
                return current

        # One HOLD state, entered from either end of the breath.  _held_flat()
        # already required the band, so reaching here means the pause is at the
        # top or the bottom rather than mid-breath.
        if current == Phase.REST:
            if is_rising_enter:
                return Phase.INHALE
            if is_falling_enter:
                return Phase.EXHALE
            return Phase.REST

        if current == Phase.INHALE:
            if is_falling_enter:
                return Phase.EXHALE
            if held_flat:
                return Phase.HOLD
            return Phase.INHALE

        if current == Phase.EXHALE:
            if is_rising_enter:
                return Phase.INHALE
            if held_flat:
                return Phase.HOLD
            return Phase.EXHALE

        if current == Phase.HOLD:
            # A latched hold is broken by displacement, not by slope.  See
            # DetectionConfig.hold_exit_delta: rolling renormalisation makes a
            # still breath drift, and that drift has enough slope to look like
            # a new phase.  It does not have enough travel.
            if self._hold_latch_amp is None:
                self._hold_latch_amp = amp
            moved = amp - self._hold_latch_amp
            if abs(moved) >= max(0.0, float(cfg.hold_exit_delta)):
                return Phase.INHALE if moved > 0 else Phase.EXHALE
            return Phase.HOLD

        return Phase.REST

