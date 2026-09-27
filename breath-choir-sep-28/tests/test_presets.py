"""
Named detection presets.

config.toml holds exactly one dial set and autosave overwrites it on every knob
turn, so a tuning you liked cannot survive the next adjustment. These tests pin
the smallest thing that fixes that: save ten numbers under a name, get them
back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breath_midi.config.model import DetectionConfig
from breath_midi.presets import list_presets, load_preset, save_preset


def make_det(**kw) -> DetectionConfig:
    """Detection config matching breath-choir-sep-28/config.toml defaults."""
    base = dict(
        derivative_enabled=True,
        derivative_smoothing_alpha=0.2,
        inhale_exit_delta=0.06,
        exhale_exit_delta=0.12,
        hold_exit_delta=0.15,
        hold_enabled=True,
        hold_still_tol=0.05,
        min_hold_ms=1500,
        hold_peak_band=0.80,
        hold_valley_band=0.20,
    )
    base.update(kw)
    return DetectionConfig(**base)


def test_round_trips_every_field(tmp_path: Path):
    det = make_det(inhale_exit_delta=0.09, min_hold_ms=900, hold_enabled=False)
    save_preset(tmp_path, "hive show", det)
    assert load_preset(tmp_path, "hive show") == det


def test_lists_saved_presets_sorted(tmp_path: Path):
    save_preset(tmp_path, "rehearsal", make_det())
    save_preset(tmp_path, "hive show", make_det())
    assert list_presets(tmp_path) == ["hive show", "rehearsal"]


def test_empty_dir_lists_nothing(tmp_path: Path):
    assert list_presets(tmp_path) == []


def test_missing_dir_lists_nothing(tmp_path: Path):
    assert list_presets(tmp_path / "not-created-yet") == []


def test_missing_preset_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_preset(tmp_path, "nope")


def test_saving_twice_overwrites_rather_than_duplicating(tmp_path: Path):
    save_preset(tmp_path, "take", make_det(min_hold_ms=1000))
    save_preset(tmp_path, "take", make_det(min_hold_ms=2000))
    assert list_presets(tmp_path) == ["take"]
    assert load_preset(tmp_path, "take").min_hold_ms == 2000


@pytest.mark.parametrize("bad", ["a/b", "a\\b", ".hidden", "", "   "])
def test_illegal_names_are_rejected(tmp_path: Path, bad: str):
    """A preset name becomes a filename, so it must not escape the directory."""
    with pytest.raises(ValueError):
        save_preset(tmp_path, bad, make_det())


def test_creates_the_directory_if_missing(tmp_path: Path):
    target = tmp_path / "presets"
    save_preset(target, "first", make_det())
    assert target.is_dir()
    assert list_presets(target) == ["first"]


def test_a_stray_file_in_the_folder_is_ignored(tmp_path: Path):
    save_preset(tmp_path, "real", make_det())
    (tmp_path / "notes.txt").write_text("not a preset")
    assert list_presets(tmp_path) == ["real"]
