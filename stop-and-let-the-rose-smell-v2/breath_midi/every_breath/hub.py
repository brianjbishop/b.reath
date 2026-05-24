from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from breath_midi.config.model import ConfigModel
from breath_midi.every_breath.device_runtime import DeviceRuntime, make_device_config
from breath_midi.every_breath.multi_osc import MultiDeviceOscSource
from breath_midi.every_breath.registry import DeviceEntry, DeviceRegistry
from breath_midi.midi.activity_bus import MidiActivityBus
from breath_midi.midi.mido_sink import MidoMidiSink
from breath_midi.types import BreathSample, Phase

_WAVEFORM_MAXLEN = 600


@dataclass
class DeviceUISnapshot:
    uuid: str
    name: str
    color: tuple[int, int, int]
    inhale_note: int
    exhale_note: int
    phase: Phase
    raw_amp: float
    muted: bool
    soloed: bool
    waveform: list[float]
    active: bool
    cc_mode: bool
    cc_value: int
    cons_n: int
    cons_tolerance: float
    consistent_gate_open: bool


class EveryBreathHub:
    """
    Orchestrates the Every Breath pipeline:
      - DeviceRegistry: persistent UUID → DeviceEntry mapping
      - MultiDeviceOscSource: single UDP socket, all devices
      - DeviceRuntime per UUID: independent signal → trigger → MIDI chain
      - One shared MidoMidiSink for all devices (single OSC thread, no lock needed)
    """

    def __init__(self, config: ConfigModel) -> None:
        self.registry = DeviceRegistry()
        self._config = config
        self._activity_bus = MidiActivityBus()
        self._midi_sink: MidoMidiSink | None = None
        self._source: MultiDeviceOscSource | None = None
        self._runtimes: dict[str, DeviceRuntime] = {}
        self._waveform_bufs: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._listening = False

    # ── public lifecycle ──────────────────────────────────────────────────────

    def start_listening(self, out_port: str | None = None) -> None:
        if self._listening:
            return
        if self._midi_sink is None:
            self._midi_sink = MidoMidiSink(
                activity_bus=self._activity_bus,
                source_id="eb",
            )
            try:
                self._midi_sink.open(out_port)
            except Exception as exc:
                print(f"[EveryBreath] MIDI open failed: {exc}")
        self._source = MultiDeviceOscSource(
            port=8001,
            on_sample_cb=self._on_sample,
            on_new_device_cb=self._on_new_device,
            on_timeout_cb=self._on_timeout,
        )
        self._source.start()
        self._listening = True
        print("Every Breath listening on port 8001")

    def stop_listening(self) -> None:
        if not self._listening:
            return
        if self._source is not None:
            self._source.stop()
            self._source = None
        self._listening = False
        self.registry.mark_all_disconnected()
        # Close the MIDI sink so start_listening() opens a fresh one.
        # This guarantees the next start gets a healthy port handle — mido
        # ports can go stale across a stop/start cycle if left open.
        if self._midi_sink is not None:
            try:
                self._midi_sink.close()
            except Exception:
                pass
            self._midi_sink = None
        # Clear runtimes so reconnecting devices get fresh pipelines that
        # reference the new sink.  Without this, _on_new_device() would
        # find the UUID already in _runtimes and skip creating a new runtime,
        # leaving the pipeline pointing at the old (now closed) sink.
        self._runtimes.clear()
        with self._lock:
            self._waveform_bufs.clear()

    def stop(self) -> None:
        """Full shutdown — called on app exit."""
        self.stop_listening()
        if self._midi_sink is not None:
            try:
                self._midi_sink.close()
            except Exception:
                pass
            self._midi_sink = None

    # ── public UI interface ───────────────────────────────────────────────────

    def get_ui_snapshot(self) -> list[DeviceUISnapshot]:
        """
        Called from the UI (main) thread each frame.
        Returns one snapshot per known device (connected or paused), sorted by display_order.
        active=False means the device timed out but is kept in the grid with frozen waveform.
        """
        connected = self.registry.connected_uuids()
        result: list[DeviceUISnapshot] = []
        for entry in self.registry.all_entries():
            is_active = entry.uuid in connected
            with self._lock:
                buf = list(self._waveform_bufs.get(entry.uuid, deque()))
            runtime = self._runtimes.get(entry.uuid)
            phase = runtime.get_phase() if runtime is not None else Phase.REST
            result.append(
                DeviceUISnapshot(
                    uuid=entry.uuid,
                    name=entry.name,
                    color=entry.color,
                    inhale_note=entry.inhale_note,
                    exhale_note=entry.exhale_note,
                    phase=phase,
                    raw_amp=buf[-1] if buf else 0.0,
                    muted=entry.muted,
                    soloed=entry.soloed,
                    waveform=buf,
                    active=is_active,
                    cc_mode=entry.cc_mode,
                    cc_value=entry.cc_value,
                    cons_n=entry.cons_n,
                    cons_tolerance=entry.cons_tolerance,
                    consistent_gate_open=runtime.get_gate_open() if runtime is not None else True,
                )
            )
        return result

    def set_muted(self, uuid: str, muted: bool) -> None:
        self.registry.set_muted(uuid, muted)

    def set_soloed(self, uuid: str, soloed: bool) -> None:
        self.registry.set_soloed(uuid, soloed)

    def set_name(self, uuid: str, name: str) -> None:
        self.registry.set_name(uuid, name)

    def set_color(self, uuid: str, color: tuple[int, int, int]) -> None:
        self.registry.set_color(uuid, color)

    def swap_order(self, uuid_a: str, uuid_b: str) -> None:
        self.registry.swap_order(uuid_a, uuid_b)

    def set_device_notes(self, uuid: str, inhale_note: int, exhale_note: int) -> None:
        self.registry.set_inhale_note(uuid, inhale_note)
        self.registry.set_exhale_note(uuid, exhale_note)
        runtime = self._runtimes.get(uuid)
        if runtime is not None:
            runtime.set_notes(inhale_note, exhale_note)

    def set_cc_mode(self, uuid: str, cc_mode: bool) -> None:
        self.registry.set_cc_mode(uuid, cc_mode)
        runtime = self._runtimes.get(uuid)
        if runtime is not None:
            runtime.set_output_mode(cc_mode)
            if cc_mode:
                # Sync CC numbers from registry so the triggers use the
                # displayed In#/Ex# values rather than their default 1/2.
                entry = self.registry.get(uuid)
                if entry is not None:
                    runtime.set_inhale_cc(entry.inhale_note)
                    runtime.set_exhale_cc(entry.exhale_note)

    def set_inhale_number(self, uuid: str, value: int) -> None:
        entry = self.registry.get(uuid)
        if entry is None:
            return
        self.registry.set_inhale_note(uuid, value)
        runtime = self._runtimes.get(uuid)
        if runtime is None:
            return
        if entry.cc_mode:
            runtime.set_inhale_cc(value)
        else:
            runtime.set_notes(value, entry.exhale_note)

    def set_exhale_number(self, uuid: str, value: int) -> None:
        entry = self.registry.get(uuid)
        if entry is None:
            return
        self.registry.set_exhale_note(uuid, value)
        runtime = self._runtimes.get(uuid)
        if runtime is None:
            return
        if entry.cc_mode:
            runtime.set_exhale_cc(value)
        else:
            runtime.set_notes(entry.inhale_note, value)

    def set_cc_value(self, uuid: str, value: int) -> None:
        self.registry.set_cc_value(uuid, value)
        runtime = self._runtimes.get(uuid)
        if runtime is not None:
            runtime.set_cc_value(value)

    def set_cons_n(self, uuid: str, n: int) -> None:
        self.registry.set_cons_n(uuid, n)
        runtime = self._runtimes.get(uuid)
        if runtime is not None:
            runtime.set_cons_n(n)

    def set_cons_tolerance(self, uuid: str, tol: float) -> None:
        self.registry.set_cons_tolerance(uuid, tol)
        runtime = self._runtimes.get(uuid)
        if runtime is not None:
            runtime.set_cons_tolerance(tol)

    # ── OSC callbacks (called from single OSC receive thread) ─────────────────

    def _on_new_device(self, uuid: str) -> None:
        entry, is_new = self.registry.get_or_create(uuid)
        self.registry.mark_connected(uuid)
        if uuid not in self._runtimes:
            assert self._midi_sink is not None
            device_cfg = make_device_config(self._config, entry.inhale_note, entry.exhale_note)
            self._runtimes[uuid] = DeviceRuntime(device_cfg, self._midi_sink)
            with self._lock:
                self._waveform_bufs[uuid] = deque(maxlen=_WAVEFORM_MAXLEN)
        print(
            f"Device connected: {uuid} | "
            f"inhale: {entry.inhale_note} exhale: {entry.exhale_note}"
        )

    def _on_timeout(self, uuid: str) -> None:
        self.registry.mark_disconnected(uuid)
        print(f"Device disconnected: {uuid}")

    def _on_sample(self, sample: BreathSample) -> None:
        uuid = sample.source_id

        # set_activity_source_id is called here without a lock because
        # _on_sample is always invoked from the single OSC receive thread.
        # All DeviceRuntime.on_sample() calls are sequential in that same thread.
        # If the threading model changes in future (e.g. per-device threads),
        # this assumption MUST be revisited and a lock or per-device sink introduced.
        if self._midi_sink is not None:
            self._midi_sink.set_activity_source_id(uuid)

        entry = self.registry.get(uuid)
        if entry is None:
            return
        runtime = self._runtimes.get(uuid)
        if runtime is None:
            return

        muted = entry.muted or (self.registry.is_any_soloed() and not entry.soloed)
        runtime.on_sample(sample, muted=muted)

        with self._lock:
            buf = self._waveform_bufs.get(uuid)
            if buf is not None:
                buf.append(sample.amp)  # raw OSC amplitude — no signal processing applied
