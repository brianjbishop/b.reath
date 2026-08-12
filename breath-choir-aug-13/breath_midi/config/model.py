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
    # Hold detection.  A hold is the breath sitting near the top or the bottom
    # of its range and staying there: inside a band, moving less than
    # hold_still_tol, for min_hold_ms.  Requiring a band is what separates a
    # deliberate hold from a mid-breath hesitation — a pause at 0.5 is someone
    # thinking about it, not holding.
    #
    # The bands are fractions of the performer's own recent range, because the
    # incoming value is already normalised per device upstream.  That is what
    # makes one setting work for a shallow breather and a deep one.
    # min_hold_ms must exceed the natural turnaround of a smooth breath, or
    # ordinary breathing registers as holding.  Rule of thumb from measurement:
    # it needs to be roughly an eighth of the breath cycle.  1500ms is clean
    # down to about 6 breaths/minute, which covers normal and meditative
    # tempos.  Slower than ~4 breaths/minute, raising this stops helping —
    # at that point the breath cycle is approaching the length of the upstream
    # normalisation window and the signal itself is the limit, not the dwell.
    hold_enabled: bool = True
    min_hold_ms: int = 1500
    hold_peak_band: float = 0.80
    hold_valley_band: float = 0.20
    hold_still_tol: float = 0.05
    # Once a hold latches it is held until the breath *moves away* by this much
    # from where it latched — slope alone is not enough to break it.
    #
    # This exists because the upstream normalisation is a rolling min/max: hold
    # your breath and the window gradually forgets the breathing that set its
    # range, so the reported value drifts even though the performer is still.
    # That drift has slope, and a slope-based exit reads it as a new inhale or
    # exhale — the hold silently ends while the performer is still holding.
    # Displacement does not have that problem: drift is slow and bounded, a real
    # breath is neither.
    hold_exit_delta: float = 0.15


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
class HoldOnsetTriggerConfig:
    """
    Fires when the FSM commits to a breath hold.  Note 0 means silent, which is
    the default: a hold releases whatever was sounding and plays nothing until
    a note is deliberately assigned.
    """

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
    hold_onset: HoldOnsetTriggerConfig = field(
        default_factory=lambda: HoldOnsetTriggerConfig(
            enabled=False, note=0, velocity=100, debounce_ms=200
        )
    )


@dataclass(frozen=True)
class MidiActivityUiConfig:
    held_dim_rgba: tuple[int, int, int, int] = (55, 55, 50, 255)
    held_lit_rgba: tuple[int, int, int, int] = (220, 180, 70, 255)
    velocity_bar_h: int = 6
    cc_bar_h: int = 8
    show_note_name: bool = False


@dataclass(frozen=True)
class VizConfig:
    """
    Browser visualization fan-out (rose_breath).

    The app receives phone data on input.osc_port and rebroadcasts it here, so
    there is no separate bridge process and nothing else binds the OSC port.
    """

    ws_enabled: bool = True
    ws_port: int = 8765
    ws_host: str = "localhost"


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
    viz: VizConfig = field(default_factory=VizConfig)

