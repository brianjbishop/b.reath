# breath-choir — Handoff Document

**Project**: Hive 10-Year Anniversary  
**Stack**: Python 3.11+, Dear PyGui 2.3, mido, python-osc  
**Entry point**: `Start.command` → `breath_midi/app.py`  
**Status**: current as of 2026-09-28. Supersedes `agent-handoff.md` and `agent-handoff-2.md`.

---

## What this is

A real-time breath-to-MIDI controller for live performance. Performers breathe into iOS devices running a companion app that sends OSC packets over Wi-Fi. The desktop app receives those packets, detects inhale/exhale phases, and fires MIDI events into a DAW (Ableton).

Three operational modes live as tabs in the same window:

| Tab | What it does |
|-----|-------------|
| **Single Breath** | One performer, full signal chain config and trigger tuning |
| **Every Breath** | N performers, each gets an independent MIDI pipeline with per-device note assignment |
| **Group Breath** | Same N performers, shared breathwave plot, per-device MIDI controls, and a visual breath guide animation |

Every Breath and Group Breath share a single OSC listener (port 8001) and the same `EveryBreathHub` instance. Single Breath uses a separate pipeline on a configurable port.

---

## Architecture overview

```
iOS app  ──OSC UDP──►  MultiDeviceOscSource (port 8001) ──submit──┐
                                                                   │
track file ──► TrackPlaybackSource ──submit───────────────────────┤
                                                                   ▼
                                                            SampleFeed
                                                     (one drain thread)
                                                                   │
                                                                   ▼
                                                            EveryBreathHub
                        ├── DeviceRegistry   (UUID → DeviceEntry, persistent across stop/start)
                        ├── TrackRecorder    (optional tap: raw amplitude, before detection)
                        ├── DeviceRuntime × N  (one per UUID)
                        │   ├── SignalProcessor  (smoothing, gain, deadzone)
                        │   ├── FeatureExtractor (phase detection, cycle tracking)
                        │   ├── BreathVoice      (note mode: one key held per phase)
                        │   ├── TriggerEngine    (CC mode + consistency gate)
                        │   │   ├── BreathCcTrigger          (one controller, whole cycle)
                        │   │   └── ConsistentBreathsTrigger (gate; never sent as MIDI)
                        │   └── MidiRouter       (CC TriggerEvent → mido message)
                        └── MidoMidiSink         (shared, single port)
```

Phones and playback are two producers. Both post into `SampleFeed`, and only the drain thread calls `DeviceRuntime.on_sample()`. That keeps the hub’s single-caller assumption without locking the MIDI path. `DeviceRuntime` still takes a `threading.Lock` around trigger and voice mutations that the UI thread can make.

---

## Key files

### Entry / config
| File | Role |
|------|------|
| `breath_midi/app.py` | Wires config, hub, runtime, launches UI |
| `breath_midi/config/model.py` | Frozen dataclasses for all config (`ConfigModel`, `TriggersConfig`, etc.) |
| `breath_midi/config/store.py` | Load/save `config.toml` |
| `breath_midi/types.py` | `BreathSample`, `Phase`, `TriggerEvent`, `TriggerKind`, `FeatureFrame` |

### Single Breath pipeline
| File | Role |
|------|------|
| `breath_midi/runtime.py` | `ControllerRuntime` — OSC/BLE input → signal chain → MIDI |
| `breath_midi/signal/processor.py` | Smoothing, gain, deadzone |
| `breath_midi/signal/features.py` | Phase FSM, cycle detection, rolling stats |
| `breath_midi/triggers/engine.py` | `TriggerEngine` — runs strategies, passes `TriggerContext` |
| `breath_midi/triggers/base.py` | `TriggerStrategy` ABC, `TriggerContext` |
| `breath_midi/midi/router.py` | `MidiRouter` — dispatches `TriggerEvent` to MIDI sink |
| `breath_midi/midi/mido_sink.py` | `MidoMidiSink` — wraps mido output port, activity bus |

### Every Breath / Group Breath pipeline
| File | Role |
|------|------|
| `breath_midi/every_breath/hub.py` | `EveryBreathHub` — orchestrates all devices; owns the sink |
| `breath_midi/every_breath/registry.py` | `DeviceRegistry` + `DeviceEntry` — persistent UUID→config map |
| `breath_midi/every_breath/device_runtime.py` | `DeviceRuntime` — per-device signal→trigger→MIDI chain |
| `breath_midi/every_breath/multi_osc.py` | `MultiDeviceOscSource` — single UDP socket, routes by UUID |
| `breath_midi/feed.py` | `SampleFeed` — merges phones and playback onto one drain thread |
| `breath_midi/tracks/file.py` | Track JSON: raw samples plus the dials that were set when captured |
| `breath_midi/tracks/playback.py` | Replays a track as extra devices in the choir |
| `breath_midi/tracks/recorder.py` | Copies live raw amplitude into a take |
| `breath_midi/presets.py` | Named detection dial sets, separate from a track’s stored dials |
| `breath_midi/midi/voice.py` | `BreathVoice` — note mode, one held note per phase |

### Trigger strategies
| File | Role |
|------|------|
| `triggers/v1/inhale_onset.py` | NOTE_ON on inhale phase entry (Single Breath) |
| `triggers/v1/exhale_onset.py` | NOTE_ON on exhale phase entry (Single Breath) |
| `triggers/v1/consistent_breaths.py` | Gate only in Every/Group Breath: opens or closes, never routed to MIDI |
| `triggers/v1/sustain_cc.py` | Continuous CC. Inhale and exhale are phase-gated; `BreathCcTrigger` follows the whole cycle |
| `midi/voice.py` | Note mode for Every/Group Breath. Onset triggers are not what holds the key |

### UI
| File | Role |
|------|------|
| `ui/main_window.py` | Root DPG window, tab navigation, Single Breath controls, `tick()` loop |
| `ui/tab_activity_manager.py` | Mutual-exclusion toggle for tab circles (start/stop hub/runtime) |
| `ui/every_breath_tab.py` | EveryBreath grid — one card per device |
| `ui/group_breath_tab.py` | GroupBreath — shared plot + bottom panel + animation, horizontal layout |
| `ui/group_breath_bottom_panel.py` | Per-device strip panel (mute/solo, mode toggle, N/tol, note inputs) |
| `ui/group_breath_animation.py` | Self-contained breath guide — pulsing circle, BPM, beat counts |
| `ui/midi_activity.py` | MIDI activity visualizer (Single Breath tab) |
| `ui/qr.py` | QR popup for Wi-Fi connection info |

---

## Data flow: Every Breath / Group Breath

```
OSC packet, or a sample from TrackPlaybackSource
  └─► SampleFeed.submit_*()
        └─ drain thread
              ├─ new device  →  hub._on_new_device()
              │     creates DeviceEntry + DeviceRuntime + waveform deque
              ├─ idle tick   →  hub._sweep_timeouts()
              │     any quiet source: mark disconnected, release its note
              └─ sample      →  hub._on_sample()
                    1. Publish raw amp to the browser WebSocket (mute does not hide it)
                    2. If recording, TrackRecorder.note(uuid, raw amp)
                    3. midi_sink.set_activity_source_id(uuid)
                    4. Check mute/solo from the registry
                    5. runtime.on_sample(sample, muted)
                         a. SignalProcessor → FeatureExtractor
                         b. TriggerEngine: consistency gate, and CC streams in CC mode
                         c. Note mode: BreathVoice holds the note for the current phase
                         d. CC mode: MidiRouter sends the CC events (gate open, not muted)
                    6. Append sample.amp to the waveform deque

UI thread (60 fps):
  hub.get_ui_snapshot() → [DeviceUISnapshot]   (reads registry + runtimes)
  GroupBreathTab.update(snapshots) → refreshes plot series + bottom panel + animation
```

---

## DeviceEntry fields

```python
@dataclass(frozen=True)
class DeviceEntry:
    uuid: str
    inhale_note: int        # note in Note mode; CC number in CC mode
    exhale_note: int        # same dual use as inhale_note
    display_order: int
    color: tuple[int, int, int]   # golden-ratio hue, stable per UUID
    name: str               # defaults to uuid[:15], user-editable
    muted: bool = False
    soloed: bool = False    # exclusive: soloing one un-solos all others
    cc_mode: bool = False   # False: BreathVoice notes. True: continuous CC
    cons_n: int = 0         # consistent breath streak target (0 = gate off)
    cons_tolerance: float = 0.30  # period + peak tolerance (single knob)
    hold_note: int = 0      # 0 = the hold is silent
    breath_cc: int = 74     # the one controller CC mode sends; 0 = off
    midi_channel: int = 1   # 1-16 as a musician reads it; the wire value is channel - 1
```

Mutations always use `dataclasses.replace()` — the dataclass is frozen and immutable.

---

## Note assignment

Devices get consecutive pairs from note 54, in order of first connection:

```python
_NOTE_BASE = 54
# device 0 → 54/55, device 1 → 56/57, device N → 54 + 2N / 55 + 2N
```

An earlier F#maj7 table was removed so the registry does not bake in a chord. Harmony is the DAW’s job.

`inhale_note`, `exhale_note`, and `hold_note` are the three notes on the strip. `0` is silent. CC mode does not reuse them. It sends `breath_cc` instead.

---

## Consistent breaths gate

`ConsistentBreathsTrigger` tracks a rolling streak of breaths whose `period_s` and `peak_amp` fall within tolerance of rolling averages. It fires:
- `NOTE_ON` (kind) once when streak ≥ N → `DeviceRuntime._gate_open = True`
- `NOTE_OFF` once when streak drops → `DeviceRuntime._gate_open = False`

These events are **never routed to MIDI** — they only update `_gate_open`.

The held note and the CC streams only go out when:
```python
gate_pass = (cons_n == 0) or self._gate_open
```

`N = 0` disables gating entirely — MIDI always fires.  
Gate starts `True` (open) so MIDI fires immediately until consistency is lost.

The gate dot in the Group Breath strip panel: green = open, gray = closed.

---

## Output modes per device

The Note / CC button on each strip is the toggle. Note mode shows the three phase arrows. CC mode hides them and shows one circle and one number. That number is `breath_cc` (default 74). It follows the breath amplitude the whole way around, including the hold. The three notes are left alone, so switching back to Note restores them.

`0` is off. Range, min, max, and curve are global (`CcConfig` in the Detection panel). Output is rate-limited by `midi.cc_rate_hz` (default 30).

CC goes out on the device’s own channel. `MidiRouter` reads `cfg.midi.channel`, so `DeviceRuntime` writes the device channel into its config (1–16 on the strip, 0–15 on the wire). Notes do the same through `BreathVoice`.

In Ableton, MIDI-map a dial, switch the strip to CC, and breathe. The circle's number (74 unless you change it) is the controller, on that device's channel. During a hold the amplitude is flat, so the dial sits still.

Switching to CC mode releases any sounding note. CC has no note-off to send when you switch back.

---

## UI patterns

**Per-frame rendering** — `tick()` runs at ~60 fps (`time.sleep(0.016)`). All UI updates use `configure_item` / `set_value` / `bind_item_theme` — no delete/recreate per frame.

**Rebuild guard** — grid/strip rebuilds are gated behind a UUID-list comparison:
```python
if current_uuids == self._built_uuids:
    self._refresh_*()   # cheap: configure_item only
else:
    self._rebuild_*()   # expensive: delete + recreate
```

**Per-series color** — set once at creation via `bind_item_theme()` with `mvPlotCol_Line`. Never touched per frame. Theme tags stored in `_theme_tags` and deleted alongside their series.

**M/S buttons** — 24×24, labeled "M"/"S". Active state shown by device color background (per-device theme stored in `_device_theme_tags`), inactive = `"theme_circle_gray"`.

**DPG horizontal layout** — `width=-1` before a fixed sibling absorbs all space. Fix: put the fixed-width panel last, or use `width=-N` on the fluid panel (e.g. `width=-224` leaves 220px for the right animation column).

**DPG font** — default font cannot render Unicode (↑↓▼▶ etc.). Use ASCII only (`^`, `v`, `>`, `M`, `S`).

---

## Tab lifecycle

```
circle button click
  └─► TabActivityManager.toggle(tab_name)
        ├─ "Single Breath"  →  runtime.start() / stop()
        ├─ "Every Breath"   →  hub.start_listening() / stop_listening()
        └─ "Group Breath"   →  hub.start_listening() / stop_listening()
                               + main_window._on_group_breath_toggle()
                                 → gb_tab.stop_animation() when turning off
```

Only one tab can be active at a time (single `_active` slot in `TabActivityManager`).

`stop_listening()` releases every held note, then closes the MIDI sink and clears `_runtimes` + `_waveform_bufs` so reconnecting devices get fresh pipelines on the new sink.

`DeviceRegistry` is **not** cleared on stop/start — colors, names, notes, and ordering persist for the session.

---

## Group Breath tab layout

```
gb_container (full width/height child_window)
├── gb_header (horizontal group: title | status | QR button)
└── gb_body_row (horizontal group)
    ├── gb_main_col  (width=-224, fills remaining)
    │   ├── gb_plot_area  (resizable_y, default 400px)
    │   │   └── gb_shared_plot  (one line series per device, colored by device theme)
    │   └── gb_bottom_panel  (collapsible)
    │       └── gb_strip_container  (horizontal scroll)
    │           └── gb_strip_row
    │               └── gb_strip_{uuid} × N  (200px each)
    └── gb_anim_col  (width=220, fixed)
        └── GroupBreathAnimation widgets
```

---

## Group Breath animation

`GroupBreathAnimation` (`ui/group_breath_animation.py`) — completely independent of OSC data.

- Circle grows (blue) during inhale phase, shrinks (orange) during exhale
- Timer driven by `dt = time.monotonic()` diff, passed from `GroupBreathTab.update()`
- BPM range: 20–240, default 60
- Inhale/exhale beat counts: 1–16, default 4 each
- Beat duration: `60 / BPM × beats`
- `stop()` is public — called by `GroupBreathTab.stop_animation()` when tab toggles off

---

## Presets and tracks

Presets and a track’s stored dials are the same ten detection numbers with different meanings.

- A **preset** (`presets/*.preset.toml`, via `breath_midi/presets.py`) is a dial set you named. Loading one replaces `config.detection` and nothing else. `config.toml` still autosaves the live dials on every knob turn, which is why a preset exists.
- A **track** is a performance. The file stores raw `(t, device_index, amp)` plus the dials that happened to be set when it was captured, and each device's CC mode and controller number. Loading a track never applies the detection dials. It does restore CC mode. Timestamps are kept as recorded.
- `tracks/generated/` is committed. `tracks/recordings/` is gitignored. Recording is refused while a track is playing. An empty take writes no file.
- Playback uuids are prefixed (`pb1:<original uuid>`) so a recording does not merge with the live phone it was captured from, and so loading one track twice makes two performers.
- Tracks do not loop. When a track ends, its devices stop sending and `_sweep_timeouts` drops them and releases held notes. The timeout used to live only in the OSC source, which is why a finished track once stayed on screen holding keys.

## Known constraints / gotchas

- **One caller, two producers**: `DeviceRuntime.on_sample()` runs only on the `SampleFeed` drain thread. A new source must `submit_*` into the feed. Do not call the hub sample path from another thread.
- **Rate-limit state is per trigger context**, keyed by strategy id (`inhale_sustain_last_cc_t`, and the same pattern for the other two). Devices do not share a context. Two strategies in one test must not share one either, or they throttle each other.
- **mido port lifecycle**: `stop_listening()` releases every held note, then closes the sink and clears `_runtimes`. The registry is not cleared. Opening the same port name again on `start_listening()` is the supported path.
- **`apply_from_ui` must pass `viz`, `network`, and `cc`** when it rebuilds `ConfigModel`. Those sections have defaults, so omitting them resets the WebSocket settings, the learned router MAC, and the CC range on every knob turn.
- **DPG 2.3**: `add_item_drop_callback` does not exist. Drag-to-reorder was replaced with `^`/`v` buttons (not currently exposed in Group Breath). `resizable_y` on child_window works for the plot/panel split.
- **`cons_n` passed to ConsistentBreathsTrigger as `max(1, n)`**: the trigger itself doesn't handle n=0, so the runtime handles the bypass at the routing level. Default `cons_n` is 0 (gate off).
