# b.reath

A breath-to-MIDI performance system using the [TOTEM iOS app](https://www.totem.audio/).
Performers breathe into their phones; the desktop app detects inhale/exhale phases and
fires MIDI events into Ableton in real time.

## What it is

b.reath treats breath as a musical instrument. Each performer's phone sends continuous
breath amplitude data over Wi-Fi. The system detects the direction and shape of each
breath, translates those into MIDI note or CC events, and routes them to a DAW — turning
a room full of people breathing together into a live musical performance.

## How it works

```
TOTEM iOS app  ──OSC/UDP──►  Python (breath_midi)  ──MIDI──►  DAW (Ableton)
                               │
                               ├── SignalProcessor   (smoothing, gain, deadzone)
                               ├── FeatureExtractor  (phase FSM, cycle tracking)
                               ├── TriggerEngine     (inhale/exhale → events)
                               └── MidiRouter        (events → mido messages)
```

The phase detector uses a slope-first state machine — it triggers on the *direction*
of breath (amplitude derivative), not the amplitude level, so it works reliably
across different breathing depths and styles.

## Iterations

| Folder | What it is |
|--------|-----------|
| [breath-choir-v2/](breath-choir-v2/) | In progress — performance mechanics: breath-hold detection, four-phase cycle |
| [breath-beat/](breath-beat/) | Rhythm piece — per-device MIDI channels, Breath Beat tab, gate disabled |
| [breath-choir/](breath-choir/) | Multi-performer — Every Breath + Group Breath tabs, breath guide animation |
| [stop-and-let-the-rose-smell-v2/](stop-and-let-the-rose-smell-v2/) | Adds p5.js browser visualization via OSC→WebSocket bridge |
| [stop-and-let-the-rose-smell-v1/](stop-and-let-the-rose-smell-v1/) | First named piece — consistent breath gate, QR code Wi-Fi setup |

## Requirements

- Python 3.11+
- [TOTEM iOS app](https://www.totem.audio/)
- macOS (Dear PyGui, bleak)
- A MIDI-capable DAW (tested with Ableton Live)

Dependencies per iteration are in each folder's `requirements.txt`.

## Running

```bash
cd breath-beat
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m breath_midi.app
# or: ./Start.command
```

## Development notes

See [DEVELOPMENT.md](DEVELOPMENT.md) for the story of how each iteration was built,
what problems were solved, and why key decisions were made.

Each iteration folder also contains a `handoff/` directory with technical design docs
written during development sessions.
