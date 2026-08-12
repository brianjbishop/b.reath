from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from breath_midi.config.model import (
    ConfigModel,
    ConsistentBreathsTriggerConfig,
    DetectionConfig,
    ExhaleOnsetTriggerConfig,
    HoldOnsetTriggerConfig,
    InhaleOnsetTriggerConfig,
    InputConfig,
    MidiActivityUiConfig,
    MidiConfig,
    SignalConfig,
    SustainTriggerConfig,
    TriggersConfig,
    UiConfig,
)

try:
    import tomllib  # pyright: ignore[reportMissingImports]
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

try:
    import tomli_w  # type: ignore
except Exception:  # pragma: no cover
    tomli_w = None  # type: ignore


def _req_int(d: dict[str, Any], key: str) -> int:
    v = d.get(key)
    if not isinstance(v, int):
        raise ValueError(f"Expected int for {key}")
    return v


def _req_float(d: dict[str, Any], key: str) -> float:
    v = d.get(key)
    if not isinstance(v, (int, float)):
        raise ValueError(f"Expected float for {key}")
    return float(v)


def _req_bool(d: dict[str, Any], key: str) -> bool:
    v = d.get(key)
    if not isinstance(v, bool):
        raise ValueError(f"Expected bool for {key}")
    return v


def _req_str(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str):
        raise ValueError(f"Expected str for {key}")
    return v


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> ConfigModel:
        if tomllib is None:
            raise RuntimeError("tomllib not available; use Python 3.11+")
        raw = tomllib.loads(self.path.read_text(encoding="utf-8"))

        version = int(raw.get("version", 1))
        controller_id = str(raw.get("controller_id", "rose-01"))

        input_raw = raw.get("input", {})
        signal_raw = raw.get("signal", {})
        detection_raw = raw.get("detection", {})
        midi_raw = raw.get("midi", {})
        triggers_raw = raw.get("triggers", {})
        ui_raw = raw.get("ui", {}) if isinstance(raw.get("ui", {}), dict) else {}

        input_cfg = InputConfig(
            mode=_req_str(input_raw, "mode"),
            osc_port=_req_int(input_raw, "osc_port"),
            source_filter=_req_str(input_raw, "source_filter"),
            ble_address=str(input_raw.get("ble_address", "")),
            ble_auto_connect=bool(input_raw.get("ble_auto_connect", True)),
        )
        signal_cfg = SignalConfig(
            smoothing_kind=_req_str(signal_raw, "smoothing_kind"),
            smoothing_alpha=_req_float(signal_raw, "smoothing_alpha"),
            baseline_enabled=_req_bool(signal_raw, "baseline_enabled"),
            baseline_alpha=_req_float(signal_raw, "baseline_alpha"),
            gain=_req_float(signal_raw, "gain"),
            deadzone=_req_float(signal_raw, "deadzone"),
        )
        detection_cfg = DetectionConfig(
            derivative_enabled=_req_bool(detection_raw, "derivative_enabled"),
            derivative_smoothing_alpha=_req_float(
                detection_raw, "derivative_smoothing_alpha"
            ),
            inhale_enter_amp=_req_float(detection_raw, "inhale_enter_amp"),
            exhale_enter_amp=_req_float(detection_raw, "exhale_enter_amp"),
            rest_enter_amp=_req_float(detection_raw, "rest_enter_amp"),
            slope_enter_abs=float(detection_raw.get("slope_enter_abs", 0.08)),
            slope_rest_abs=float(detection_raw.get("slope_rest_abs", 0.03)),
            hysteresis=_req_float(detection_raw, "hysteresis"),
            min_phase_ms=_req_int(detection_raw, "min_phase_ms"),
            hold_enabled=bool(detection_raw.get("hold_enabled", True)),
            min_hold_ms=int(detection_raw.get("min_hold_ms", 1000)),
        )
        midi_cfg = MidiConfig(
            out_port=str(midi_raw.get("out_port", "")),
            channel=int(midi_raw.get("channel", 0)),
            default_velocity=int(midi_raw.get("default_velocity", 100)),
            cc_rate_hz=int(midi_raw.get("cc_rate_hz", 30)),
        )

        inhale_onset_raw = triggers_raw.get("inhale_onset", {})
        exhale_onset_raw = triggers_raw.get("exhale_onset", {})
        inhale_sustain_raw = triggers_raw.get("inhale_sustain", {})
        exhale_sustain_raw = triggers_raw.get("exhale_sustain", {})
        consistent_raw = triggers_raw.get("consistent_breaths", {})
        hold_full_raw = triggers_raw.get("hold_full_onset", {})
        hold_empty_raw = triggers_raw.get("hold_empty_onset", {})

        triggers_cfg = TriggersConfig(
            inhale_onset=InhaleOnsetTriggerConfig(
                enabled=bool(inhale_onset_raw.get("enabled", True)),
                note=int(inhale_onset_raw.get("note", 60)),
                velocity=int(inhale_onset_raw.get("velocity", midi_cfg.default_velocity)),
                debounce_ms=int(inhale_onset_raw.get("debounce_ms", 200)),
            ),
            exhale_onset=ExhaleOnsetTriggerConfig(
                enabled=bool(exhale_onset_raw.get("enabled", True)),
                note=int(exhale_onset_raw.get("note", 62)),
                velocity=int(exhale_onset_raw.get("velocity", midi_cfg.default_velocity)),
                debounce_ms=int(exhale_onset_raw.get("debounce_ms", 200)),
            ),
            inhale_sustain=SustainTriggerConfig(
                enabled=bool(inhale_sustain_raw.get("enabled", True)),
                cc=int(inhale_sustain_raw.get("cc", 1)),
                min_value=int(inhale_sustain_raw.get("min", 0)),
                max_value=int(inhale_sustain_raw.get("max", 127)),
                curve_kind=str(inhale_sustain_raw.get("curve_kind", "gamma")),
                curve_gamma=float(inhale_sustain_raw.get("curve_gamma", 1.0)),
            ),
            exhale_sustain=SustainTriggerConfig(
                enabled=bool(exhale_sustain_raw.get("enabled", True)),
                cc=int(exhale_sustain_raw.get("cc", 2)),
                min_value=int(exhale_sustain_raw.get("min", 0)),
                max_value=int(exhale_sustain_raw.get("max", 127)),
                curve_kind=str(exhale_sustain_raw.get("curve_kind", "gamma")),
                curve_gamma=float(exhale_sustain_raw.get("curve_gamma", 1.0)),
            ),
            consistent_breaths=ConsistentBreathsTriggerConfig(
                enabled=bool(consistent_raw.get("enabled", True)),
                n=int(consistent_raw.get("n", 5)),
                min_cycles_before_eval=int(consistent_raw.get("min_cycles_before_eval", 3)),
                period_tol_kind=str(consistent_raw.get("period_tol_kind", "relative")),
                period_tol_value=float(consistent_raw.get("period_tol_value", 0.15)),
                peak_tol_kind=str(consistent_raw.get("peak_tol_kind", "absolute")),
                peak_tol_value=float(consistent_raw.get("peak_tol_value", 0.1)),
                note=int(consistent_raw.get("note", 64)),
                velocity=int(consistent_raw.get("velocity", midi_cfg.default_velocity)),
            ),
            # Holds default to disabled — see HoldOnsetTriggerConfig.
            hold_full_onset=HoldOnsetTriggerConfig(
                enabled=bool(hold_full_raw.get("enabled", False)),
                note=int(hold_full_raw.get("note", 67)),
                velocity=int(hold_full_raw.get("velocity", midi_cfg.default_velocity)),
                debounce_ms=int(hold_full_raw.get("debounce_ms", 200)),
            ),
            hold_empty_onset=HoldOnsetTriggerConfig(
                enabled=bool(hold_empty_raw.get("enabled", False)),
                note=int(hold_empty_raw.get("note", 60)),
                velocity=int(hold_empty_raw.get("velocity", midi_cfg.default_velocity)),
                debounce_ms=int(hold_empty_raw.get("debounce_ms", 200)),
            ),
        )

        ma_raw = ui_raw.get("midi_activity", {})
        if not isinstance(ma_raw, dict):
            ma_raw = {}
        _mad = MidiActivityUiConfig()

        def _rgba4(key: str, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            v = ma_raw.get(key)
            if isinstance(v, (list, tuple)) and len(v) == 4:
                return (int(v[0]), int(v[1]), int(v[2]), int(v[3]))
            return default

        midi_activity_cfg = MidiActivityUiConfig(
            held_dim_rgba=_rgba4("held_dim_rgba", _mad.held_dim_rgba),
            held_lit_rgba=_rgba4("held_lit_rgba", _mad.held_lit_rgba),
            velocity_bar_h=int(ma_raw.get("velocity_bar_h", _mad.velocity_bar_h)),
            cc_bar_h=int(ma_raw.get("cc_bar_h", _mad.cc_bar_h)),
            show_note_name=bool(ma_raw.get("show_note_name", _mad.show_note_name)),
        )

        ui_cfg = UiConfig(
            window_width=int(ui_raw.get("window_width", 1320)),
            window_height=int(ui_raw.get("window_height", 880)),
            window_x=int(ui_raw.get("window_x", -1)),
            window_y=int(ui_raw.get("window_y", -1)),
            left_panel_open=bool(ui_raw.get("left_panel_open", True)),
            right_panel_open=bool(ui_raw.get("right_panel_open", True)),
            midi_activity=midi_activity_cfg,
        )

        return ConfigModel(
            version=version,
            controller_id=controller_id,
            input=input_cfg,
            signal=signal_cfg,
            detection=detection_cfg,
            midi=midi_cfg,
            triggers=triggers_cfg,
            ui=ui_cfg,
        )

    def save(self, cfg: ConfigModel) -> None:
        if tomli_w is None:
            raise RuntimeError("tomli-w not installed (required for saving config)")
        data = asdict(cfg)
        # Match the on-disk config.toml keys (avoid dataclass field renames leaking)
        # tomli-w preserves ordering in insertion order for dicts in py3.7+.
        self.path.write_text(tomli_w.dumps(data), encoding="utf-8")

