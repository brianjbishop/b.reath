from __future__ import annotations

from pathlib import Path

from breath_midi.config.store import ConfigStore
from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.midi.activity_bus import MidiActivityBus
from breath_midi.midi.mido_sink import MidoMidiSink
from breath_midi.runtime import ControllerRuntime
from breath_midi.ui.main_window import run_ui


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    config_path = project_root / "config.toml"

    store = ConfigStore(config_path)
    config = store.load()

    midi_bus = MidiActivityBus()
    midi = MidoMidiSink(
        activity_bus=midi_bus,
        source_id=str(config.controller_id),
    )
    runtime = ControllerRuntime(config=config, midi=midi)
    eb_hub = EveryBreathHub(config=config)
    # Breath tracking starts from the UI once Dear PyGui init finishes (same as after Reload).
    try:
        run_ui(runtime, store, midi_bus, eb_hub)
    finally:
        runtime.stop()
        eb_hub.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
