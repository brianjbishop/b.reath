from __future__ import annotations

import threading
from pathlib import Path
from collections import deque
from dataclasses import dataclass

from breath_midi.config.model import ConfigModel
from breath_midi.every_breath.device_runtime import DeviceRuntime, make_device_config
from breath_midi.every_breath.multi_osc import MultiDeviceOscSource
from breath_midi.feed import SampleFeed
from breath_midi.every_breath.registry import DeviceEntry, DeviceRegistry
from breath_midi.midi.activity_bus import MidiActivityBus
from breath_midi.midi.mido_sink import MidoMidiSink
from breath_midi.types import BreathSample, Phase
from breath_midi.viz.ws_server import BreathWebSocketServer

_WAVEFORM_MAXLEN = 600
# Phones send here.  Every Breath / Group Breath share it and are mutually
# exclusive, and nothing else binds it now that the bridge is in-process.
_OSC_PORT = 8001


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
    hold_note: int


class EveryBreathHub:
    """
    Orchestrates the Every Breath pipeline:
      - DeviceRegistry: persistent UUID → DeviceEntry mapping
      - MultiDeviceOscSource: single UDP socket, all devices
      - DeviceRuntime per UUID: independent signal → trigger → MIDI chain
      - One shared MidoMidiSink for all devices (single OSC thread, no lock needed)
    """

    def __init__(self, config: ConfigModel, osc_port: int = _OSC_PORT) -> None:
        self.registry = DeviceRegistry()
        self._config = config
        self._osc_port = int(osc_port)
        self._activity_bus = MidiActivityBus()
        self._midi_sink: MidoMidiSink | None = None
        self._source: MultiDeviceOscSource | None = None
        # Every source posts through one drain thread; see feed.py.
        self._feed: SampleFeed | None = None
        # prefix -> TrackPlaybackSource, for tracks currently in the choir.
        self._tracks: dict = {}
        self._track_seq = 0
        self._recorder = None
        self._recordings_dir = (
            Path(__file__).resolve().parents[2] / "tracks" / "recordings"
        )
        self._runtimes: dict[str, DeviceRuntime] = {}
        self._waveform_bufs: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._listening = False
        self._ws: BreathWebSocketServer | None = None
        # Surfaced in the Every Breath toolbar; None when the fan-out is healthy.
        self.viz_error: str | None = None

    # ── public lifecycle ──────────────────────────────────────────────────────

    def _ensure_feed(self) -> SampleFeed:
        """Started by whichever of the listener or a track needs it first."""
        if self._feed is None:
            self._feed = SampleFeed(
                self._on_sample, self._on_new_device, self._on_timeout
            )
            self._feed.start()
        return self._feed

    def _release_feed_if_idle(self) -> None:
        """Stop the drain thread only once nothing is producing into it."""
        if self._listening:
            return
        if getattr(self, "_tracks", None):
            return
        if self._feed is not None:
            self._feed.stop()
            self._feed = None

    # ── recording ────────────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None

    def start_recording(self, name: str) -> None:
        """
        Capture live breath into a take.

        Refused while a track is playing: that would only produce a lossy copy
        of a file that already exists.
        """
        if self._tracks:
            print("[Tracks] not recording: a track is playing")
            return
        from breath_midi.tracks.recorder import TrackRecorder

        self._recorder = TrackRecorder(self._config.detection, name=name)

    def stop_recording(self):
        """
        Write the take and return its path, or None if nothing was captured.

        An empty take writes no file — hitting record and stop with nobody
        breathing should not litter the folder with empty tracks.
        """
        recorder, self._recorder = self._recorder, None
        if recorder is None or recorder.sample_count == 0:
            return None

        for entry in self.registry.all_entries():
            recorder.set_device_meta(
                entry.uuid, entry.name, entry.color,
                entry.inhale_note, entry.exhale_note,
            )

        from breath_midi.tracks.file import write_track

        # The take name becomes a filename, so strip anything that could walk
        # out of the folder rather than trusting what was typed.
        safe = "".join(
            c for c in recorder.name if c.isalnum() or c in " -_"
        ).strip()
        path = self._recordings_dir / f"{safe or 'take'}.breath.json"
        write_track(path, recorder.to_track())
        print(f"[Tracks] wrote {path}")
        return path

    # ── tracks ───────────────────────────────────────────────────────────────

    def _ensure_midi_sink(self) -> None:
        """Open a sink if one is not already open.  Failure is reported, not fatal."""
        if self._midi_sink is not None:
            return
        self._midi_sink = MidoMidiSink(
            activity_bus=self._activity_bus, source_id="eb"
        )
        try:
            self._midi_sink.open(self._config.midi.out_port.strip() or None)
        except Exception as exc:
            print(f"[Tracks] MIDI open failed: {exc}")

    def load_track(self, path) -> str:
        """
        Add a saved performance to the choir.  Returns the prefix assigned to it.

        Deliberately does not touch config.detection.  The track's stored dials
        are provenance — what happened to be set when it was captured — and
        applying them is a separate, explicit action.  The track is the clip;
        the dials are the instrument.

        Raises ValueError if the file is malformed, before anything is started.
        """
        from breath_midi.tracks.file import read_track
        from breath_midi.tracks.playback import TrackPlaybackSource

        track = read_track(path)           # validate before touching any state
        self._track_seq += 1
        prefix = f"pb{self._track_seq}"

        self._ensure_midi_sink()

        # Seed names and colours before playback announces the devices, so the
        # panel shows the performers the track was recorded with rather than
        # Device 1..n briefly flashing up first.
        for device in track.devices:
            uuid = f"{prefix}:{device.uuid}"
            self.registry.get_or_create(uuid)
            self.registry.set_name(uuid, device.name)
            self.registry.set_color(uuid, device.color)

        source = TrackPlaybackSource(track, self._ensure_feed(), prefix=prefix)
        self._tracks[prefix] = source
        source.start()
        return prefix

    def stop_track(self, prefix: str) -> None:
        """Stop one track and let go of any keys its performers were holding."""
        source = self._tracks.pop(prefix, None)
        if source is None:
            return
        source.stop()
        for entry in self.registry.all_entries():
            if not entry.uuid.startswith(f"{prefix}:"):
                continue
            runtime = self._runtimes.get(entry.uuid)
            if runtime is not None:
                try:
                    runtime.release()
                except Exception:
                    pass
            self.registry.mark_disconnected(entry.uuid)
        self._release_feed_if_idle()

    def stop_all_tracks(self) -> None:
        for prefix in list(self._tracks):
            self.stop_track(prefix)

    @property
    def playing_tracks(self) -> list[str]:
        return sorted(self._tracks)

    def start_listening(self, out_port: str | None = None) -> None:
        """
        Bind the OSC port and start the visualization fan-out.

        Raises OSError if the OSC port is already in use.  That used to be
        silently survivable via SO_REUSEADDR, which was the whole bug behind
        the old bridge setup — see multi_osc.start().  Callers are expected to
        report the failure and stay stopped.
        """
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
        feed = self._ensure_feed()
        source = MultiDeviceOscSource(
            port=self._osc_port,
            on_sample_cb=feed.submit_sample,
            on_new_device_cb=feed.submit_new_device,
            on_timeout_cb=feed.submit_timeout,
        )
        # Bind before assigning to self._source so a failure leaves the hub
        # cleanly stopped rather than holding a half-started source.
        source.start()
        self._source = source
        self._listening = True
        print(f"Every Breath listening on port {self._osc_port}")
        self._start_viz()

    def _start_viz(self) -> None:
        """
        Start the browser fan-out.  Never fatal: a busy 8765 costs you the
        visualization, and taking MIDI down with it would be worse.
        """
        cfg = self._config.viz
        if not cfg.ws_enabled:
            return
        server = BreathWebSocketServer(port=cfg.ws_port, host=cfg.ws_host)
        try:
            server.start()
        except Exception as exc:
            self.viz_error = f"visualization off — port {cfg.ws_port}: {exc}"
            print(f"[viz] WebSocket start failed: {exc}")
            return
        self._ws = server
        self.viz_error = None

    def stop_listening(self) -> None:
        if not self._listening:
            return
        if self._source is not None:
            self._source.stop()
            self._source = None
        if self._ws is not None:
            self._ws.stop()
            self._ws = None
        # Release every held note while the sink is still open.
        for runtime in self._runtimes.values():
            try:
                runtime.release()
            except Exception:
                pass
        self._listening = False
        self._release_feed_if_idle()
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
                    hold_note=entry.hold_note,
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
            runtime.set_notes(inhale_note, exhale_note, entry.hold_note)

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
                    runtime.set_hold_cc(entry.hold_note)

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
            runtime.set_notes(value, entry.exhale_note, entry.hold_note)

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
            runtime.set_notes(entry.inhale_note, value, entry.hold_note)

    def set_hold_number(self, uuid: str, value: int) -> None:
        """Set this device's hold note (or CC number).  0 means silent."""
        entry = self.registry.get(uuid)
        if entry is None:
            return
        self.registry.set_hold_note(uuid, value)
        runtime = self._runtimes.get(uuid)
        if runtime is None:
            return
        if entry.cc_mode:
            runtime.set_hold_cc(value)
        else:
            runtime.set_notes(entry.inhale_note, entry.exhale_note, value)

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
            device_cfg = make_device_config(
                self._config,
                entry.inhale_note,
                entry.exhale_note,
                hold_note=entry.hold_note,
            )
            self._runtimes[uuid] = DeviceRuntime(device_cfg, self._midi_sink)
            with self._lock:
                self._waveform_bufs[uuid] = deque(maxlen=_WAVEFORM_MAXLEN)
        print(
            f"Device connected: {uuid} | "
            f"inhale: {entry.inhale_note} exhale: {entry.exhale_note}"
        )

    def _on_timeout(self, uuid: str) -> None:
        self.registry.mark_disconnected(uuid)
        # A device that stopped sending is holding a key down.  Release it here
        # or it rings until something else happens to clear it.
        runtime = self._runtimes.get(uuid)
        if runtime is not None:
            runtime.release()
        # Reuses MultiDeviceOscSource's existing 5s timeout — the browser is told
        # about the same drop-out the device grid already reacts to, rather than
        # a second timer with its own idea of when a phone is gone.
        if self._ws is not None:
            self._ws.publish_disconnect(uuid)
        print(f"Device disconnected: {uuid}")

    def _on_sample(self, sample: BreathSample) -> None:
        uuid = sample.source_id

        # Fan out to the browser first, and unconditionally.  The visualization
        # shows breathing, not MIDI: a muted or soloed-out performer still draws,
        # and a device whose runtime has not been built yet still draws.  This is
        # a dict assignment — it cannot block this thread.  See ws_server.
        if self._ws is not None:
            self._ws.publish_sample(uuid, float(sample.amp))

        # Record the raw amplitude, before any processing — a take must be
        # replayable against dials other than the ones in force right now.
        if self._recorder is not None:
            self._recorder.note(uuid, float(sample.amp))

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
