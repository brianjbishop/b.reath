"""
Per-device MIDI channel.

Devices were separated only by note number, all on one channel. A channel each
means each performer can land on its own Ableton track, with its own instrument
and effects.

Stored 1-16, the way MIDI is written everywhere a musician reads it. The wire
wants 0-15, and that conversion happens in exactly one place.
"""

from __future__ import annotations

from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.midi.voice import BreathVoice
from breath_midi.types import BreathSample, Phase

from .test_hold_triggers import base_config


class SpySink:
    """Records what actually went out, with the channel it went out on."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, int, int]] = []

    def send_note_on(self, channel, note, velocity):
        self.sent.append(("on", int(channel), int(note)))

    def send_note_off(self, channel, note, velocity=0):
        self.sent.append(("off", int(channel), int(note)))

    def send_cc(self, channel, cc, value):
        pass


def make_hub() -> EveryBreathHub:
    return EveryBreathHub(config=base_config(), osc_port=8815)


# ── registry ─────────────────────────────────────────────────────────────────


def test_devices_default_to_channel_one():
    """No behaviour change for an existing set-up until a channel is changed."""
    hub = make_hub()
    entry, _ = hub.registry.get_or_create("phone-a")
    assert entry.midi_channel == 1


def test_channel_can_be_set_per_device():
    hub = make_hub()
    hub.registry.get_or_create("phone-a")
    hub.registry.get_or_create("phone-b")
    hub.registry.set_midi_channel("phone-a", 5)
    assert hub.registry.get("phone-a").midi_channel == 5
    assert hub.registry.get("phone-b").midi_channel == 1, "changed the wrong device"


def test_channel_is_clamped_to_the_midi_range():
    hub = make_hub()
    hub.registry.get_or_create("phone-a")
    hub.registry.set_midi_channel("phone-a", 99)
    assert hub.registry.get("phone-a").midi_channel == 16
    hub.registry.set_midi_channel("phone-a", 0)
    assert hub.registry.get("phone-a").midi_channel == 1
    hub.registry.set_midi_channel("phone-a", -4)
    assert hub.registry.get("phone-a").midi_channel == 1


def test_snapshot_carries_the_channel():
    hub = make_hub()
    hub.registry.get_or_create("phone-a")
    hub.registry.set_midi_channel("phone-a", 7)
    snap = next(s for s in hub.get_ui_snapshot() if s.uuid == "phone-a")
    assert snap.midi_channel == 7


# ── the wire ─────────────────────────────────────────────────────────────────


def test_channel_one_goes_out_as_zero():
    """MIDI is written 1-16 and sent 0-15. Off by one here is silent and awful."""
    sink = SpySink()
    voice = BreathVoice(sink, channel=0, velocity=100)
    voice.set_notes(inhale=54, hold=0, exhale=55)
    voice.on_phase(Phase.INHALE)
    assert sink.sent == [("on", 0, 54)]


def test_changing_channel_releases_on_the_old_one():
    """
    The stuck-note case.

    If the note-off went out on the new channel, the old channel would hold that
    key down forever with nothing left to clear it.
    """
    sink = SpySink()
    voice = BreathVoice(sink, channel=2, velocity=100)
    voice.set_notes(inhale=54, hold=0, exhale=55)
    voice.on_phase(Phase.INHALE)
    sink.sent.clear()

    voice.release()              # what set_midi_channel does first
    voice.set_channel(6)

    assert sink.sent == [("off", 2, 54)], "note-off did not go to the old channel"


def test_hub_moves_a_live_device_to_a_new_channel():
    hub = make_hub()
    hub.registry.get_or_create("phone-a")
    hub._ensure_midi_sink()
    hub._on_new_device("phone-a")
    hub.set_midi_channel("phone-a", 9)
    assert hub.registry.get("phone-a").midi_channel == 9
    # The runtime moved too, not just the stored value.
    assert hub._runtimes["phone-a"]._voice._channel == 8


def test_a_new_device_starts_on_its_stored_channel():
    """Set before connection — a device reconnecting must come back where it was."""
    hub = make_hub()
    hub.registry.get_or_create("phone-a")
    hub.registry.set_midi_channel("phone-a", 4)
    hub._ensure_midi_sink()
    hub._on_new_device("phone-a")
    assert hub._runtimes["phone-a"]._voice._channel == 3


def test_setting_a_channel_on_an_unknown_device_is_safe():
    make_hub().set_midi_channel("ghost", 4)


def test_two_devices_sound_on_their_own_channels():
    hub = make_hub()
    for uuid in ("phone-a", "phone-b"):
        hub.registry.get_or_create(uuid)
    hub.registry.set_midi_channel("phone-a", 1)
    hub.registry.set_midi_channel("phone-b", 3)
    hub._ensure_midi_sink()
    for uuid in ("phone-a", "phone-b"):
        hub._on_new_device(uuid)
    assert hub._runtimes["phone-a"]._voice._channel == 0
    assert hub._runtimes["phone-b"]._voice._channel == 2


# ── the strip ────────────────────────────────────────────────────────────────


def test_the_strip_has_a_channel_field_above_n():
    """Ch answers where a performer goes; N answers whether they may sound."""
    from pathlib import Path

    import dearpygui.dearpygui as dpg

    from breath_midi.config.store import ConfigStore
    from breath_midi.ui.group_breath_bottom_panel import GroupBreathBottomPanel

    from .test_rhombus_ui import snapshot

    dpg.create_context()

    class FakeHub:
        registry = type("R", (), {"get": lambda self, u: None})()
        _config = ConfigStore(Path(__file__).parent.parent / "config.toml").load()

    for tag in ("theme_circle_gray", "theme_circle_yellow", "theme_gate_green"):
        with dpg.theme(tag=tag):
            pass
    with dpg.window(tag="root"):
        with dpg.group(tag="gb_strip_row"):
            pass
        panel = GroupBreathBottomPanel(FakeHub(), "root")  # type: ignore[arg-type]
        snap = snapshot(uuid="dev-ch")
        panel._build_strip(snap)

    ch, n = f"gb_strip_ch_{snap.uuid}", f"gb_strip_cons_n_{snap.uuid}"
    assert dpg.does_item_exist(ch), "no channel field"
    assert dpg.does_item_exist(n)
    # Built before N, so it is drawn above it.
    assert dpg.get_alias_id(ch) < dpg.get_alias_id(n), "Ch is not above N"
    cfg = dpg.get_item_configuration(ch)
    assert (cfg["min_value"], cfg["max_value"]) == (1, 16)
    dpg.destroy_context()
