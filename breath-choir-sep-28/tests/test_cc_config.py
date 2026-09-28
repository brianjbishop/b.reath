"""
Global CC shaping, and the config sections apply_from_ui used to drop.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from breath_midi.config.model import CcConfig
from breath_midi.config.store import ConfigStore

from .test_hold_triggers import base_config


def test_cc_defaults_are_a_full_range_linear_ish_dial():
    cc = CcConfig()
    assert (cc.min_value, cc.max_value) == (0, 127)
    assert cc.curve_gamma == 1.0


def test_cc_section_round_trips(tmp_path: Path):
    path = tmp_path / "config.toml"
    store = ConfigStore(path)
    cfg = replace(
        base_config(),
        cc=CcConfig(min_value=20, max_value=110, curve_kind="gamma", curve_gamma=2.5),
    )
    store.save(cfg)
    back = store.load().cc
    assert (back.min_value, back.max_value) == (20, 110)
    assert back.curve_gamma == 2.5


def test_a_config_without_a_cc_section_still_loads(tmp_path: Path):
    """[cc] is additive; an older config must not stop loading."""
    src = Path(__file__).parent.parent / "config.toml"
    text = src.read_text()
    trimmed = text.split("[cc]")[0]
    path = tmp_path / "config.toml"
    path.write_text(trimmed)
    cc = ConfigStore(path).load().cc
    assert (cc.min_value, cc.max_value) == (0, 127)


def test_apply_from_ui_keeps_viz_network_and_cc():
    """
    The regression: ConfigModel was rebuilt without these three, and all three
    have defaults, so every knob turn silently reset them — including the router
    MAC the Wi-Fi icon had just learned.
    """
    import inspect

    from breath_midi.ui.main_window import BreathMidiDpgUI

    src = inspect.getsource(BreathMidiDpgUI.apply_from_ui)
    for field in ("viz=", "network=", "cc="):
        assert field in src, f"apply_from_ui drops {field[:-1]} again"
