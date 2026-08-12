from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import replace

from breath_midi.config.model import ConfigModel
from breath_midi.input.base import BreathInputSource
from breath_midi.input.ble_source import BleBreathInput
from breath_midi.input.osc_source import OscBreathInput
from breath_midi.midi.base import MidiSink
from breath_midi.midi.router import MidiRouter
from breath_midi.signal.features import FeatureExtractor
from breath_midi.signal.processor import SignalProcessor
from breath_midi.triggers.engine import TriggerEngine
from breath_midi.triggers.v1 import v1_strategies
from breath_midi.types import CycleMetrics, Phase, RuntimeState
from breath_midi.types import BreathSample


class ControllerRuntime:
    def __init__(self, config: ConfigModel, midi: MidiSink):
        self._lock = threading.Lock()
        self._running = False

        self.config = config
        self.midi = midi

        self._input: BreathInputSource = self._make_input(config)
        self._signal = SignalProcessor(config.signal)
        self._features = FeatureExtractor(config.detection)
        self._triggers = TriggerEngine(config, strategies=v1_strategies())
        self._router = MidiRouter(config, midi=midi)

        self._recent: deque = deque(maxlen=30)
        self._plot_t: deque[float] = deque(maxlen=1600)
        self._plot_amp: deque[float] = deque(maxlen=1600)
        self._plot_t0: float | None = None

        self._rx_count = 0
        self._rx_t0 = time.monotonic()
        self._rx_hz = 0.0
        dummy = BreathSample(t=0.0, amp=0.0, source_id="none")
        dummy_frame = self._features.update(self._signal.process(dummy))
        self._last_state = RuntimeState(
            t=0.0,
            amp=0.0,
            phase=Phase.REST,
            d_amp=0.0,
            last_cycle=None,
            rolling=dummy_frame.rolling,
            recent_triggers=[],
            source_id="none",
            input_mode=str(config.input.mode),
            input_status="disconnected",
            rx_hz=0.0,
            consistent_streak=0,
            consistent_target=int(config.triggers.consistent_breaths.n),
            consistent_held=False,
        )

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True

        # Open MIDI
        try:
            out_port = self.config.midi.out_port.strip() or None
            self.midi.open(out_port)  # type: ignore[arg-type]
        except Exception:
            pass

        # Start input
        self._input.start(self._on_sample)

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def stop(self) -> None:
        with self._lock:
            self._running = False
        try:
            self._input.stop()
        except Exception:
            pass
        try:
            self.midi.close()
        except Exception:
            pass

    def reset_subsystems_from_config(self, cfg: ConfigModel) -> None:
        """Rebuild processing chain and input from cfg; clear session buffers. Not running."""
        with self._lock:
            self.config = cfg
            self._signal = SignalProcessor(cfg.signal)
            self._features = FeatureExtractor(cfg.detection)
            self._triggers = TriggerEngine(cfg, strategies=v1_strategies())
            self._router = MidiRouter(cfg, midi=self.midi)
            try:
                self._input.stop()
            except Exception:
                pass
            self._input = self._make_input(cfg)
            self._recent.clear()
            self._plot_t.clear()
            self._plot_amp.clear()
            self._plot_t0 = None
            self._rx_count = 0
            self._rx_t0 = time.monotonic()
            self._rx_hz = 0.0
            dummy = BreathSample(t=0.0, amp=0.0, source_id="none")
            dummy_frame = self._features.update(self._signal.process(dummy))
            self._last_state = RuntimeState(
                t=0.0,
                amp=0.0,
                phase=Phase.REST,
                d_amp=0.0,
                last_cycle=None,
                rolling=dummy_frame.rolling,
                recent_triggers=[],
                source_id="none",
                input_mode=str(cfg.input.mode),
                input_status="disconnected",
                rx_hz=0.0,
                consistent_streak=0,
                consistent_target=int(cfg.triggers.consistent_breaths.n),
                consistent_held=False,
            )

    def set_config(self, cfg: ConfigModel) -> None:
        with self._lock:
            self.config = cfg
            self._signal.update_config(cfg.signal)
            self._features.update_config(cfg.detection)
            self._triggers.update_config(cfg)
            self._router.update_config(cfg)

            # Recreate input if mode or key settings change
            try:
                self._input.stop()
            except Exception:
                pass
            self._input = self._make_input(cfg)
            if self._running:
                self._input.start(self._on_sample)

        # MIDI port changes: attempt reopen
        try:
            self.midi.close()
        except Exception:
            pass
        try:
            out_port = cfg.midi.out_port.strip() or None
            self.midi.open(out_port)  # type: ignore[arg-type]
        except Exception:
            pass

    def get_latest_state(self) -> RuntimeState:
        with self._lock:
            return self._last_state

    def get_plot_data(self) -> tuple[list[float], list[float]]:
        with self._lock:
            return (list(self._plot_t), list(self._plot_amp))

    # ---- BLE helpers for UI
    def ble_scan(self) -> list[tuple[str, str]]:
        with self._lock:
            inp = self._input
        if isinstance(inp, BleBreathInput):
            devs = inp.scan()
            return [(d.label, d.address) for d in devs]
        return []

    def ble_connect(self, address: str) -> None:
        with self._lock:
            inp = self._input
        if isinstance(inp, BleBreathInput):
            inp.connect(address)

    def ble_disconnect(self) -> None:
        with self._lock:
            inp = self._input
        if isinstance(inp, BleBreathInput):
            inp.disconnect()

    def _make_input(self, cfg: ConfigModel) -> BreathInputSource:
        mode = (cfg.input.mode or "osc").lower().strip()
        if mode == "ble":
            return BleBreathInput(
                auto_connect=bool(cfg.input.ble_auto_connect),
                address=str(cfg.input.ble_address or ""),
            )
        return OscBreathInput(
            port=cfg.input.osc_port,
            source_filter=cfg.input.source_filter,
        )

    def _on_sample(self, sample) -> None:
        # Called from input thread
        with self._lock:
            if not self._running:
                return
            ps = self._signal.process(sample)
            frame = self._features.update(ps)

            # plot buffer (15s window)
            if self._plot_t0 is None:
                self._plot_t0 = frame.t
            t_rel = frame.t - self._plot_t0
            self._plot_t.append(t_rel)
            # Match totem_ble_viewer behavior: plot the value coming from TOTEM.
            # Keep the controller pipeline (features/triggers) based on `frame.amp`.
            self._plot_amp.append(float(ps.amp_raw))
            cutoff_plot = t_rel - 15.0
            while self._plot_t and self._plot_t[0] < cutoff_plot:
                self._plot_t.popleft()
                self._plot_amp.popleft()

            # rx rate (OSC); BLE provides its own estimate too
            now = time.monotonic()
            self._rx_count += 1
            elapsed = now - self._rx_t0
            if elapsed >= 1.0:
                self._rx_hz = self._rx_count / elapsed
                self._rx_count = 0
                self._rx_t0 = now

            status = "listening"
            if isinstance(self._input, BleBreathInput):
                status, _connected, ble_hz = self._input.status()
                if ble_hz > 0:
                    self._rx_hz = ble_hz

            events = self._triggers.on_frame(frame)
            for e in events:
                # store absolute-ish time for UI pruning (monotonic based)
                self._recent.append(replace(e, mono_t=time.monotonic()))
                try:
                    self._router.handle(e)
                except Exception:
                    continue

            # prune recent events older than ~1.5s using frame time basis
            cutoff = frame.t - 1.5
            while self._recent and getattr(self._recent[0], "t", 0.0) < cutoff:
                self._recent.popleft()

            last_cycle: CycleMetrics | None = frame.cycle if frame.cycle_completed else self._last_state.last_cycle
            consistent_streak, consistent_target, consistent_held = self._triggers.consistent_status()
            self._last_state = RuntimeState(
                t=frame.t,
                # Display/monitor should match viewer: show incoming TOTEM value.
                amp=float(ps.amp_raw),
                phase=frame.phase,
                d_amp=frame.d_amp,
                last_cycle=last_cycle,
                rolling=frame.rolling,
                recent_triggers=list(self._recent),
                source_id=frame.source_id,
                input_mode=str(self.config.input.mode),
                input_status=str(status),
                rx_hz=float(self._rx_hz),
                consistent_streak=int(consistent_streak),
                consistent_target=int(consistent_target),
                consistent_held=bool(consistent_held),
            )

