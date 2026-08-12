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

## breath-choir-apr-25 — April/May 2026

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

## breath-beat-may-1 — May 2026

A rhythm-focused piece on top of breath-choir-apr-25.

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

## breath-choir-aug-13 — August 2026

Forked from breath-choir-apr-25 (not breath-beat-may-1) to refine **performance mechanics**
rather than add another tab.

**Four-phase breath cycle — inhale → hold → exhale → hold**

The old detector could not see a breath hold. The only flat state, `Phase.REST`, also
required *low* amplitude, so a hold at the top of an inhale — flat but high — fell
through and stayed `INHALE`. There was no state to assign an action to.

`Phase` now has `HOLD_FULL` and `HOLD_EMPTY`. `REST` is demoted to the cold-start state:
once breathing begins the FSM never returns to it, and a device going quiet is handled
by the hub's existing device timeout.

Two things about the first design turned out to be wrong, both found by the tests:

- *Deciding the hold by amplitude doesn't work.* A shallow breather's "full" is a deep
  breather's "empty". Which hold a sustained flat resolves to is decided by the phase it
  arrives **from** — `INHALE → HOLD_FULL`, `EXHALE → HOLD_EMPTY`. The cycle order always
  holds where amplitude doesn't.
- *Slope is the wrong measure of flatness.* The derivative is EMA-smoothed, so after a
  two-second inhale it needs ~300ms to decay below any flat threshold — silently
  shortening every hold and making short holds undetectable. `_held_flat()` measures
  **amplitude excursion** over the `min_hold_ms` window instead, which has no lag. The
  tolerance is derived as `slope_rest_abs * min_hold_ms`, so the existing Detection knob
  keeps its meaning and its UI control.

The unavoidable trade-off: a deliberate hold and the turnaround of a very slow deep
breath are near-identical over a short window. `min_hold_ms` defaults to **1000ms** for
that reason, not out of caution — at 400ms a 10s-period breath reads as a hold. The
`slope_rest_abs` default dropped 0.03 → 0.015 since it now scales the hold tolerance
rather than the old low-amplitude rest test.

Also fixed in passing: the cycle clock was anchored at the first *sample* rather than the
first inhale, so the first "cycle" reported a period of one sample (~0.04s) straight into
the rolling-average EMA that the consistent-breaths gate reads. The first onset now only
anchors the cycle.

**Per-phase MIDI** — `HoldFullOnsetTrigger` / `HoldEmptyOnsetTrigger` and CC variants,
sharing a base rather than the four-way copy-paste the inhale/exhale pair uses.
`DeviceEntry` gains hold notes plus explicit enabled flags, both **off by default** —
holds are additive, so an existing Ableton set keeps its exact inhale/exhale output until
a hold is switched on. Hold notes seed from the device's own inhale/exhale numbers so
enabling one can never collide with another device's assignment.

**Rhombus phase UI** — `ui/widgets/phase_rhombus.py` replaces the two In/Ex squares with a
diamond, one vertex per phase, clockwise: inhale (left) → hold full (top) → exhale
(right) → hold empty (bottom). Used by both the Every Breath cards and the Group Breath
strips. Vertices are recoloured in place via `configure_item`, never rebuilt — the same
constraint that caused the waveform flicker bug in breath-choir-apr-25.

**Tests** — first test suite in the repo (`tests/`, pytest in `requirements-dev.txt`).
Synthetic breath signals cover the FSM, the full signal → trigger → MIDI chain against a
fake sink, and headless DPG builds of both device views. The device cards and strips are
built lazily when a phone connects, so launching the app never touches them; without
these, a bad tag would only surface mid-performance.

**Bridge absorbed into the app** — the rose visualization no longer needs a second
process. `osc_ws_bridge.py` used to sit in front as a man-in-the-middle: phones to 8001,
forward to 8002, browser on 8765. But `hub.py` also listened on 8001, and `multi_osc.py`
set `SO_REUSEADDR`, so on macOS the second bind *succeeded* and the kernel handed each
datagram to only one of the two sockets. Phones appeared to connect and then vanish; it
read as a Wi-Fi problem, not a port clash.

```
phones ──8001──►  app  ──┬── MidiRouter ──► DAW
                         └── viz/ws_server ──ws:8765──► browser
```

One process, one bind on 8001, no 8002 hop. `SO_REUSEADDR` is gone, so a real clash now
raises and the Every Breath toolbar says so instead of the app half-working.

`viz/ws_server.py` runs asyncio on its own thread. The constraint that shapes it:
`publish_sample()` is called from the OSC thread — the same thread that does signal
processing and MIDI — so it must never block, or a wedged browser would stall MIDI
mid-performance. It does no I/O and touches no event loop; it assigns one dict key.

Samples are **coalesced** rather than queued: only the newest value per device survives to
the next 60Hz broadcast tick. That is what bounds the handoff — by device count, not packet
rate — so a phone flood or a paused laptop cannot grow it. This costs nothing visually
because index.html assigns each sample to `targetValue` and lerps toward it every frame, so
a sample superseded within 16ms was never going to be drawn. Disconnects get their own
buffer so a flood cannot crowd them out, and they are emitted before samples in a tick so a
stale sample cannot resurrect a device that just dropped.

Drop-outs reuse `MultiDeviceOscSource`'s existing 5s device timeout — the browser hears
about the same event the device grid reacts to, rather than a second timer with its own
opinion. Wire format is byte-identical to the old bridge, pinned by a test, since
index.html is unchanged.

`[viz]` in config.toml holds `ws_enabled` / `ws_port` / `ws_host`. A busy WS port is
non-fatal: you lose the visualization, not MIDI.

**Three phases, gated notes** — the four-phase model collapsed to INHALE / HOLD /
EXHALE. One HOLD state, entered from either end; the rhombus still shows four vertices
and lights top or bottom by amplitude, so the cycle stays readable without the detector
inventing a distinction it cannot reliably make.

*A hold is now defined by position, not by where it came from.* It must sit inside the
peak or valley band and stay still there for `min_hold_ms`. That fixes the failure the
arrival-phase rule had: a pause halfway up an inhale used to register as a hold.

*And a hold latches.* Upstream normalisation is a rolling min/max, so holding your breath
makes the window forget the breathing that set its range and the reported value drifts
even though the performer is motionless. That drift has slope, and a slope-based exit
reads it as a fresh breath — the hold ends silently while the performer is still holding.
Exit is on **displacement** (`hold_exit_delta`) instead: drift is slow and bounded, a real
breath is neither. Measured result — a hold survives to 16s on TOTEM Live and 5s on the
older TOTEM, matching each app's window exactly. Past that the signal itself is gone.

*Notes are gates, not one-shots.* `midi/voice.py` owns one sounding note per device:
release the old, then press the new, always in that order so two phases sharing a note
retrigger rather than fall silent. At most one note is down at any instant, and that is
structural rather than emergent — four independent onset strategies could not guarantee
it. Every path that ends a phase without starting another releases: mute, solo-out,
device timeout, gate close, CC-mode switch, stop, tab switch, app exit.

Defaults changed: notes are sequential from 54 (device 1 = 54/55, device 2 = 56/57),
replacing the F#maj7 pairs, and `hold_note` is **0 = silent**, which also replaced the
per-hold enable checkboxes — the number carries it.

Two bugs found by the tests, both of which would have bitten in performance: the first
breath of every session registered as a hold, because a min/max normaliser reports
exactly 1.0 while its buffer fills (holds now wait for one completed cycle); and phase
chatter on noisy data reset the hold window before it could ever accumulate, so holds
were undetectable on real signals.

Known limits, recorded in tests rather than papered over: inhaling *deeper* from a peak
hold is invisible (the running maximum is 1.0 by definition, so doubling the roll moves
the value ~0.02), and at the default 1000ms dwell a very slow breather's turnaround does
register as a hold — `min_hold_ms` is the knob, and ~1600ms clears a 10s breath.

**Still open** — dummy-data mode.

*Dummy-data mode*: port the pattern from
`stop-and-let-the-rose-smell-v2/rose_breath/dummy_data.js`, which defines six synthetic
performers including a `'box'` shape (inhale/hold/exhale/hold). Injection point is the
`BreathInputSource` ABC in `input/base.py`: a `DummyBreathSource` emitting synthetic
`BreathSample`s exercises device registration, colors, timeout fade-out, and MIDI through
the unchanged path — including one performer that drops out. The FSM tests already use
these waveforms, so the app-level mode covers the same cases interactively.

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
| Hold resolved by prior phase, not amplitude | A shallow breather's "full" is a deep breather's "empty"; cycle order is universal |
| Hold flatness measured as amplitude excursion | The smoothed derivative lags ~300ms after a ramp, which would truncate every hold |
| Hold notes off by default | Holds are additive — an existing Ableton set keeps its exact output until opted in |

---

## Technical references

Each iteration folder's `handoff/` directory contains the full session design docs.
`agent-handoff-3.md` (or the highest-numbered one) is always the most current.
These cover algorithm specs, file structure maps, threading models, and known constraints.
