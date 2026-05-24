# Agent Handoff: breath-choir (v2)

**Supersedes:** `handoff/agent-handoff.md`
**Session scope:** Every Breath tab implementation + bug fixes

---

## Mission and Vision
- Build a reliable breath-to-MIDI controller driven by TOTEM (BLE/OSC) with fast live feedback in Dear PyGui.
- Now expanding to **multi-device, multi-performer** scenarios via the Every Breath tab.
- Single Breath tab remains unchanged — single local device, single controller, single MIDI output.
- Every Breath tab tracks onset events (inhale/exhale) per performer for choir-level note triggering; continuous CC and pattern detection are intentionally excluded from this mode.
- Architecture is future-safe for multi-source expansion via `source_id` on all MIDI activity events.
- Guardrail: avoid unplanned algorithm shifts in signal/trigger logic unless explicitly requested.

---

## What Changed Since v1 Handoff

### New: Every Breath tab (full implementation)

A second top-level tab now runs a parallel, independent pipeline for multi-device OSC input. It does **not** share any runtime, port, or state with Single Breath.

**New files:**
- `breath_midi/every_breath/hub.py` — `EveryBreathHub`: orchestrates the full Every Breath pipeline (registry + OSC source + per-device runtimes + shared MIDI sink). Binds to **port 8001**.
- `breath_midi/every_breath/registry.py` — `DeviceRegistry`: session-scoped UUID → `DeviceEntry` mapping. Assigns stable per-device note pairs (inhale/exhale), golden-ratio hue colors, display order. Thread-safe.
- `breath_midi/every_breath/multi_osc.py` — `MultiDeviceOscSource`: single UDP socket on port 8001 tracking all source_ids simultaneously. Fires `on_new_device_cb`, `on_sample_cb`, `on_timeout_cb`. 5-second timeout sweep per device.
- `breath_midi/every_breath/device_runtime.py` — `DeviceRuntime`: independent `SignalProcessor → FeatureExtractor → TriggerEngine → MidiRouter` chain per UUID. Only `InhaleOnsetTrigger` and `ExhaleOnsetTrigger` run per device — all other trigger types are disabled.
- `breath_midi/ui/every_breath_tab.py` — `EveryBreathTab`: Dear PyGui grid UI. One card per connected device (max 4 columns). Cards show: device name (editable), mute/solo buttons, inhale/exhale phase indicators, per-device waveform plot. Drag-to-reorder between cards. All DPG tags are namespaced with `eb_` prefix.
- `breath_midi/ui/qr.py` — `show_qr_popup(port, app_name)`: shared QR code popup used by both tabs. Encodes `{"ip": <local_ip>, "port": <port>, "name": <app_name>}` as JSON in the QR payload. Single Breath calls it with port 8000; Every Breath calls it with port 8001.

**Modified files:**
- `breath_midi/app.py` — constructs `EveryBreathHub(config=config)` and passes it to `run_ui()`; calls `eb_hub.stop()` on exit.
- `breath_midi/ui/main_window.py` — adds "Every Breath" and "Group Breath" tabs to the top-level `tab_bar`. Wires `_on_tab_change` callback to start/stop hub on tab switch. Calls `EveryBreathTab.build()` inside the tab context. Calls `eb_tab.update()` each frame from `tick()`.

### Bug fixes applied this session

**Bug 1 — Hub never initialized on launch** (`main_window.py` lines 116–125)
- Root cause: launch-time check only called `start_listening()` if Every Breath was the *active* tab at launch, which it never is (Single Breath is the DPG default first tab).
- Fix: removed the conditional; `start_listening()` is now called unconditionally at launch when `eb_hub is not None`. The `_listening` guard inside the hub makes it idempotent, so the tab-switch callback calling it again is harmless.

**Bug 2 — Port 8000 conflict crash** (`hub.py` line 67)
- Root cause: `EveryBreathHub` was passing `self._config.input.osc_port` (value: `8000`) to `MultiDeviceOscSource`, same port as Single Breath's `OscBreathInput`. The bind raised `OSError: Address already in use` and crashed the process.
- Fix: hard-coded `8001` for Every Breath throughout — in `hub.py` (socket bind), `every_breath_tab.py` (toolbar text, QR callback, placeholder text). Single Breath remains on `8000`, untouched.
- Hub now prints `"Every Breath listening on port 8001"` to terminal on start.

**Bug 3 — DPG tag audit** (`every_breath_tab.py`)
- Audited all tagged DPG items. All tags use `eb_` prefix. No collision with Single Breath tags. No code changes required.

---

## Runtime Data Flow (Authoritative)

### Single Breath (unchanged)
`Input (BLE/OSC port 8000) → SignalProcessor → FeatureExtractor → TriggerEngine → MidiRouter → MidoMidiSink → MidiActivityBus → UI`

### Every Breath (new, parallel)
`MultiDeviceOscSource (UDP port 8001) → per-UUID DeviceRuntime (SignalProcessor → FeatureExtractor → TriggerEngine [inhale/exhale onset only] → MidiRouter) → shared MidoMidiSink → EveryBreathHub → EveryBreathTab (UI, per-frame)`

- Both pipelines share the same `MidoMidiSink` class but are **separate instances** with separate `MidiActivityBus` instances and separate MIDI sinks.
- Every Breath hub starts at app launch (not on tab click). The tab-switch callback in `main_window._on_tab_change` still calls `stop_listening()` / `start_listening()` when switching between tabs, so devices are released when the user leaves the tab.

---

## Every Breath: Device Lifecycle

1. Phone sends OSC to `0.0.0.0:8001` with address `/breath_value/<uuid>`.
2. `MultiDeviceOscSource` fires `on_new_device_cb(uuid)` on first packet.
3. `EveryBreathHub._on_new_device()` calls `DeviceRegistry.get_or_create(uuid)` → assigns stable note pair and golden-ratio hue color.
4. A `DeviceRuntime` is created for that UUID with a `ConfigModel` where only inhale/exhale onset triggers are enabled, with device-specific notes.
5. Subsequent packets route through `_on_sample_cb(sample)` → `DeviceRuntime.on_sample()`.
6. 5-second silence triggers `on_timeout_cb(uuid)` → `registry.mark_disconnected(uuid)`.
7. UI grid rebuilds only when the connected UUID list changes. Per-frame `_refresh_cards()` updates waveform plots, indicators, mute/solo labels without rebuilding.

### Note assignment scheme
- Device index 0 → inhale note 40, exhale note 41
- Device index 1 → inhale note 42, exhale note 43
- Device index N → inhale note `40 + N*2`, exhale note `40 + N*2 + 1`
- Colors: golden-ratio hue, S=0.75, L=0.55 → vivid, readable on dark background, stable across reconnects.

### Mute / Solo semantics
- Mute: `DeviceRuntime.on_sample()` receives `muted=True` → trigger events are discarded before MIDI routing.
- Solo: `DeviceRegistry.set_soloed(uuid, True)` un-solos all other devices atomically. Any device that is not soloed when any solo is active is treated as muted.

---

## File Structure (updated)

### Top Level (same as v1)
- `README.md`, `Start.command`, `config.toml`, `requirements.txt`
- `breath_midi/` — main application package
- `handoff/` — handoff documents

### `breath_midi/` (additions and changes)
- `app.py` ← **modified**: wires `EveryBreathHub`
- `ui/main_window.py` ← **modified**: 3-tab structure, hub lifecycle, `eb_tab.update()` each frame
- `ui/qr.py` ← **new**: shared QR popup
- `ui/every_breath_tab.py` ← **new**: Every Breath grid UI
- `every_breath/hub.py` ← **new**: pipeline orchestrator, port 8001
- `every_breath/registry.py` ← **new**: session-scoped device registry
- `every_breath/multi_osc.py` ← **new**: single-socket multi-device OSC listener
- `every_breath/device_runtime.py` ← **new**: per-device signal→MIDI chain

### Unchanged from v1
- `runtime.py`, `types.py`, `config/`, `input/`, `signal/`, `triggers/`, `midi/`, `ui/midi_activity.py`, `ui/window_placement.py`

---

## Port Map (canonical)
| Tab | Port | Purpose |
|---|---|---|
| Single Breath | 8000 | Single OSC device, full trigger suite |
| Every Breath | 8001 | Multi-device OSC, onset-only per device |

**Never change Single Breath's port. Never share a port between tabs.**

---

## Operational Quickstart
- `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- `python -m breath_midi.app`
- On launch: terminal prints `"Every Breath listening on port 8001"` when hub starts.
- Every Breath QR encodes `{"ip": <lan_ip>, "port": 8001, "name": "breath-choir"}`.
- Single Breath QR encodes port 8000.

---

## Algorithmic Capture: Every Breath Signal Chain

Each `DeviceRuntime` runs a full independent pipeline:

1. **`SignalProcessor`** — same gain/EMA/deadzone chain as Single Breath, using base config values.
2. **`FeatureExtractor`** — same slope-first phase machine as Single Breath (rest/inhale/exhale).
3. **`TriggerEngine`** — only `InhaleOnsetTrigger` and `ExhaleOnsetTrigger` active per device. Notes assigned by registry index at first connect. Debounce from base config.
4. **`MidiRouter`** — routes `TriggerEvent` → `NOTE_ON`/`NOTE_OFF` via shared `MidoMidiSink`.

Triggers disabled for Every Breath by design: `SustainCCTrigger`, `ConsistentBreathsTrigger`.

---

## Do / Don't Guardrails (updated)
- **Do:** keep changes localized; preserve both runtime chains independently.
- **Do:** preserve Single Breath tab behavior, port 8000, OSC listener — do not touch it when working on Every Breath.
- **Do:** namespace all new Every Breath DPG tags with `eb_` prefix.
- **Do:** preserve config compatibility when adding fields.
- **Do:** keep UI-thread safety for DPG updates.
- **Don't:** change trigger detection math or strategy semantics unless explicitly requested.
- **Don't:** add CC sustain or consistent-breaths logic to `DeviceRuntime` without explicit product approval.
- **Don't:** share a port between Single Breath and Every Breath.
- **Don't:** change `breath_midi/signal/`, `breath_midi/triggers/`, `breath_midi/midi/router.py`, or `breath_midi/midi/mido_sink.py` without explicit request.

---

## Open Edges (current)
- Every Breath hub's `stop_listening()` on tab-switch tears down all device runtimes? No — runtimes persist in `_runtimes` dict across stop/start. Devices reconnect seamlessly.
- `DeviceRuntime` uses base config signal/detection params, not per-device tuning. Per-device config editing is not implemented.
- Group Breath tab is a "Coming soon" placeholder — not yet scoped.
- Every Breath MIDI activity is not surfaced in the Single Breath MIDI visualizer or Trigger Activity log (different `MidiActivityBus` instance). If needed, a shared bus or secondary subscriber would be required.
- No persistence of device names/colors/order across sessions (`DeviceRegistry` is in-memory only).

## Ordered Backlog for Next Agent
1. Persist `DeviceRegistry` entries (name, color, note overrides, display_order) to `config.toml` or a sidecar file across sessions.
2. Add per-device note override UI in the device card or right-panel "Device detail" pane.
3. Implement "Activity" left panel for Every Breath (currently "Coming soon") — aggregate trigger event log across all devices.
4. Implement "Device detail" right panel — per-selected-device phase, waveform zoom, note config.
5. Add all-notes-off panic on `stop_listening()` to prevent stuck MIDI notes on tab switch.
6. Consider per-device signal config (gain, smoothing) if performers have different sensors.
7. Add small runtime test for `DeviceRegistry` — note assignment stability, solo/mute semantics.
8. Add test for `MultiDeviceOscSource` timeout sweep behavior.
9. Validate Group Breath concept and scope before implementation.
10. (Inherited) Add config validation/clamping for `[ui.midi_activity]` sizes and RGBA vectors.
