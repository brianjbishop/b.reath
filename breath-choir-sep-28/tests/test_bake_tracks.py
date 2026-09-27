"""
The generated tracks.

These are clean maths, not recordings — they will not reproduce the sensor
noise that caused the original inhale/exhale chatter. What they are good for is
exercising the real code path with no phones in the room, so the tests here
check exactly that: that the shapes still mean what the FSM tests say they mean
once they have been through a file.
"""

from __future__ import annotations

from pathlib import Path

from breath_midi.signal.features import FeatureExtractor
from breath_midi.tracks.file import read_track
from breath_midi.types import Phase, ProcessedSample
from scripts.bake_tracks import bake_all

from .test_phase_fsm import make_detection

EXPECTED = {
    "slow-and-deep.breath.json",
    "fast-and-shallow.breath.json",
    "irregular.breath.json",
    "box-breathing.breath.json",
    "dropout.breath.json",
    "group-of-four.breath.json",
}


def phases_of(track, device_index: int = 0) -> set[Phase]:
    """Run one performer's samples through the real detector."""
    fx = FeatureExtractor(make_detection())
    seen = set()
    for t, i, amp in track.samples:
        if i != device_index:
            continue
        seen.add(
            fx.update(
                ProcessedSample(t=t, amp_raw=amp, amp_proc=amp, source_id="x")
            ).phase
        )
    return seen


def test_bakes_the_expected_tracks(tmp_path: Path):
    assert {p.name for p in bake_all(tmp_path)} == EXPECTED


def test_every_track_reads_back(tmp_path: Path):
    for p in bake_all(tmp_path):
        track = read_track(p)
        assert track.source == "generated"
        assert track.samples, f"{p.name} is empty"
        assert track.duration_s > 0
        assert track.devices


def test_box_breathing_produces_holds_through_the_real_detector(tmp_path: Path):
    """The bake path and the FSM tests must agree about what box breathing is."""
    bake_all(tmp_path)
    seen = phases_of(read_track(tmp_path / "box-breathing.breath.json"))
    assert Phase.HOLD in seen, "box breathing did not register a hold"
    assert Phase.INHALE in seen and Phase.EXHALE in seen


def test_smooth_breathing_does_not_produce_holds(tmp_path: Path):
    """Continuous breathing has no sustained flat region."""
    bake_all(tmp_path)
    seen = phases_of(read_track(tmp_path / "fast-and-shallow.breath.json"))
    assert Phase.HOLD not in seen
    assert Phase.INHALE in seen and Phase.EXHALE in seen


def test_dropout_has_a_gap_long_enough_to_time_out(tmp_path: Path):
    """The hub fades a device after 5s of silence; this track must trigger it."""
    bake_all(tmp_path)
    track = read_track(tmp_path / "dropout.breath.json")
    last_seen: dict[int, float] = {}
    for t, i, _ in track.samples:
        last_seen[i] = t
    gaps = [track.duration_s - t for t in last_seen.values()]
    assert max(gaps) > 5.0, "no performer is silent long enough to fade out"


def test_group_track_has_four_performers(tmp_path: Path):
    bake_all(tmp_path)
    track = read_track(tmp_path / "group-of-four.breath.json")
    assert len(track.devices) == 4
    assert len({d.inhale_note for d in track.devices}) == 4, "notes collide"


def test_samples_are_ordered_by_time(tmp_path: Path):
    """read_track enforces this, but the baker must not rely on being caught."""
    for p in bake_all(tmp_path):
        times = [t for t, _, _ in read_track(p).samples]
        assert times == sorted(times), f"{p.name} is out of order"


def test_amplitudes_stay_in_range(tmp_path: Path):
    for p in bake_all(tmp_path):
        for _, _, amp in read_track(p).samples:
            assert 0.0 <= amp <= 1.0, f"{p.name} has amplitude {amp}"


def test_rerunning_the_bake_is_safe(tmp_path: Path):
    bake_all(tmp_path)
    second = bake_all(tmp_path)
    assert {p.name for p in second} == EXPECTED
