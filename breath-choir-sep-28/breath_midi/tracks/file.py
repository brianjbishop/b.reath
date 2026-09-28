"""
Track files: a saved breath performance.

A track stores what the phones sent — a time, which device, an amplitude — and
nothing the detector made of it.  Phase, derivative, cycle metrics and MIDI are
all derived downstream by SignalProcessor -> FeatureExtractor -> BreathVoice.
Baking any of that in would mean turning a dial changed nothing on playback,
which is the one job a track exists to do.  Raw input only makes every playback
a fresh detection run: same breath, different dials, directly comparable.

`detection` records the dials in effect when the track was captured.  It is
provenance, not instruction — loading a track never changes your dials.  The
track is the clip; the dials are the instrument.

Timestamps are stored as recorded and are never resampled onto a fixed grid.
The hold detector measures stillness in *time*, so regularising arrival gaps
would quietly change which holds register — a track cleaned up that way would
lie about the very dials it exists to test.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from breath_midi.config.model import DetectionConfig

VERSION = 1


@dataclass(frozen=True)
class TrackDevice:
    uuid: str
    name: str
    color: tuple[int, int, int]
    inhale_note: int
    exhale_note: int
    # Everything below is optional on read, so a track written before any of
    # these fields existed still loads.  A field that only adds information
    # needs no version bump.
    midi_channel: int = 1          # 1-16
    hold_note: int = 0             # 0 = the hold plays nothing
    cons_n: int = 0                # 0 = consistency gate off
    cons_tolerance: float = 0.30


@dataclass(frozen=True)
class Track:
    name: str
    created: str
    duration_s: float
    source: str                                   # "generated" | "recorded"
    detection: DetectionConfig
    devices: list[TrackDevice]
    samples: list[tuple[float, int, float]]       # (t, device_index, amp)


def write_track(path: Path, track: Track) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": VERSION,
        "name": track.name,
        "created": track.created,
        "duration_s": round(float(track.duration_s), 3),
        "source": track.source,
        "detection": asdict(track.detection),
        "devices": [
            {
                "uuid": d.uuid,
                "name": d.name,
                "color": list(d.color),
                "inhale_note": d.inhale_note,
                "exhale_note": d.exhale_note,
                "midi_channel": d.midi_channel,
                "hold_note": d.hold_note,
                "cons_n": d.cons_n,
                "cons_tolerance": round(float(d.cons_tolerance), 4),
            }
            for d in track.devices
        ],
        # Milliseconds and four decimals of amplitude.  Phones send far coarser
        # data than that, and full float repr would double the file for noise.
        "samples": [[round(t, 3), i, round(a, 4)] for t, i, a in track.samples],
    }
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def read_track(path: Path) -> Track:
    """
    Load and validate a track.

    Every failure raises ValueError with a message naming the problem.  A
    half-loaded track would surface as baffling behaviour mid-performance,
    which is a far worse way to find out the file was wrong.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name}: not valid JSON ({exc})") from exc

    if raw.get("version") != VERSION:
        raise ValueError(
            f"{path.name}: unsupported track version {raw.get('version')!r} "
            f"(this build reads version {VERSION})"
        )

    try:
        devices = [
            TrackDevice(
                uuid=str(d["uuid"]),
                name=str(d["name"]),
                color=tuple(int(c) for c in d["color"]),
                inhale_note=int(d["inhale_note"]),
                exhale_note=int(d["exhale_note"]),
                # Optional: tracks written before the field existed read as 1.
                midi_channel=max(1, min(16, int(d.get("midi_channel", 1)))),
                hold_note=int(d.get("hold_note", 0)),
                cons_n=int(d.get("cons_n", 0)),
                cons_tolerance=float(d.get("cons_tolerance", 0.30)),
            )
            for d in raw["devices"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{path.name}: malformed device list ({exc})") from exc

    if not devices:
        raise ValueError(f"{path.name}: no devices")

    samples: list[tuple[float, int, float]] = []
    last_t = float("-inf")
    for row in raw["samples"]:
        try:
            t, i, amp = float(row[0]), int(row[1]), float(row[2])
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"{path.name}: malformed sample {row!r}") from exc
        if not 0 <= i < len(devices):
            raise ValueError(
                f"{path.name}: device index {i} out of range "
                f"(track has {len(devices)} devices)"
            )
        if t < last_t:
            raise ValueError(f"{path.name}: decreasing timestamp at t={t}")
        last_t = t
        samples.append((t, i, amp))

    try:
        detection = DetectionConfig(**raw["detection"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path.name}: malformed detection block ({exc})") from exc

    return Track(
        name=str(raw["name"]),
        created=str(raw["created"]),
        duration_s=float(raw["duration_s"]),
        source=str(raw["source"]),
        detection=detection,
        devices=devices,
        samples=samples,
    )
