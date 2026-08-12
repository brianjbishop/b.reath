from __future__ import annotations

from dataclasses import dataclass

from breath_midi.config.model import SignalConfig
from breath_midi.types import BreathSample, ProcessedSample


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


class SignalProcessor:
    def __init__(self, cfg: SignalConfig):
        self.cfg = cfg
        self._smooth = _Ema(alpha=float(cfg.smoothing_alpha))
        self._baseline = _Ema(alpha=float(cfg.baseline_alpha)) if cfg.baseline_enabled else None

    def update_config(self, cfg: SignalConfig) -> None:
        self.cfg = cfg
        self._smooth.alpha = float(cfg.smoothing_alpha)
        if cfg.baseline_enabled:
            if self._baseline is None:
                self._baseline = _Ema(alpha=float(cfg.baseline_alpha))
            else:
                self._baseline.alpha = float(cfg.baseline_alpha)
        else:
            self._baseline = None

    def process(self, sample: BreathSample) -> ProcessedSample:
        amp_raw = float(sample.amp)
        amp = amp_raw * float(self.cfg.gain)

        # In TOTEM, the upstream app already sends a computed breath value in [0,1].
        # Keep processing "viewer-like": optional smoothing + gentle noise shaping,
        # but avoid high-pass style baseline subtraction that turns the waveform into pulses.
        amp = self._smooth.update(amp)
        if self._baseline is not None:
            # Still track baseline for potential future use / diagnostics,
            # but do not subtract it from the signal.
            _ = self._baseline.update(amp)

        dz = float(self.cfg.deadzone)
        if dz > 0.0 and 0.0 <= amp < dz:
            # Soft deadzone (continuous): compress small amplitudes instead of hard-zeroing.
            amp = (amp * amp) / dz

        # Normalize / clamp to [0,1] for v1
        if amp < 0.0:
            amp = 0.0
        if amp > 1.0:
            amp = 1.0

        return ProcessedSample(
            t=float(sample.t),
            amp_raw=amp_raw,
            amp_proc=float(amp),
            source_id=sample.source_id,
        )

