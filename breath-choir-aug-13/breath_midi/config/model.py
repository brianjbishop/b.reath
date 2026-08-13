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
    # ── Phase stickiness ──────────────────────────────────────────────────
    #
    # One dial for how hard it is to leave the current phase, in either
    # direction. It drives three things that all express the same idea:
    #
    #   min_phase_ms     how long a phase must last before another can start
    #   min_hold_ms      how long the breath must be still before HOLD latches
    #   hold_exit_delta  how far it must move to break a latched hold
    #
    # They were separate knobs, but they are never usefully tuned apart: the
    # symptom is always "the phase changes too readily" or "not readily
    # enough". Chatter between inhale and exhale on a plateau — before a hold
    # catches — is the case that matters, because with gate-style notes every
    # flip is an audible spurious note.
    #
    # 0 = twitchy, 1 = very sticky. Each derived value can still be pinned
    # explicitly (config or tests); stickiness only supplies the default.
    phase_stickiness: float = 0.5

    hold_enabled: bool = True
    hold_peak_band: float = 0.80
    hold_valley_band: float = 0.20
    hold_still_tol: float = 0.05

    # Explicit overrides. None means "derive from phase_stickiness".
    min_phase_ms_override: int | None = None
    min_hold_ms_override: int | None = None
    hold_exit_delta_override: float | None = None

    def _s(self) -> float:
        return max(0.0, min(1.0, float(self.phase_stickiness)))

    @property
    def min_phase_ms(self) -> int:
        """Dwell before any phase change is accepted. This is the anti-chatter one."""
        if self.min_phase_ms_override is not None:
            return int(self.min_phase_ms_override)
        return int(100 + self._s() * 500)          # 100 … 600 ms

    @property
    def min_hold_ms(self) -> int:
        """Stillness required before HOLD latches."""
        if self.min_hold_ms_override is not None:
            return int(self.min_hold_ms_override)
        return int(700 + self._s() * 1800)         # 700 … 2500 ms

    @property
    def hold_exit_delta(self) -> float:
        """Travel required to break a latched hold."""
        if self.hold_exit_delta_override is not None:
            return float(self.hold_exit_delta_override)
        return 0.05 + self._s() * 0.25             # 0.05 … 0.30


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
class NetworkConfig:
    """
    Which router counts as the performance network.

    Identified by gateway MAC, not SSID: macOS will not report an SSID without
    Location Services, and a MAC names the specific box rather than a name that
    two routers could share.  Empty means "not set yet".
    """

    expected_gateway_mac: str = ""
    label: str = "breath-choir"


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
    network: NetworkConfig = field(default_factory=NetworkConfig)

