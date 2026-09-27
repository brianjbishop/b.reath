# Breath Tracks — design

2026-09-27

## Why

Tuning detection needs the same breath twice. Today every test needs phones, a
room, and people, and no two runs are alike — so when a dial changes it is never
clear whether the difference came from the dial or from the breathing. The
retracement rewrite shipped on simulation alone for exactly this reason.

A track is a saved breath performance that replays through the real chain, so a
dial change becomes the only variable.

## What a track is

Two halves in one file: the breath data, and the dials in effect when it was
captured.

The governing analogy is Ableton: **the track is the clip, the dials are the
instrument.** A clip records which instrument it was made with, but dropping it
in does not reconfigure your instrument.

## The principle the format turns on

**Store what the phone sent. Never store what the detector concluded.**

A phone sends exactly one thing — `/breath_value/<uuid>` carrying a float. The
app adds an arrival time. That is the whole input: `t`, `uuid`, `amp`.
Everything downstream (smoothed amplitude, derivative, phase, cycle period,
MIDI) is derived by `SignalProcessor` -> `FeatureExtractor` -> `BreathVoice`.

If phases were baked into the file, turning a dial would change nothing on
playback and the track would be useless for the one job it exists to do.
Storing only raw input makes every playback a fresh detection run: same breath,
different dials, directly comparable.

## File format

One track per file, `*.breath.json`, in a `tracks/` data folder beside
`config.toml`. (The code lives in the `breath_midi/tracks/` package — different
thing, same word.)

```json
{
  "version": 1,
  "name": "Box breathing — 4 performers",
  "created": "2026-09-27T14:30:00",
  "duration_s": 120.0,
  "source": "recorded",
  "detection": { "inhale_exit_delta": 0.06, "exhale_exit_delta": 0.12, "...": "all 10 fields" },
  "devices": [
    { "uuid": "abc-123", "name": "Ana", "color": [220, 120, 90], "inhale_note": 54, "exhale_note": 55 }
  ],
  "samples": [[0.000, 0, 0.412], [0.020, 0, 0.418], [0.021, 1, 0.233]]
}
```

- `samples` are `[t, device_index, amp]`. The index points into `devices`, so
  names and colours live in one place and the sample list stays compact.
- `t` is seconds from track start, as recorded. **Not resampled to a fixed
  grid** — the hold detector's stillness window is measured in time, so
  regularising arrival gaps would quietly change which holds register.
- `source` is `"recorded"` or `"generated"`, for display only.
- `detection` is provenance. The detector uses whatever is currently set.

Size: 50 Hz x 6 devices x 10 min is roughly 5 MB of JSON. Chunky but inspectable
and diffable, which beats a binary format at this scale.

## Components

**`breath_midi/tracks/file.py`** — read and write a track, validate on load (version, device
indices in range, timestamps non-decreasing). Rejects a malformed file with a
clear message rather than half-loading it.

**`breath_midi/tracks/playback.py`** — `TrackPlaybackSource`. Replays samples on a thread at
their recorded offsets, entering the hub through the same three callbacks as
`MultiDeviceOscSource` (`_on_sample`, `_on_new_device`, `_on_timeout`). Because
it uses the identical seam, device registration, colours, MIDI, WebSocket
fan-out and the 5-second device timeout all exercise unchanged. Supports stop
and loop.

**`breath_midi/tracks/recorder.py`** — `TrackRecorder`. Taps the same sample flow and
appends `(t, uuid, amp)`. On stop, writes the file with the dials currently set
and the device table as it stood.

**`scripts/bake_tracks.py`** — turns the six rose performer definitions
(Slow & Deep, Fast & Shallow, Irregular, Box Breathing, and the dropout one)
into real track files using the `sine` / `box` / `ramp` shapes already written
and tested in `tests/test_phase_fsm.py`. Output is an ordinary track file, so
generated and recorded tracks load through one path and there is no separate
"dummy mode" branch to rot.

## Source exclusivity

The hub has exactly one source at a time: OSC or playback. Starting playback
while the OSC listener is bound stops the listener first, and vice versa. This
mirrors the existing mutual exclusion between Every Breath and Group Breath and
avoids two sources racing on the same device registry.

Recording is a tap, not a source. It is available while the OSC listener is
live and disabled during playback — recording a playback would only produce a
lossy copy of a file that already exists.

## UI

The two placeholder tray icons in the Group Breath right column become real:

- **import** — file dialog, load a track
- **export** — save the last recording

Added alongside: a **record** toggle and a **play/stop** control, plus the
loaded track's name and a **Restore dials** button that applies the track's
stored `detection` block.

Loading a track does **not** touch the current dials. That is the Ableton rule
above, and it keeps the bench stable while A/B-ing a dial against fixed breath.

## Testing

- round trip: write a track, read it back, samples and metadata identical
- validation: truncated file, bad device index, out-of-order timestamps each
  rejected with a message
- playback enters the hub through the same callbacks, and device registration
  and colours match the file
- a gap in timestamps fires the existing 5-second timeout and fades the device
- loading a track leaves `config.detection` unchanged; Restore applies it
- a generated box-breathing track produces the phase sequence the FSM tests
  already assert for that shape — the bake path and the test generators agree

## Staging

**Stage 1** — format, playback, bake script, load/play UI. Usable with no
phones.

**Stage 2** — recording: the tap, the record control, export.

Recording is small once the format exists, but Stage 1 is independently useful,
so it ships first.

## Out of scope

Editing or trimming tracks, layering several at once, audio of any kind, and
any change to the OSC protocol or the iOS apps.
