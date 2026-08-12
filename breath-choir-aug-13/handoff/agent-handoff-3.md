# breath-choir — Handoff Document

**Project**: Hive 10-Year Anniversary  
**Stack**: Python 3.11+, Dear PyGui 2.3, mido, python-osc  
**Entry point**: `Start.command` → `breath_midi/app.py`

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
iOS app  ──OSC UDP──►  MultiDeviceOscSource (port 8001)
                               │
                               ▼
                        EveryBreathHub
                        ├── DeviceRegistry   (UUID → DeviceEntry, persistent across stop/start)
                        ├── DeviceRuntime × N  (one per UUID)
                        │   ├── SignalProcessor  (smoothing, gain, deadzone)
                        │   ├── FeatureExtractor (phase detection, cycle tracking)
                        │   ├── TriggerEngine    (strategies → TriggerEvents)
                        │   │   ├── InhaleOnsetTrigger / ExhaleOnsetTrigger  (note mode)
                        │   │   ├── InhaleCcOnsetTrigger / ExhaleCcOnsetTrigger  (CC mode)
                        │   │   └── ConsistentBreathsTrigger  (gate controller)
                        │   └── MidiRouter       (TriggerEvent → mido message)
                        └── MidoMidiSink         (shared, single port, one thread)
```

The OSC receive thread is single-threaded — all `DeviceRuntime.on_sample()` calls are sequential. `DeviceRuntime` uses a `threading.Lock` to protect TriggerEngine and CC strategy mutations called from the UI thread.

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

### Trigger strategies
| File | Role |
|------|------|
| `triggers/v1/inhale_onset.py` | NOTE_ON on inhale phase entry |
| `triggers/v1/exhale_onset.py` | NOTE_ON on exhale phase entry |
| `triggers/v1/inhale_cc_onset.py` | CC message on inhale entry (mutable cc_number/value) |
| `triggers/v1/exhale_cc_onset.py` | CC message on exhale entry |
| `triggers/v1/consistent_breaths.py` | Fires NOTE_ON/NOTE_OFF when breath streak reaches N |
| `triggers/v1/sustain_cc.py` | Continuous CC proportional to breath amplitude |

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
OSC packet arrives
  └─► MultiDeviceOscSource._dispatch()
        ├─ on_new_device_cb(uuid)  →  hub._on_new_device()
        │     creates DeviceEntry (notes, color) + DeviceRuntime + waveform deque
        ├─ on_timeout_cb(uuid)     →  hub._on_timeout()
        │     marks device disconnected (entry persists in registry)
        └─ on_sample_cb(sample)   →  hub._on_sample()
              1. midi_sink.set_activity_source_id(uuid)
              2. Check mute/solo state from registry
              3. runtime.on_sample(sample, muted)
                   a. SignalProcessor → ProcessedSample
                   b. FeatureExtractor → FeatureFrame
                   c. TriggerEngine.on_frame(frame) → [TriggerEvents]
                   d. Intercept consistent_breaths events → update _gate_open
                   e. Route onset events to MidiRouter (if gate_pass and not muted)
              4. Append sample.amp to waveform deque

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
    inhale_note: int        # also used as CC number in CC mode
    exhale_note: int
    display_order: int
    color: tuple[int, int, int]   # golden-ratio hue, stable per UUID
    name: str               # defaults to uuid[:15], user-editable
    muted: bool = False
    soloed: bool = False    # exclusive: soloing one un-solos all others
    cc_mode: bool = False   # Note onset vs CC onset
    cc_value: int = 127     # CC value fired in CC mode
    cons_n: int = 3         # consistent breath streak target (0 = gate off)
    cons_tolerance: float = 0.30  # period + peak tolerance (single knob)
```

Mutations always use `dataclasses.replace()` — the dataclass is frozen and immutable.

---

## Note assignment

Devices are assigned F#maj7 note pairs in order of first connection:

```python
_DEVICE_NOTE_PAIRS = [
    (54, 58),   # F#3 / Bb3
    (61, 65),   # Db4 / F4
    (73, 77),   # Db5 / F5
    (85, 89),   # Db6 / F6
    (97, 101),  # ...
    (109, 113),
]
# Beyond 6 devices, wraps with +12 octave offset per full cycle
```

`inhale_note` = the note fired on inhale (or CC number in CC mode).  
`exhale_note` = the note fired on exhale.

---

## Consistent breaths gate

`ConsistentBreathsTrigger` tracks a rolling streak of breaths whose `period_s` and `peak_amp` fall within tolerance of rolling averages. It fires:
- `NOTE_ON` (kind) once when streak ≥ N → `DeviceRuntime._gate_open = True`
- `NOTE_OFF` once when streak drops → `DeviceRuntime._gate_open = False`

These events are **never routed to MIDI** — they only update `_gate_open`.

Onset triggers (inhale/exhale, note or CC) only fire when:
```python
gate_pass = (cons_n == 0) or self._gate_open
```

`N = 0` disables gating entirely — MIDI always fires.  
Gate starts `True` (open) so MIDI fires immediately until consistency is lost.

The gate dot in the Group Breath strip panel: green = open, gray = closed.

---

## Output modes per device

| Mode | Trigger on inhale | Trigger on exhale |
|------|-------------------|-------------------|
| **Note** (default) | `NOTE_ON` → `inhale_note` | `NOTE_ON` → `exhale_note` |
| **CC** | `CC` → cc_number=`inhale_note`, value=`cc_value` | `CC` → cc_number=`exhale_note`, value=`cc_value` |

Switching to CC mode via the "Note/CC" toggle button immediately syncs `inhale_note`/`exhale_note` as the CC numbers, so the displayed In#/Ex# values always match what is sent.

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

`stop_listening()` closes the MIDI sink AND clears `_runtimes` + `_waveform_bufs` so that reconnecting devices always get fresh pipelines pointing at the new sink.

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

## Known constraints / gotchas

- **Single OSC thread**: all `DeviceRuntime.on_sample()` calls are sequential. If per-device threads are ever introduced, the shared `MidoMidiSink` needs a lock or per-device sinks.
- **mido port lifecycle**: `stop_listening()` always closes the sink. Opening the same port name again on `start_listening()` works reliably; leaving it open across stop/start can produce stale handles.
- **Sustain CC excluded from Every Breath**: `DeviceRuntime` is intentionally limited to onset triggers. Sustain CC is single-device only (Single Breath tab).
- **DPG 2.3**: `add_item_drop_callback` does not exist. Drag-to-reorder was replaced with `^`/`v` buttons (not currently exposed in Group Breath). `resizable_y` on child_window works for the plot/panel split.
- **`cons_n` passed to ConsistentBreathsTrigger as `max(1, n)`**: the trigger itself doesn't handle n=0, so the runtime handles the bypass at the routing level.
