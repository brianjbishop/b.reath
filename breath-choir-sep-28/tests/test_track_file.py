"""
Track files.

The rule the format exists for: store what the phone sent, never what the
detector concluded. Phase, derivative and cycle metrics are all derived
downstream, and baking them in would mean turning a dial changed nothing on
playback — which is the one job a track exists to do.

Validation is deliberately strict. A malformed track should be refused with a
message, not half-loaded into a live performance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from breath_midi.tracks.file import Track, TrackDevice, read_track, write_track

from .test_presets import make_det


def sample_track() -> Track:
    return Track(
        name="two performers",
        created="2026-09-27T14:30:00",
        duration_s=0.04,
        source="generated",
        detection=make_det(),
        devices=[
            TrackDevice("aaa", "Ana", (220, 120, 90), 54, 55),
            TrackDevice("bbb", "Bo", (90, 160, 220), 56, 57),
        ],
        samples=[(0.0, 0, 0.41), (0.02, 1, 0.23), (0.04, 0, 0.44)],
    )


def corrupt(path: Path, **changes):
    raw = json.loads(path.read_text())
    raw.update(changes)
    path.write_text(json.dumps(raw))


def test_round_trips(tmp_path: Path):
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    assert read_track(p) == sample_track()


def test_creates_the_directory(tmp_path: Path):
    p = tmp_path / "nested" / "deeper" / "t.breath.json"
    write_track(p, sample_track())
    assert p.exists()


def test_detection_block_round_trips(tmp_path: Path):
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    assert read_track(p).detection == make_det()


def test_rejects_device_index_out_of_range(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    raw = json.loads(p.read_text())
    raw["samples"][0][1] = 7
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="device index"):
        read_track(p)


def test_rejects_negative_device_index(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    raw = json.loads(p.read_text())
    raw["samples"][0][1] = -1
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="device index"):
        read_track(p)


def test_rejects_backwards_timestamps(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    corrupt(p, samples=[[1.0, 0, 0.5], [0.5, 0, 0.5]])
    with pytest.raises(ValueError, match="decreasing"):
        read_track(p)


def test_equal_timestamps_are_fine(tmp_path: Path):
    """Two phones can land in the same millisecond. That is not corruption."""
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    corrupt(p, samples=[[0.5, 0, 0.5], [0.5, 1, 0.6]])
    assert len(read_track(p).samples) == 2


def test_rejects_unknown_version(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    corrupt(p, version=99)
    with pytest.raises(ValueError, match="version"):
        read_track(p)


def test_rejects_a_track_with_no_devices(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    corrupt(p, devices=[], samples=[])
    with pytest.raises(ValueError, match="no devices"):
        read_track(p)


def test_rejects_truncated_json(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    p.write_text(p.read_text()[: len(p.read_text()) // 2])
    with pytest.raises(ValueError):
        read_track(p)


def test_stores_no_derived_fields(tmp_path: Path):
    """
    The whole point: raw input only, never the detector's conclusions.

    The detection block is excluded from the check — it legitimately names
    dials, and two of them are called derivative_*.  What must not appear is
    anything the detector *produced*: a phase, a cycle, a smoothed amplitude.
    """
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    raw = json.loads(p.read_text())
    raw.pop("detection")
    text = json.dumps(raw).lower()
    for banned in ("phase", "derivative", "cycle", "amp_proc", "rolling", "velocity"):
        assert banned not in text, f"{banned!r} leaked into the track file"


def test_a_sample_is_exactly_three_values(tmp_path: Path):
    """Time, which device, amplitude.  Anything more is a conclusion."""
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    for row in json.loads(p.read_text())["samples"]:
        assert len(row) == 3, f"sample carries more than (t, device, amp): {row}"


def test_amplitudes_keep_four_decimals(tmp_path: Path):
    p = tmp_path / "t.breath.json"
    t = sample_track()
    t = Track(**{**t.__dict__, "samples": [(0.0, 0, 0.123456789)]})
    write_track(p, t)
    assert read_track(p).samples[0][2] == pytest.approx(0.1235, abs=1e-6)
