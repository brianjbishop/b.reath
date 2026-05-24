# Agent Handoff: breath-choir

## Mission and Vision
- Build a reliable breath-to-MIDI controller driven by TOTEM (BLE/OSC) with fast live feedback in Dear PyGui.
- Current product direction prioritizes **MIDI observability**: show what the sink actually sends, when it sends it, and which mapped notes are held.
- Current scope is intentionally narrow: **single local device, single controller, single MIDI output**.
- Architecture should remain future-safe for multi-source expansion via `source_id` on MIDI activity events.
- Guardrail: avoid unplanned algorithm shifts in signal/trigger logic unless explicitly requested.

## Canonical Context Sources
- [Rename + MIDI observability thread](eec88f03-e25e-42cc-b403-fbe3f1bb9fb0)
- [Current handoff request](c9c20d95-1c6e-4211-b952-72c89132c84c)
- `README.md`
- `config.toml`
- `.cursor/plans/breath_midi_ui_polish_02e28c3a.plan.md`
- `.cursor/plans/slope-based_phase_detection_01ee0695.plan.md`

## Current Implementation Status
- **Implemented:** `MidiActivityBus` event model + queue + subscriber list in `breath_midi/midi/activity_bus.py`.
- **Implemented:** sink emits activity events from real sends in `breath_midi/midi/mido_sink.py`.
- **Implemented:** MIDI activity visualizer UI component in `breath_midi/ui/midi_activity.py`.
- **Implemented:** Trigger Activity panel interleaves trigger lines with sink NOTE lines in `breath_midi/ui/main_window.py`.
- **Partial by design:** textual sink log integration in Trigger Activity currently focuses on `note_on`/`note_off`; not a full all-event text log for CC/system traffic.

## Runtime Data Flow (Authoritative)
`Input (BLE/OSC) -> SignalProcessor -> FeatureExtractor -> TriggerEngine -> MidiRouter -> MidoMidiSink -> MidiActivityBus -> UI`

- Input sources created in `breath_midi/runtime.py` (`_make_input`) and implemented in `breath_midi/input/ble_source.py` + `breath_midi/input/osc_source.py`.
- Breath samples are transformed in `breath_midi/signal/processor.py`, then framed in `breath_midi/signal/features.py`.
- Trigger strategies execute via `breath_midi/triggers/engine.py` + `breath_midi/triggers/v1/*`.
- Trigger events route to output in `breath_midi/midi/router.py`.
- Sink writes MIDI via `mido` in `breath_midi/midi/mido_sink.py` and publishes mirrored activity events.
- UI (`breath_midi/ui/main_window.py`) polls runtime state and drains MIDI bus each frame, updating monitor/plot/log/visualizer.

## Algorithmic Capture: What Is Measured and How Decisions Are Made

This section complements the file map with concrete behavior of the runtime math/state machine.

### Input Capture (`BreathSample`)
- **OSC** (`breath_midi/input/osc_source.py`):
  - Expects UDP OSC addresses starting with `/breath_value/`.
  - Uses the first OSC argument as breath amplitude (`amp`, float).
  - Uses the final address segment as `source_id`.
  - Computes `t` from local monotonic elapsed time since first packet in session.
- **BLE** (`breath_midi/input/ble_source.py`):
  - Expects notify payload with UUID bytes + timestamp bytes + breath float.
  - Parses `breath_value` from bytes 24:28 as big-endian float.
  - Uses parsed UUID as `source_id`.
  - Re-times `t` locally from monotonic elapsed time since first notify for stable downstream timing.

### Signal Processing (`SignalProcessor` in `breath_midi/signal/processor.py`)
For each incoming sample:
1. Apply gain: `amp = amp_raw * signal.gain`.
2. Apply EMA smoothing (`signal.smoothing_alpha`).
3. If baseline tracking is enabled, baseline EMA is updated but not subtracted from the signal (tracking-only behavior).
4. Apply soft deadzone for `0 <= amp < deadzone`: `amp = (amp * amp) / deadzone`.
5. Clamp to `[0, 1]` and emit `ProcessedSample.amp_proc`.

### Feature Extraction (`FeatureExtractor` in `breath_midi/signal/features.py`)
Each frame emits:
- `amp`: processed amplitude (`amp_proc`).
- `d_amp`: finite-difference derivative `delta_amp / delta_t`, optionally EMA-smoothed (`detection.derivative_smoothing_alpha`).
- `phase`: one of `rest | inhale | exhale`.
- `phase_changed`, `phase_entered`.
- `cycle_completed`, `cycle` (`period_s`, `peak_amp`) when a cycle boundary is detected.
- `rolling` averages (`avg_period_s`, `avg_peak_amp`).

### Phase Logic (Slope-First State Machine)
The phase machine uses:
- `rest_enter_amp`, `slope_enter_abs`, `slope_rest_abs`, `hysteresis`, `min_phase_ms`.
- Enter/stay threshold bands derived from hysteresis.
- Minimum phase dwell (`min_phase_ms`) to prevent rapid phase chatter.

Behavioral intent:
- From `rest`, sufficient positive slope enters `inhale`; sufficient negative slope enters `exhale`.
- Low-amplitude + low-slope conditions return active phases to `rest`.
- Cycle boundaries are defined by phase transitions, not fixed windows.

Important implementation note:
- `inhale_enter_amp` and `exhale_enter_amp` exist in config/UI schema, but current `FeatureExtractor._next_phase` does not consume them directly.

### Cycle and Rolling Metrics
- Peak is tracked continuously within a cycle segment.
- A cycle is marked complete on transition to `Phase.INHALE` (`REST/EXHALE -> INHALE`).
- Completed cycle metrics:
  - `period_s = t_now - cycle_start_t`
  - `peak_amp = max amp observed in previous segment`
- Rolling metrics are EMA averages (alpha fixed to `0.2` in code) of cycle period and cycle peak.

### Trigger Semantics (Per Feature Frame)
- **Inhale onset** (`triggers/v1/inhale_onset.py`): emit `NOTE_ON` on phase entry to inhale, debounced by `debounce_ms`.
- **Exhale onset** (`triggers/v1/exhale_onset.py`): emit `NOTE_ON` on phase entry to exhale, debounced by `debounce_ms`.
- **Sustain CC** (`triggers/v1/sustain_cc.py`):
  - Active only while frame phase matches the trigger phase.
  - Maps `amp` (0..1) through linear/gamma curve to `[min_value, max_value]`.
  - Rate-limited by `midi.cc_rate_hz`.

### Breath Consistency: Algorithmic Definition (`triggers/v1/consistent_breaths.py`)
Consistency is evaluated on completed breath cycles (not raw waveform smoothness):

Preconditions:
1. Strategy enabled.
2. `frame.cycle_completed` and `frame.cycle` available.
3. Rolling averages exist (`avg_period_s`, `avg_peak_amp`).
4. Completed-cycle warmup counter reaches `min_cycles_before_eval`.

Tolerance checks on each completed cycle:
- `ok_period = within_tol(cycle.period_s, avg_period, period_tol_kind, period_tol_value)`
- `ok_peak = within_tol(cycle.peak_amp, avg_peak, peak_tol_kind, peak_tol_value)`

`within_tol` behavior:
- `relative`: `abs(value - avg) <= abs(tol) * avg`
- otherwise (absolute): `abs(value - avg) <= abs(tol)`

Streak and note behavior:
- If both checks pass, increment `consistent_streak`; else reset to `0`.
- When `streak >= n`, emit one `NOTE_ON` and hold logical key.
- While held, no repeated `NOTE_ON` is emitted.
- On subsequent inconsistency, emit `NOTE_OFF` and clear hold.
- If trigger is disabled while held, emits immediate `NOTE_OFF` and resets state.

## First-Party File Structure

### Top Level
- `README.md` - setup, runbook, protocols, dependencies.
- `Start.command` - macOS launcher (`cd` script dir, activate `.venv`, run app module).
- `config.toml` - persisted runtime + UI + midi-activity appearance settings.
- `requirements.txt` - Python dependencies.
- `totem_ble_viewer.py` - standalone Dear PyGui breath monitor utility.
- `totem_breath_viz.py` - separate visualization utility script.
- `breath_midi/` - main application package.
- `.cursor/plans/` - planning artifacts and decision context.
- `handoff/` - this handoff package.

### `breath_midi/`
- `app.py` - app entrypoint and top-level wiring.
- `runtime.py` - orchestration loop/state lifecycle.
- `types.py` - shared dataclasses/enums.
- `config/model.py` - config schema dataclasses.
- `config/store.py` - TOML load/save/default compatibility.
- `input/base.py` - input interface.
- `input/ble_source.py` - BLE ingest.
- `input/osc_source.py` - OSC ingest.
- `signal/processor.py` - smoothing/baseline/gain/deadzone.
- `signal/features.py` - derivative/phase/cycle feature extraction.
- `triggers/base.py` - trigger strategy contract.
- `triggers/engine.py` - strategy execution hub.
- `triggers/v1/inhale_onset.py` - inhale note trigger.
- `triggers/v1/exhale_onset.py` - exhale note trigger.
- `triggers/v1/sustain_cc.py` - sustain CC trigger.
- `triggers/v1/consistent_breaths.py` - consistent-cycle note trigger.
- `midi/base.py` - MIDI sink interface.
- `midi/router.py` - `TriggerEvent` -> MIDI routing.
- `midi/mido_sink.py` - concrete MIDI output sink.
- `midi/activity_bus.py` - pub/sub-style MIDI activity bus.
- `ui/main_window.py` - primary Dear PyGui window/controller.
- `ui/midi_activity.py` - MIDI activity visualizer widget/controller.
- `ui/window_placement.py` - viewport placement helpers.

## Operational Quickstart for Next Agent
- Setup:
  - `python3 -m venv .venv`
  - `source .venv/bin/activate`
  - `pip install -r requirements.txt`
- Run main app:
  - `python -m breath_midi.app`
- Alternative run:
  - `.venv/bin/python -m breath_midi.app`
- Launcher:
  - `chmod +x Start.command` then run `Start.command`.
- Validate MIDI observability quickly:
  - ensure a valid MIDI out port in `config.toml` (`[midi].out_port`),
  - trigger inhale/exhale/consistent events,
  - verify Trigger Activity interleaves trigger and NOTE ON/OFF lines,
  - verify visualizer held indicators and velocity bars update.

## Config Notes That Matter
- `controller_id` is used as source identity context.
- Detection includes slope-first parameters (`slope_enter_abs`, `slope_rest_abs`) plus hysteresis/min duration controls.
- UI state persists in `[ui]` (`window_*`, panel visibility flags).
- MIDI visualizer appearance persists in `[ui.midi_activity]` (`held_*_rgba`, `velocity_bar_h`, `cc_bar_h`, `show_note_name`).

## Do / Don't Guardrails
- **Do:** keep changes localized and preserve the runtime chain (`input -> signal -> triggers -> midi -> ui`).
- **Do:** preserve existing config compatibility when adding fields (`config/store.py` defaults).
- **Do:** keep UI-thread safety for DPG updates when consuming bus events.
- **Don't:** change trigger detection math or strategy semantics unless explicitly requested.
- **Don't:** couple UI logic to concrete trigger strategy classes; prefer config-derived note/CC mapping.
- **Don't:** include `.venv` or vendor artifacts in structural or implementation decisions.

## Open Edges (Inherited)
- Clarify startup behavior parity: auto-start on launch vs explicit Start click.
- Decide policy for panic/all-notes-off behavior on stop/reload in sink lifecycle.
- Define debounce strategy for frequent viewport persistence writes.
- Confirm event ordering clock policy for mixed trigger + sink log interleave.
- Define behavior for duplicate note mappings across enabled triggers.

## Ordered Backlog for Next Agent
1. Add/verify small runtime test harness for `MidiActivityBus` publish/drain/order behavior.
2. Add focused unit tests for note-map filtering used by Trigger Activity and visualizer.
3. Add regression checks for reload/session reset to ensure no stale subscriptions or duplicate log lines.
4. Verify `mido_sink` lifecycle behavior on stop/reload, including optional panic policy decision.
5. Tighten Trigger Activity formatting consistency (timestamps, labels, source tagging) without increasing noise.
6. Add minimal diagnostics toggle for optional CC/system textual lines if needed for debugging sessions.
7. Add config validation/clamping for `[ui.midi_activity]` sizes and RGBA vectors.
8. Document a fast QA script in `README.md` for end-to-end MIDI observability checks.
9. If requested, introduce lightweight tests around `window_placement` and UI state persistence.
10. Keep multi-source readiness scoped to event metadata (`source_id`) without implementing multi-source routing yet.
