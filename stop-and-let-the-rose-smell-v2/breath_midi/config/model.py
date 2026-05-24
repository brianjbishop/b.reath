from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InputConfig:
    mode: str
    osc_port: int
    source_filter: str
    ble_address: str
    ble_auto_connect: bool


@dataclass(frozen=True)
class SignalConfig:
    smoothing_kind: str
    smoothing_alpha: float
    baseline_enabled: bool
    baseline_alpha: float
    gain: float
    deadzone: float


@dataclass(frozen=True)
class DetectionConfig:
    derivative_enabled: bool
    derivative_smoothing_alpha: float
    inhale_enter_amp: float
    exhale_enter_amp: float
    rest_enter_amp: float
    slope_enter_abs: float
    slope_rest_abs: float
    hysteresis: float
    min_phase_ms: int


@dataclass(frozen=True)
class MidiConfig:
    out_port: str
    channel: int
    default_velocity: int
    cc_rate_hz: int


@dataclass(frozen=True)
class InhaleOnsetTriggerConfig:
    enabled: bool
    note: int
    velocity: int
    debounce_ms: int


@dataclass(frozen=True)
class ExhaleOnsetTriggerConfig:
    enabled: bool
    note: int
    velocity: int
    debounce_ms: int


@dataclass(frozen=True)
class SustainTriggerConfig:
    enabled: bool
    cc: int
    min_value: int
    max_value: int
    curve_kind: str
    curve_gamma: float


@dataclass(frozen=True)
class ConsistentBreathsTriggerConfig:
    enabled: bool
    n: int
    min_cycles_before_eval: int
    period_tol_kind: str
    period_tol_value: float
    peak_tol_kind: str
    peak_tol_value: float
    note: int
    velocity: int


@dataclass(frozen=True)
class TriggersConfig:
    inhale_onset: InhaleOnsetTriggerConfig
    exhale_onset: ExhaleOnsetTriggerConfig
    inhale_sustain: SustainTriggerConfig
    exhale_sustain: SustainTriggerConfig
    consistent_breaths: ConsistentBreathsTriggerConfig


@dataclass(frozen=True)
class MidiActivityUiConfig:
    held_dim_rgba: tuple[int, int, int, int] = (55, 55, 50, 255)
    held_lit_rgba: tuple[int, int, int, int] = (220, 180, 70, 255)
    velocity_bar_h: int = 6
    cc_bar_h: int = 8
    show_note_name: bool = False


@dataclass(frozen=True)
class UiConfig:
    window_width: int = 1320
    window_height: int = 880
    window_x: int = -1
    window_y: int = -1
    left_panel_open: bool = True
    right_panel_open: bool = True
    midi_activity: MidiActivityUiConfig = field(default_factory=MidiActivityUiConfig)


@dataclass(frozen=True)
class ConfigModel:
    version: int
    controller_id: str
    input: InputConfig
    signal: SignalConfig
    detection: DetectionConfig
    midi: MidiConfig
    triggers: TriggersConfig
    ui: UiConfig

