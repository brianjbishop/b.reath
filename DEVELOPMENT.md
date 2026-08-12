# Development History

All design work happened in [Claude Code](https://claude.ai/claude-code)
(Anthropic's CLI coding agent). Each session produced a set of `handoff/*.md` docs
inside the iteration folder — Claude-to-Claude context documents that capture what
was implemented, how the algorithms work, and what edge cases were discovered.
The timeline below is the narrative layer on top of those docs.

---

## stop-and-let-the-rose-smell-v1 — April 2026

First named piece, built for a live performance.

Starting from Avery Bedows' TOTEM receiver prototype, I built a full signal
processing and MIDI triggering pipeline around it:

**Signal pipeline**
- EMA smoothing + soft deadzone on raw breath amplitude
- Slope-first phase FSM: inhale/exhale detected from amplitude *derivative*,
  not amplitude level — so irregular breath depths still trigger consistently
- Phase must dwell for `min_phase_ms` before a transition is accepted, preventing
  rapid chattering at phase boundaries

**Triggering**
- `InhaleOnsetTrigger` / `ExhaleOnsetTrigger`: fire a MIDI NOTE_ON on phase entry,
  debounced
- `ConsistentBreathsTrigger`: a gate that only passes MIDI after N consecutive breaths
  whose period and peak amplitude are within tolerance of rolling averages — prevents
  accidental triggers during warmup or irregular breathing at the start of a set
- `send_note` toggle: option to emit the consistent-breath gate event as its own MIDI
  note, useful for triggering a distinct sound when the gate opens

**UI / setup**
- Tab activity manager: explicit per-tab circle indicator toggle; mutual exclusion
  between tabs; all-notes-off (CC 123) fires on all 16 channels before any switch
- QR code popup: performers scan to connect their TOTEM app to the correct Wi-Fi
  IP and port — no manual IP entry

**Key bugs fixed during development**
- *BLE mode selector invisible*: the show/hide logic was reading `input_mode` from
  the last received sample, not from the config. During a mode switch the two diverge.
  Fix: read `self.runtime.config.input.mode` directly in `tick()`.
- *BLE streaming silent after connect*: Single Breath wasn't auto-activating on launch,
  so the BLE event loop never started. Fix: auto-activate on app open.
- *MIDI doesn't stop on disconnect*: added a 3-second timeout — if no breath sample
  arrives for 3s, fire CC 123 all-notes-off. Short dropouts don't interrupt; sustained
  silence does.

---

## stop-and-let-the-rose-smell-v2 — April/May 2026

Same MIDI pipeline; added a browser-side real-time visualization.

**rose-breath** (`rose_breath/index.html`) is a p5.js sketch:
- One petal per performer, filling the full circumference of a circle
- Petal width uses `sin(π/n)` — automatically fits the available angular gap
  regardless of performer count (2 performers → 2 wide petals; 8 → 8 narrow ones)
- Petal length grows and shrinks with breath amplitude each frame
- Colors assigned via the golden-ratio conjugate: each UUID gets a stable, visually
  distinct hue that doesn't repeat for the first ~20 devices

**osc_ws_bridge.py** sits between the phones and the rest of the system:
- Receives OSC from phones on UDP 8001
- Forwards each packet to the Python MIDI app via loopback UDP
- Pushes data to the browser via WebSocket on TCP 8765

This lets the MIDI instrument and the browser visualization both receive live breath
data simultaneously from a single OSC stream, without either knowing about the other.

---

## breath-choir — April/May 2026

Multi-performer expansion, built for the Hive 10-Year Anniversary performance.

**Every Breath tab** — per-device MIDI cards
- `DeviceRegistry`: session-persistent UUID → color/note/name mapping. Devices keep
  their assignment across stop/start cycles so the display doesn't shuffle mid-show.
- F#maj7 note pairs by connection order: (54, 58), (61, 65), (73, 77)…
  inhale → lower note of the pair, exhale → upper note
- Per-device cards: waveform plot, inhale/exhale phase indicators, mute/solo buttons,
  editable note numbers, ↑/↓ reorder
- Timeout without removal: a device going quiet turns indicators white and freezes
  the waveform; reconnection restores all settings automatically

**Group Breath tab** — shared view for coordinated performance
- Shared waveform plot: all devices on the same axes, each line colored by device
- Per-device bottom strip: mute/solo, note/CC mode toggle, consistent-breath N and
  tolerance controls, in/ex number inputs
- Breath guide animation: completely independent of incoming OSC data — pulsing
  circle driven by a local timer, BPM control, configurable inhale/exhale beat counts.
  Used by the performer as a visual metronome.
- CC mode: switch any device from note-on triggers to CC messages — same in/ex numbers
  are used as CC numbers; a separate CC value knob sets the message value

**Key bugs fixed during development**
- *Crash on first OSC packet*: `add_item_drop_callback` doesn't exist in DPG 2.3.
  The drag-to-reorder cards feature was removed; replaced with ↑/↓ buttons.
- *Devices connect but cards never appear*: phones were sending to the cached port 8000
  from a previous QR scan. Added trace prints through the full receive path to pinpoint
  the break. Fix: scan the Every Breath QR fresh after any port change.
- *Waveform flickering*: line series color was being reset every frame via
  `configure_item`. Fix: color set once at card creation via `bind_item_theme`.
- *Tab switching crashes*: mido port must be fully closed before reopening.
  `stop_listening()` now always closes the sink; `start_listening()` opens a fresh one.

---

## breath-beat — May 2026

A rhythm-focused piece on top of breath-choir.

**Breath Beat tab** — isolated copy of Group Breath
- Full independent pipeline: `BreathBeatHub` with its own `DeviceRegistry` and
  `MidoMidiSink`, completely separate from `EveryBreathHub`
- All DPG tags use `bb_` prefix throughout to avoid collision with Group Breath's
  `gb_` namespace (Dear PyGui has a single global tag namespace per process)
- Single Breath is independent; Every Breath / Group Breath / Breath Beat share port
  8001 and are mutually exclusive — only one can listen at a time

**Per-device MIDI channels**
- `DeviceEntry` gains a `midi_channel` field; `DeviceRuntime` and `MidiRouter` gain
  an optional `midi_channel` override
- Devices auto-assigned to channels 1–4 in rotation as they connect
- Manual override via "Ch:" input in each device strip; takes effect immediately
- `MidiRouter` resolves channel as `(override - 1)` when set, or `cfg.midi.channel`
  when not — keeps backward compatibility with Single Breath and Every Breath

**Gate disabled**
- `cons_n=0` is set on every new device in `BreathBeatHub._on_new_device()`
- At `cons_n=0`, `DeviceRuntime.on_sample()` bypasses the gate check entirely —
  every inhale/exhale fires MIDI immediately, no consistency requirement
- The ConsistentBreathsTrigger machinery still exists but is skipped at the routing
  level, not removed, so the UI controls remain available

**MIDI channel indexing fix**
- Bug: setting channel to 1 in the UI caused Ableton to receive on channel 2
- Root cause: UI/registry store 1–16 (human-readable); mido protocol is 0-indexed
- Fix: `MidiRouter` subtracts 1 when an explicit override is set. The fallback path
  (`cfg.midi.channel`) was already 0-indexed and is unchanged.

---

## breath-choir-v2 — August 2026

Forked from breath-choir (not breath-beat) to refine **performance mechanics** rather
than add another tab. Fork is a verbatim copy; the work below is planned, not built.

**Four-phase breath cycle — inhale → hold → exhale → hold**

The current detector cannot see a breath hold. `FeatureExtractor` already computes a
smoothed derivative and already tests for flatness (`is_flat_enter` / `is_flat_stay`,
driven by `slope_rest_abs`), but the only flat state, `Phase.REST`, *also* requires
low amplitude:

```python
if is_low_enter and is_flat_enter:
    return Phase.REST
```

A hold at the top of an inhale is flat but **high** amplitude, so it falls through and
stays `INHALE` — there is no state to assign an action to.

- Split the flat state by amplitude: `HOLD_FULL` (flat + high, after inhale) and
  `HOLD_EMPTY` (flat + low, after exhale). Keep `REST` distinct from `HOLD_EMPTY` so
  an idle device doesn't fire a hold action.
- Add a minimum hold duration separate from `min_phase_ms` (120 ms is far too short —
  the natural flat moment at a breath's turnaround would read as a deliberate hold).
- Cycle completion currently keys off `REST/EXHALE -> INHALE`; the period math needs
  revisiting once the states change.
- Four assignable states, not two: this reaches `DeviceEntry`, the router, and the
  device cards, not just the FSM.

**Rhombus phase UI** — replace the two-state inhale/exhale indicator with a four-point
figure, one vertex per phase, lit as the FSM enters it. Makes box breathing legible at
a glance.

**Dummy-data mode** — port the pattern from
`stop-and-let-the-rose-smell-v2/rose_breath/dummy_data.js`, which already defines six
synthetic performers including a `'box'` shape (inhale/hold/exhale/hold). That is
exactly the signal the four-phase FSM needs, so this lands *before* the FSM work.
Injection point is the `BreathInputSource` ABC in `input/base.py`: a `DummyBreathSource`
emitting synthetic `BreathSample`s exercises device registration, colors, timeout
fade-out, and MIDI through the unchanged path — including one performer that drops out.

**Port map** — the rose visualization and the MIDI app currently collide.
`osc_ws_bridge.py` binds 8001 (phones), 8765 (browser WS), and forwards to 8002, but
Every Breath / Group Breath / Breath Beat also listen on 8001, and `config.toml` is set
to 8000 — a third value matching neither. Settle one map across the bridge,
`config.toml`, and the wifi-qr generator, and document it.

---

## Key design decisions

| Decision | Rationale |
|---|---|
| Slope-first phase detection | Amplitude level varies between performers; derivative is more universal |
| Single OSC receive thread | No lock needed on the shared MIDI sink; all DeviceRuntime calls are sequential |
| Frozen dataclasses for DeviceEntry | UI thread reads registry concurrently; `replace()` mutations are atomic |
| `cons_n=0` bypass at routing level | ConsistentBreathsTrigger doesn't handle n=0 internally; runtime checks first |
| DPG tag isolation (`bb_` vs `gb_`) | Dear PyGui has one global tag namespace; name collisions cause silent bugs |
| `midi_channel - 1` in router only | UI and registry stay human-readable (1–16); only the send path converts |
| DeviceRegistry not cleared on stop | Device names, colors, note assignments persist across hub stop/start in a session |
| WebSocket bridge as middleware | Decouples MIDI and visualization — neither needs to know the other exists |

---

## Technical references

Each iteration folder's `handoff/` directory contains the full session design docs.
`agent-handoff-3.md` (or the highest-numbered one) is always the most current.
These cover algorithm specs, file structure maps, threading models, and known constraints.
