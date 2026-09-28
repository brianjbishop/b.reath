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
    """
    Breath phase detection.

    Phase changes are decided by **retracement**, not by instantaneous slope: a
    phase ends once the breath has travelled a set distance back from the
    extreme it reached during that phase. Slope alone was the cause of the
    inhale/exhale chatter — on a plateau, noise pushes the derivative across a
    threshold repeatedly without the breath actually going anywhere, and with
    gate-style notes each flip is an audible spurious note.

    The three exit deltas are separate because a retracement is measured on the
    *next* phase's movement, and breathing is asymmetric — I:E runs 1:3 to 1:5.
    Leaving an inhale waits on the slow exhale, so it needs a small threshold;
    leaving an exhale waits on the fast inhale and can afford a large one.
    Measured on a 1:4 breath, a single shared 0.12 detected the exhale 0.44s
    late against 0.13s for the inhale — every cycle dragging on one side.

    All deltas are fractions of the performer's own recent range, since the
    incoming value is already normalised per device upstream.
    """

    derivative_enabled: bool
    derivative_smoothing_alpha: float

    # ── Exit: how far the breath must move to end each phase ──────────────
    inhale_exit_delta: float = 0.06   # fall this far to call the exhale
    exhale_exit_delta: float = 0.12   # rise this far to call the inhale
    hold_exit_delta: float = 0.15     # move this far to break a hold

    # ── Hold ──────────────────────────────────────────────────────────────
    hold_enabled: bool = True
    hold_still_tol: float = 0.05      # how little movement counts as still
    min_hold_ms: int = 1500           # how long that stillness must persist
    hold_peak_band: float = 0.80      # a hold may be declared above this...
    hold_valley_band: float = 0.20    # ...or below this


# Not a dial: a floor that stops per-sample flapping at odd frame rates.
# Retracement does the anti-chatter work; this only guards the degenerate case.
MIN_PHASE_FLOOR_MS = 80

# A "cycle" shorter than this is not a breath — it is the detector settling, or
# noise. Counting one pollutes the rolling period average that the consistency
# gate reads, and satisfies the one-completed-cycle guard that holds wait on,
# which is how a smooth sine ended up latching a hold on its very first peak.
# 0.8s leaves headroom below even a hyperventilating 60 breaths/minute.
MIN_CYCLE_S = 0.8


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
class CcConfig:
    """
    How a breath is shaped into a controller value.  Global, not per device.

    Range and curve are a property of what the dial is driving — a filter wants
    the same response whoever is breathing into it — so they are set once in the
    Detection panel rather than repeated on every device strip.  The CC numbers
    themselves stay per device, because that is what separates performers.
    """

    min_value: int = 0
    max_value: int = 127
    # "linear" or "gamma".  Breath is perceptually non-linear, so gamma lets the
    # dial respond more at the bottom of the range or more at the top.
    curve_kind: str = "gamma"
    curve_gamma: float = 1.0


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
    cc: CcConfig = field(default_factory=CcConfig)

