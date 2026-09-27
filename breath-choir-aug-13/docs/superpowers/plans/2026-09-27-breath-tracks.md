# Breath Tracks, Presets and Recording — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save and reload dial sets by name, and load saved breath performances as extra
performers that play alongside live phones.

**Architecture:** A track is a JSON file holding raw breath samples plus the dials in effect
when it was captured. Playback replays those samples into the hub as ordinary devices, so
recorded and live performers mix in one choir. All sources feed the hub through a single
drain thread, preserving the hub's existing single-caller invariant.

**Tech Stack:** Python 3.13, Dear PyGui 2.3.1, pytest, tomllib/tomli-w, stdlib json and
threading.

## Global Constraints

- Work happens in `breath-choir-aug-13/`. Do not touch sibling iterations.
- Store what the phone sent, never what the detector concluded. No phases, derivatives or
  cycle metrics in a track file.
- Loading a track never changes the current dials.
- Timestamps are stored as recorded. Never resample to a fixed grid.
- Tracks do not loop. A track that ends lets its devices time out.
- `tracks/generated/` is committed. `tracks/recordings/` is gitignored.
- Run the whole suite with `.venv/bin/python -m pytest -q` before each commit.
- Commit messages end with: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

**Order:** presets, then tracks, then recording. Presets come first because they are small
and because today a good tuning cannot survive the next knob turn. Say so if you would
rather lead with tracks.

---

## File Structure

**Stage A — presets**
- Create `breath_midi/presets.py` — named dial sets: list, save, load.
- Modify `breath_midi/ui/widgets/hold_controls.py` — preset row above the knobs.
- Create `tests/test_presets.py`

**Stage B — tracks**
- Create `breath_midi/tracks/__init__.py`
- Create `breath_midi/tracks/file.py` — the `Track` dataclass, read, write, validate.
- Create `breath_midi/feed.py` — `SampleFeed`, the single-consumer merge point.
- Create `breath_midi/tracks/playback.py` — `TrackPlaybackSource`.
- Create `scripts/bake_tracks.py` — writes `tracks/generated/*.breath.json`.
- Modify `breath_midi/every_breath/hub.py` — route sources through the feed; add
  `load_track` / `stop_track`.
- Modify `breath_midi/ui/group_breath_tab.py:165` — the Tracks row gains load and stop.
- Create `tests/test_track_file.py`, `tests/test_feed.py`, `tests/test_playback.py`

**Stage C — recording**
- Create `breath_midi/tracks/recorder.py` — `TrackRecorder`.
- Modify `breath_midi/every_breath/hub.py` — record tap.
- Modify `breath_midi/ui/group_breath_tab.py` — record toggle.
- Modify `.gitignore`
- Create `tests/test_recorder.py`

---

# STAGE A — PRESETS

### Task 1: Preset store

**Files:**
- Create: `breath_midi/presets.py`
- Test: `tests/test_presets.py`

**Interfaces:**
- Consumes: `DetectionConfig` from `breath_midi.config.model` (10 fields:
  `derivative_enabled`, `derivative_smoothing_alpha`, `inhale_exit_delta`,
  `exhale_exit_delta`, `hold_exit_delta`, `hold_enabled`, `hold_still_tol`,
  `min_hold_ms`, `hold_peak_band`, `hold_valley_band`).
- Produces: `save_preset(dir: Path, name: str, det: DetectionConfig) -> Path`,
  `load_preset(dir: Path, name: str) -> DetectionConfig`,
  `list_presets(dir: Path) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_presets.py
from pathlib import Path
import pytest
from breath_midi.config.model import DetectionConfig
from breath_midi.presets import list_presets, load_preset, save_preset


def make_det(**kw) -> DetectionConfig:
    base = dict(
        derivative_enabled=True, derivative_smoothing_alpha=0.2,
        inhale_exit_delta=0.06, exhale_exit_delta=0.12, hold_exit_delta=0.15,
        hold_enabled=True, hold_still_tol=0.05, min_hold_ms=1500,
        hold_peak_band=0.80, hold_valley_band=0.20,
    )
    base.update(kw)
    return DetectionConfig(**base)


def test_round_trips_every_field(tmp_path: Path):
    det = make_det(inhale_exit_delta=0.09, min_hold_ms=900)
    save_preset(tmp_path, "hive show", det)
    assert load_preset(tmp_path, "hive show") == det


def test_lists_saved_presets_sorted(tmp_path: Path):
    save_preset(tmp_path, "rehearsal", make_det())
    save_preset(tmp_path, "hive show", make_det())
    assert list_presets(tmp_path) == ["hive show", "rehearsal"]


def test_empty_dir_lists_nothing(tmp_path: Path):
    assert list_presets(tmp_path) == []


def test_missing_preset_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_preset(tmp_path, "nope")


def test_name_with_slash_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        save_preset(tmp_path, "a/b", make_det())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_presets.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'breath_midi.presets'`

- [ ] **Step 3: Write minimal implementation**

```python
# breath_midi/presets.py
"""
Named detection presets.

config.toml holds exactly one dial set and autosave overwrites it on every knob
turn, so a tuning you liked is gone the moment you nudge the next dial.  A
preset is that dial set, named and kept.

Presets are intent — something you chose.  A track's stored dials are
provenance — what happened to be set when it was captured.  Same ten numbers,
different meaning, so they live in different files.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import tomli_w

try:
    import tomllib
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

from breath_midi.config.model import DetectionConfig

_SUFFIX = ".preset.toml"


def _path(dir: Path, name: str) -> Path:
    if not name.strip():
        raise ValueError("preset name must not be blank")
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"illegal preset name: {name!r}")
    return dir / f"{name}{_SUFFIX}"


def save_preset(dir: Path, name: str, det: DetectionConfig) -> Path:
    p = _path(dir, name)
    dir.mkdir(parents=True, exist_ok=True)
    p.write_text(tomli_w.dumps(asdict(det)), encoding="utf-8")
    return p


def load_preset(dir: Path, name: str) -> DetectionConfig:
    p = _path(dir, name)
    if not p.exists():
        raise FileNotFoundError(f"no preset named {name!r}")
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    return DetectionConfig(**raw)


def list_presets(dir: Path) -> list[str]:
    if not dir.exists():
        return []
    return sorted(p.name[: -len(_SUFFIX)] for p in dir.glob(f"*{_SUFFIX}"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_presets.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add breath_midi/presets.py tests/test_presets.py
git commit -m "feat: named detection presets

config.toml holds one dial set and autosave overwrites it on every knob turn, so
a tuning you liked cannot survive the next adjustment.  A preset is that dial set
kept under a name.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Preset UI in the Detection panel

**Files:**
- Modify: `breath_midi/ui/widgets/hold_controls.py`
- Test: `tests/test_presets_ui.py`

**Interfaces:**
- Consumes: `save_preset`, `load_preset`, `list_presets` from Task 1.
- Produces: `build_hold_controls(on_change, presets_dir, on_preset_load)` — the
  existing function gains two keyword arguments, both defaulting to `None` so
  existing callers and tests keep working.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_presets_ui.py
from pathlib import Path
import dearpygui.dearpygui as dpg
import pytest
from breath_midi.ui.widgets import knob as K
from breath_midi.ui.widgets.hold_controls import build_hold_controls


@pytest.fixture
def ctx(tmp_path: Path):
    dpg.create_context()
    K._reset_for_tests()
    with dpg.window(tag="root"):
        build_hold_controls(lambda *_: None, presets_dir=tmp_path,
                            on_preset_load=lambda det: None)
    yield tmp_path
    dpg.destroy_context()
    K._reset_for_tests()


def test_preset_widgets_exist(ctx):
    for tag in ("ui_preset_combo", "ui_preset_name", "ui_preset_save"):
        assert dpg.does_item_exist(tag), tag


def test_combo_starts_empty_when_no_presets(ctx):
    assert dpg.get_item_configuration("ui_preset_combo")["items"] == []


def test_knobs_still_build(ctx):
    for tag in ("ui_inhale_exit_delta", "ui_exhale_exit_delta", "ui_hold_exit_delta",
                "ui_hold_still_tol", "ui_min_hold_ms",
                "ui_hold_peak_band", "ui_hold_valley_band"):
        assert dpg.does_item_exist(tag), tag
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_presets_ui.py -q`
Expected: FAIL — `TypeError: build_hold_controls() got an unexpected keyword argument 'presets_dir'`

- [ ] **Step 3: Write minimal implementation**

Change the signature and add the preset row above the existing knob group:

```python
def build_hold_controls(on_change, presets_dir=None, on_preset_load=None) -> None:
    """Build the detection controls into the current DPG container."""
    if presets_dir is not None:
        _build_preset_row(presets_dir, on_preset_load)
        dpg.add_spacer(height=6)
        dpg.add_separator()
        dpg.add_spacer(height=6)
    with dpg.group(horizontal=True):
        ...  # existing knobs unchanged
```

```python
def _build_preset_row(presets_dir, on_preset_load) -> None:
    from breath_midi.presets import list_presets, load_preset, save_preset

    def _refresh() -> None:
        dpg.configure_item("ui_preset_combo", items=list_presets(presets_dir))

    def _load(_s=None, _a=None) -> None:
        name = dpg.get_value("ui_preset_combo")
        if name and on_preset_load is not None:
            on_preset_load(load_preset(presets_dir, name))

    def _save(_s=None, _a=None) -> None:
        name = (dpg.get_value("ui_preset_name") or "").strip()
        if not name:
            return
        from breath_midi.ui.widgets.hold_controls import read_detection_from_ui
        save_preset(presets_dir, name, read_detection_from_ui())
        dpg.set_value("ui_preset_name", "")
        _refresh()
        dpg.set_value("ui_preset_combo", name)

    with dpg.group(horizontal=True):
        dpg.add_combo([], tag="ui_preset_combo", width=150, callback=_load)
        dpg.add_spacer(width=6)
        dpg.add_input_text(tag="ui_preset_name", width=90, hint="name")
        dpg.add_spacer(width=6)
        dpg.add_button(label="Save", tag="ui_preset_save", callback=_save)
    _refresh()
```

Add the reader that turns the live widgets into a `DetectionConfig`:

```python
def read_detection_from_ui() -> "DetectionConfig":
    """The seven knobs plus the toggle, as a config object."""
    from breath_midi.config.model import DetectionConfig
    return DetectionConfig(
        derivative_enabled=True,
        derivative_smoothing_alpha=0.2,
        inhale_exit_delta=float(dpg.get_value("ui_inhale_exit_delta")),
        exhale_exit_delta=float(dpg.get_value("ui_exhale_exit_delta")),
        hold_exit_delta=float(dpg.get_value("ui_hold_exit_delta")),
        hold_enabled=bool(dpg.get_value("ui_hold_enabled")),
        hold_still_tol=float(dpg.get_value("ui_hold_still_tol")),
        min_hold_ms=int(dpg.get_value("ui_min_hold_ms")),
        hold_peak_band=float(dpg.get_value("ui_hold_peak_band")),
        hold_valley_band=float(dpg.get_value("ui_hold_valley_band")),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_presets_ui.py tests/test_rhombus_ui.py -q`
Expected: all pass — the rhombus suite proves the default-argument path still builds.

- [ ] **Step 5: Wire it in main_window**

In `breath_midi/ui/main_window.py`, where `build_hold_controls(self._on_change)` is called
via `group_breath_tab`, pass `presets_dir=self.store.path.parent / "presets"` and
`on_preset_load=self._apply_detection_preset`. Add:

```python
def _apply_detection_preset(self, det) -> None:
    """A preset replaces the dials and nothing else."""
    from dataclasses import replace
    self._apply_cfg(replace(self.runtime.config, detection=det))
```

`_apply_cfg` already calls `load_into_ui`, so the knobs move to match.

- [ ] **Step 6: Run the whole suite, then launch**

Run: `.venv/bin/python -m pytest -q`
Then: `.venv/bin/python -m breath_midi.app` — save a preset, turn a knob, reload it, confirm
the knob returns. Quit.

- [ ] **Step 7: Commit**

```bash
git add breath_midi/ui/widgets/hold_controls.py breath_midi/ui/main_window.py \
        breath_midi/ui/group_breath_tab.py tests/test_presets_ui.py
git commit -m "feat: save and recall detection presets from the panel

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# STAGE B — TRACKS

### Task 3: Track file format

**Files:**
- Create: `breath_midi/tracks/__init__.py` (empty)
- Create: `breath_midi/tracks/file.py`
- Test: `tests/test_track_file.py`

**Interfaces:**
- Produces: `TrackDevice(uuid, name, color, inhale_note, exhale_note)`,
  `Track(name, created, duration_s, source, detection, devices, samples)` where
  `samples: list[tuple[float, int, float]]`, plus
  `write_track(path: Path, track: Track) -> None` and
  `read_track(path: Path) -> Track` which raises `ValueError` on malformed input.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_track_file.py
import json
from pathlib import Path
import pytest
from breath_midi.tracks.file import Track, TrackDevice, read_track, write_track
from .test_presets import make_det


def sample_track() -> Track:
    return Track(
        name="two performers",
        created="2026-09-27T14:30:00",
        duration_s=0.06,
        source="generated",
        detection=make_det(),
        devices=[
            TrackDevice("aaa", "Ana", (220, 120, 90), 54, 55),
            TrackDevice("bbb", "Bo", (90, 160, 220), 56, 57),
        ],
        samples=[(0.0, 0, 0.41), (0.02, 1, 0.23), (0.04, 0, 0.44)],
    )


def test_round_trips(tmp_path: Path):
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    assert read_track(p) == sample_track()


def test_rejects_device_index_out_of_range(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    raw = json.loads(p.read_text())
    raw["samples"][0][1] = 7
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="device index"):
        read_track(p)


def test_rejects_backwards_timestamps(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    raw = json.loads(p.read_text())
    raw["samples"] = [[1.0, 0, 0.5], [0.5, 0, 0.5]]
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="decreasing"):
        read_track(p)


def test_rejects_unknown_version(tmp_path: Path):
    p = tmp_path / "bad.breath.json"
    write_track(p, sample_track())
    raw = json.loads(p.read_text())
    raw["version"] = 99
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="version"):
        read_track(p)


def test_stores_no_derived_fields(tmp_path: Path):
    """The rule the format exists for: raw input only, never conclusions."""
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    text = p.read_text()
    for banned in ("phase", "derivative", "cycle", "inhale\"", "amp_proc"):
        assert banned not in text, banned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_track_file.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'breath_midi.tracks'`

- [ ] **Step 3: Write minimal implementation**

```python
# breath_midi/tracks/file.py
"""
Track files: a saved breath performance.

A track stores what the phones sent — t, which device, amplitude — and nothing
the detector concluded.  Phase, derivative and cycle metrics are all derived
downstream, and baking them in would mean turning a dial changed nothing on
playback, which is the one job a track exists to do.  Raw input only makes every
playback a fresh detection run.

`detection` records the dials in effect when the track was captured.  It is
provenance, not instruction: loading a track never changes your dials.
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


@dataclass(frozen=True)
class Track:
    name: str
    created: str
    duration_s: float
    source: str                  # "generated" | "recorded"
    detection: DetectionConfig
    devices: list[TrackDevice]
    samples: list[tuple[float, int, float]]   # (t, device_index, amp)


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
                "uuid": d.uuid, "name": d.name, "color": list(d.color),
                "inhale_note": d.inhale_note, "exhale_note": d.exhale_note,
            }
            for d in track.devices
        ],
        "samples": [[round(t, 3), i, round(a, 4)] for t, i, a in track.samples],
    }
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def read_track(path: Path) -> Track:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if raw.get("version") != VERSION:
        raise ValueError(f"unsupported track version: {raw.get('version')!r}")

    devices = [
        TrackDevice(
            uuid=str(d["uuid"]), name=str(d["name"]),
            color=tuple(int(c) for c in d["color"]),
            inhale_note=int(d["inhale_note"]), exhale_note=int(d["exhale_note"]),
        )
        for d in raw["devices"]
    ]

    samples: list[tuple[float, int, float]] = []
    last_t = float("-inf")
    for t, i, a in raw["samples"]:
        t = float(t)
        i = int(i)
        if not 0 <= i < len(devices):
            raise ValueError(f"device index {i} out of range")
        if t < last_t:
            raise ValueError(f"decreasing timestamp at t={t}")
        last_t = t
        samples.append((t, i, float(a)))

    return Track(
        name=str(raw["name"]), created=str(raw["created"]),
        duration_s=float(raw["duration_s"]), source=str(raw["source"]),
        detection=DetectionConfig(**raw["detection"]),
        devices=devices, samples=samples,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_track_file.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add breath_midi/tracks/ tests/test_track_file.py
git commit -m "feat: track file format — raw breath in, no conclusions

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Single-consumer sample feed

This task exists because of a real invariant in the hub. `_on_sample` states:

> set_activity_source_id is called here without a lock because `_on_sample` is always
> invoked from the single OSC receive thread … If the threading model changes in future
> this assumption MUST be revisited.

Playing a track alongside live phones means a second producer thread. Rather than lock the
real-time MIDI path, every source posts events to one queue and one drain thread calls the
hub. The invariant stays literally true: still exactly one calling thread.

**Files:**
- Create: `breath_midi/feed.py`
- Test: `tests/test_feed.py`

**Interfaces:**
- Produces: `SampleFeed(on_sample, on_new_device, on_timeout)` with
  `submit_sample(BreathSample)`, `submit_new_device(str)`, `submit_timeout(str)`,
  `start()`, `stop()`. All three submit methods are thread-safe and never block.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_feed.py
import threading
import time
from breath_midi.feed import SampleFeed
from breath_midi.types import BreathSample


def test_delivers_in_order():
    got = []
    feed = SampleFeed(got.append, lambda u: None, lambda u: None)
    feed.start()
    for i in range(50):
        feed.submit_sample(BreathSample(t=i * 0.02, amp=i / 50, source_id="a"))
    time.sleep(0.4)
    feed.stop()
    assert [s.t for s in got] == [i * 0.02 for i in range(50)]


def test_all_callbacks_run_on_one_thread():
    """The whole point: the hub must still see a single caller."""
    threads = set()
    feed = SampleFeed(
        lambda s: threads.add(threading.get_ident()),
        lambda u: threads.add(threading.get_ident()),
        lambda u: threads.add(threading.get_ident()),
    )
    feed.start()

    def produce(tag):
        for i in range(30):
            feed.submit_new_device(tag)
            feed.submit_sample(BreathSample(t=i * 0.01, amp=0.5, source_id=tag))
            feed.submit_timeout(tag)

    ts = [threading.Thread(target=produce, args=(f"dev{n}",)) for n in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    time.sleep(0.4)
    feed.stop()
    assert len(threads) == 1, f"hub was called from {len(threads)} threads"


def test_stop_is_idempotent():
    feed = SampleFeed(lambda s: None, lambda u: None, lambda u: None)
    feed.start()
    feed.stop()
    feed.stop()


def test_a_raising_callback_does_not_kill_the_drain():
    seen = []

    def boom(s):
        seen.append(s)
        raise RuntimeError("callback blew up")

    feed = SampleFeed(boom, lambda u: None, lambda u: None)
    feed.start()
    for i in range(3):
        feed.submit_sample(BreathSample(t=i, amp=0.5, source_id="a"))
    time.sleep(0.3)
    feed.stop()
    assert len(seen) == 3, "drain thread died on the first exception"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_feed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'breath_midi.feed'`

- [ ] **Step 3: Write minimal implementation**

```python
# breath_midi/feed.py
"""
The hub's single calling thread.

EveryBreathHub._on_sample routes MIDI activity and drives per-device runtimes
without a lock, and says so: it assumes one caller.  Playback adds a second
producer, so rather than put a lock on the real-time MIDI path, every source
posts here and one drain thread makes the calls.  The invariant stays literally
true — the hub still sees exactly one thread.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable

from breath_midi.types import BreathSample

_NEW, _SAMPLE, _TIMEOUT = 0, 1, 2
_MAX = 8192


class SampleFeed:
    def __init__(
        self,
        on_sample: Callable[[BreathSample], None],
        on_new_device: Callable[[str], None],
        on_timeout: Callable[[str], None],
    ) -> None:
        self._on_sample = on_sample
        self._on_new_device = on_new_device
        self._on_timeout = on_timeout
        self._q: queue.Queue = queue.Queue(maxsize=_MAX)
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._drain, daemon=True,
                                        name="sample-feed")
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._q.put_nowait((None, None))
        t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=1.0)

    # ── producers: thread-safe, never block ──────────────────────────────────
    def _put(self, kind: int, payload) -> None:
        try:
            self._q.put_nowait((kind, payload))
        except queue.Full:
            # Dropping the newest sample is better than stalling a producer
            # thread that is reading a UDP socket.
            pass

    def submit_sample(self, s: BreathSample) -> None:
        self._put(_SAMPLE, s)

    def submit_new_device(self, uuid: str) -> None:
        self._put(_NEW, uuid)

    def submit_timeout(self, uuid: str) -> None:
        self._put(_TIMEOUT, uuid)

    # ── the one consumer ─────────────────────────────────────────────────────
    def _drain(self) -> None:
        while self._running:
            kind, payload = self._q.get()
            if kind is None:
                break
            try:
                if kind == _SAMPLE:
                    self._on_sample(payload)
                elif kind == _NEW:
                    self._on_new_device(payload)
                else:
                    self._on_timeout(payload)
            except Exception as exc:
                # One bad callback must not silence every device.
                print(f"[SampleFeed] callback raised: {exc}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_feed.py -q`
Expected: 4 passed

- [ ] **Step 5: Route the OSC source through the feed**

In `breath_midi/every_breath/hub.py::start_listening`, build the feed first and hand the
source the feed's submit methods instead of the hub's callbacks:

```python
self._feed = SampleFeed(self._on_sample, self._on_new_device, self._on_timeout)
self._feed.start()
source = MultiDeviceOscSource(
    port=self._osc_port,
    on_sample_cb=self._feed.submit_sample,
    on_new_device_cb=self._feed.submit_new_device,
    on_timeout_cb=self._feed.submit_timeout,
)
```

In `stop_listening`, stop the feed after the source and before releasing notes, but only
when no track is playing (Task 6 adds that check; for now stop it unconditionally).

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: everything passes, including `tests/test_fanout_integration.py`, which exercises
the OSC path end to end.

- [ ] **Step 7: Commit**

```bash
git add breath_midi/feed.py breath_midi/every_breath/hub.py tests/test_feed.py
git commit -m "refactor: one drain thread feeds the hub

_on_sample routes MIDI activity and drives per-device runtimes without a lock,
on the documented assumption of a single calling thread.  Playback is about to
add a second producer.  Rather than lock the real-time MIDI path, sources now
post to a queue and one thread makes the calls, so the assumption stays true.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Track playback source

**Files:**
- Create: `breath_midi/tracks/playback.py`
- Test: `tests/test_playback.py`

**Interfaces:**
- Consumes: `Track` (Task 3), `SampleFeed` (Task 4).
- Produces: `TrackPlaybackSource(track, feed, prefix)` with `start()`, `stop()`,
  `is_finished` and `uuid_for(index) -> str`. Emitted uuids are
  `f"{prefix}:{device.uuid}"` so a recorded performer never collides with the live
  phone it came from, and the same track loaded twice gives two performers.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_playback.py
import time
from breath_midi.feed import SampleFeed
from breath_midi.tracks.playback import TrackPlaybackSource
from .test_track_file import sample_track


def collect(track, prefix="pb1", settle=0.6):
    samples, new, timeouts = [], [], []
    feed = SampleFeed(samples.append, new.append, timeouts.append)
    feed.start()
    src = TrackPlaybackSource(track, feed, prefix=prefix)
    src.start()
    time.sleep(settle)
    src.stop()
    feed.stop()
    return samples, new, timeouts


def test_announces_each_device_before_its_first_sample():
    samples, new, _ = collect(sample_track())
    assert new == ["pb1:aaa", "pb1:bbb"]


def test_uuids_are_namespaced_so_a_live_phone_cannot_collide():
    samples, _, _ = collect(sample_track())
    assert all(s.source_id.startswith("pb1:") for s in samples)
    assert {s.source_id for s in samples} == {"pb1:aaa", "pb1:bbb"}


def test_same_track_twice_gives_independent_performers():
    a = TrackPlaybackSource(sample_track(), SampleFeed(lambda s: None, lambda u: None,
                                                       lambda u: None), prefix="pb1")
    b = TrackPlaybackSource(sample_track(), SampleFeed(lambda s: None, lambda u: None,
                                                       lambda u: None), prefix="pb2")
    assert a.uuid_for(0) != b.uuid_for(0)


def test_replays_every_sample_with_its_amplitude():
    samples, _, _ = collect(sample_track())
    assert [round(s.amp, 2) for s in samples] == [0.41, 0.23, 0.44]


def test_marks_itself_finished_at_the_end():
    src = TrackPlaybackSource(sample_track(),
                              SampleFeed(lambda s: None, lambda u: None, lambda u: None),
                              prefix="pb1")
    assert not src.is_finished
    src.start()
    time.sleep(0.6)
    assert src.is_finished
    src.stop()


def test_stop_partway_stops_emitting():
    track = sample_track()
    samples = []
    feed = SampleFeed(samples.append, lambda u: None, lambda u: None)
    feed.start()
    src = TrackPlaybackSource(track, feed, prefix="pb1")
    src.start()
    src.stop()
    time.sleep(0.3)
    feed.stop()
    assert len(samples) < len(track.samples)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_playback.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'breath_midi.tracks.playback'`

- [ ] **Step 3: Write minimal implementation**

```python
# breath_midi/tracks/playback.py
"""
Replay a track as extra performers in the choir.

Playback is additive, not a mode: recorded performers register as ordinary
devices and mix with live phones.  The hub cannot tell the difference, so they
get colours, notes, mute and solo for free, and when a track ends its devices
stop sending and the existing 5s timeout fades them out and releases their
notes.

Emitted uuids are prefixed, so a recording never collides with the live phone it
was captured from, and loading one track twice gives two independent performers.
"""
from __future__ import annotations

import threading
import time

from breath_midi.feed import SampleFeed
from breath_midi.tracks.file import Track
from breath_midi.types import BreathSample


class TrackPlaybackSource:
    def __init__(self, track: Track, feed: SampleFeed, prefix: str) -> None:
        self._track = track
        self._feed = feed
        self._prefix = prefix
        self._thread: threading.Thread | None = None
        self._running = False
        self._finished = False

    @property
    def is_finished(self) -> bool:
        return self._finished

    def uuid_for(self, index: int) -> str:
        return f"{self._prefix}:{self._track.devices[index].uuid}"

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._finished = False
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"playback-{self._prefix}")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=1.0)

    def _run(self) -> None:
        # Announce every device up front so the panel fills immediately rather
        # than one performer at a time as each happens to take its first breath.
        for i in range(len(self._track.devices)):
            self._feed.submit_new_device(self.uuid_for(i))

        t0 = time.monotonic()
        for t, i, amp in self._track.samples:
            if not self._running:
                return
            wait = t - (time.monotonic() - t0)
            if wait > 0:
                time.sleep(wait)
            self._feed.submit_sample(
                BreathSample(t=time.monotonic(), amp=float(amp),
                             source_id=self.uuid_for(i))
            )
        self._finished = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_playback.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add breath_midi/tracks/playback.py tests/test_playback.py
git commit -m "feat: play a track as extra performers alongside live phones

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Hub can load and stop tracks

**Files:**
- Modify: `breath_midi/every_breath/hub.py`
- Test: `tests/test_hub_tracks.py`

**Interfaces:**
- Produces: `hub.load_track(path: Path) -> str` returning the prefix it assigned, and
  `hub.stop_track(prefix: str) -> None`, plus `hub.playing_tracks -> list[str]`.
- The feed starts on first use by either the OSC listener or a track, and stops only when
  both are done.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_tracks.py
import time
from pathlib import Path
from breath_midi.tracks.file import write_track
from .test_track_file import sample_track
from breath_midi.every_breath.hub import EveryBreathHub
from .test_hold_triggers import base_config
from .test_track_file import sample_track
import pytest


@pytest.fixture
def hub():
    """A hub that never binds a UDP port — track tests do not need one."""
    h = EveryBreathHub(config=base_config(), osc_port=8813)
    yield h
    for prefix in list(h.playing_tracks):
        h.stop_track(prefix)


def test_loading_a_track_registers_its_devices(hub, tmp_path: Path):
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    prefix = hub.load_track(p)
    time.sleep(0.5)
    uuids = {e.uuid for e in hub.registry.all_entries()}
    assert f"{prefix}:aaa" in uuids and f"{prefix}:bbb" in uuids
    hub.stop_track(prefix)


def test_track_devices_carry_their_recorded_names(hub, tmp_path: Path):
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    prefix = hub.load_track(p)
    time.sleep(0.5)
    names = {e.name for e in hub.registry.all_entries()}
    assert "Ana" in names and "Bo" in names
    hub.stop_track(prefix)


def test_two_loads_of_one_track_do_not_collide(hub, tmp_path: Path):
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    a, b = hub.load_track(p), hub.load_track(p)
    assert a != b
    time.sleep(0.5)
    uuids = {e.uuid for e in hub.registry.all_entries()}
    assert {f"{a}:aaa", f"{b}:aaa"} <= uuids
    hub.stop_track(a)
    hub.stop_track(b)


def test_loading_a_track_does_not_change_detection_config(hub, tmp_path: Path):
    """The Ableton rule: the clip does not reconfigure the instrument."""
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    before = hub._config.detection
    prefix = hub.load_track(p)
    time.sleep(0.3)
    assert hub._config.detection == before
    hub.stop_track(prefix)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hub_tracks.py -q`
Expected: FAIL — `AttributeError: 'EveryBreathHub' object has no attribute 'load_track'`

- [ ] **Step 3: Write minimal implementation**

Add to `EveryBreathHub.__init__`: `self._feed = None`, `self._tracks = {}`,
`self._track_seq = 0`. Then:

```python
def _ensure_feed(self) -> SampleFeed:
    """Started by whichever of the listener or a track needs it first."""
    if self._feed is None:
        self._feed = SampleFeed(self._on_sample, self._on_new_device, self._on_timeout)
        self._feed.start()
    return self._feed


def _release_feed_if_idle(self) -> None:
    if not self._listening and not self._tracks and self._feed is not None:
        self._feed.stop()
        self._feed = None


def load_track(self, path: Path) -> str:
    """
    Add a saved performance to the choir.  Returns the prefix assigned to it.

    Deliberately does NOT touch config.detection.  The track's stored dials are
    provenance; applying them is a separate, explicit action.
    """
    from breath_midi.tracks.file import read_track
    from breath_midi.tracks.playback import TrackPlaybackSource

    track = read_track(path)
    self._track_seq += 1
    prefix = f"pb{self._track_seq}"

    if self._midi_sink is None:
        self._midi_sink = MidoMidiSink(activity_bus=self._activity_bus, source_id="eb")
        try:
            self._midi_sink.open(self._config.midi.out_port.strip() or None)
        except Exception as exc:
            print(f"[Tracks] MIDI open failed: {exc}")

    # Seed names and colours before playback announces the devices, so the panel
    # shows the performers the track was recorded with rather than Device 1..n.
    for i, d in enumerate(track.devices):
        uuid = f"{prefix}:{d.uuid}"
        self.registry.get_or_create(uuid)
        self.registry.set_name(uuid, d.name)
        self.registry.set_color(uuid, d.color)

    src = TrackPlaybackSource(track, self._ensure_feed(), prefix=prefix)
    self._tracks[prefix] = src
    src.start()
    return prefix


def stop_track(self, prefix: str) -> None:
    src = self._tracks.pop(prefix, None)
    if src is None:
        return
    src.stop()
    for uuid in [e.uuid for e in self.registry.all_entries()
                 if e.uuid.startswith(f"{prefix}:")]:
        runtime = self._runtimes.get(uuid)
        if runtime is not None:
            runtime.release()      # a stopped performer must not hold a key down
        self.registry.mark_disconnected(uuid)
    self._release_feed_if_idle()


@property
def playing_tracks(self) -> list[str]:
    return sorted(self._tracks)
```

Change `start_listening` to use `self._ensure_feed()` and `stop_listening` to call
`self._release_feed_if_idle()` instead of stopping the feed outright.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_hub_tracks.py -q`
Expected: 4 passed

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

- [ ] **Step 6: Commit**

```bash
git add breath_midi/every_breath/hub.py tests/test_hub_tracks.py
git commit -m "feat: hub loads and stops tracks as extra performers

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Bake the generated tracks

**Files:**
- Create: `scripts/bake_tracks.py`
- Create (output): `tracks/generated/*.breath.json`
- Test: `tests/test_bake_tracks.py`

**Interfaces:**
- Consumes: `Track`, `TrackDevice`, `write_track` (Task 3).
- Produces: `bake_all(out_dir: Path) -> list[Path]`, and the shape helpers
  `gen_sine(...)`, `gen_box(...)` returning `list[float]`.

The performers mirror the six in `rose_breath/dummy_data.js`, which were written as a
deliberate cast: a slow deep breather, a fast shallow one, an irregular one, a box
breather, and one that drops out to exercise the timeout path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bake_tracks.py
from pathlib import Path
from breath_midi.tracks.file import read_track
from scripts.bake_tracks import bake_all


def test_bakes_the_expected_tracks(tmp_path: Path):
    paths = bake_all(tmp_path)
    names = sorted(p.name for p in paths)
    assert names == sorted([
        "slow-and-deep.breath.json", "fast-and-shallow.breath.json",
        "irregular.breath.json", "box-breathing.breath.json",
        "dropout.breath.json", "group-of-four.breath.json",
    ])


def test_every_baked_track_reads_back(tmp_path: Path):
    for p in bake_all(tmp_path):
        t = read_track(p)
        assert t.source == "generated"
        assert t.samples, f"{p.name} is empty"
        assert t.duration_s > 0


def test_box_track_produces_holds_through_the_real_detector(tmp_path: Path):
    """The bake path and the FSM tests must agree about what box breathing is."""
    from breath_midi.signal.features import FeatureExtractor
    from breath_midi.types import Phase, ProcessedSample
    from .test_phase_fsm import make_detection

    bake_all(tmp_path)
    track = read_track(tmp_path / "box-breathing.breath.json")

    fx = FeatureExtractor(make_detection())
    phases = {
        fx.update(ProcessedSample(t=t, amp_raw=a, amp_proc=a, source_id="x")).phase
        for t, _, a in track.samples
    }
    assert Phase.HOLD in phases
    assert Phase.INHALE in phases and Phase.EXHALE in phases


def test_dropout_track_has_a_gap_long_enough_to_time_out(tmp_path: Path):
    bake_all(tmp_path)
    track = read_track(tmp_path / "dropout.breath.json")
    per_device: dict[int, list[float]] = {}
    for t, i, _ in track.samples:
        per_device.setdefault(i, []).append(t)
    gaps = [track.duration_s - max(ts) for ts in per_device.values()]
    assert max(gaps) > 5.0, "no performer is silent long enough to fade out"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bake_tracks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/__init__.py` (empty) and:

```python
# scripts/bake_tracks.py
"""
Write the generated tracks.

The shapes are the ones already proven in tests/test_phase_fsm.py, and the cast
mirrors rose_breath/dummy_data.js.  The output is an ordinary track file, so
generated and recorded tracks load through exactly one path and there is no
separate dummy-data mode to rot.

Run:  .venv/bin/python -m scripts.bake_tracks
"""
from __future__ import annotations

import math
import random
from datetime import datetime
from pathlib import Path

from breath_midi.config.model import DetectionConfig
from breath_midi.tracks.file import Track, TrackDevice, write_track

HZ = 50.0
DT = 1.0 / HZ

DEFAULT_DETECTION = DetectionConfig(
    derivative_enabled=True, derivative_smoothing_alpha=0.2,
    inhale_exit_delta=0.06, exhale_exit_delta=0.12, hold_exit_delta=0.15,
    hold_enabled=True, hold_still_tol=0.05, min_hold_ms=1500,
    hold_peak_band=0.80, hold_valley_band=0.20,
)


def gen_sine(period_s, seconds, lo=0.1, hi=0.9, jitter=0.0, seed=0) -> list[float]:
    r = random.Random(seed)
    mid, half = (hi + lo) / 2.0, (hi - lo) / 2.0
    out = []
    for i in range(int(seconds * HZ)):
        v = mid - half * math.cos(2 * math.pi * i / (period_s * HZ))
        out.append(max(0.0, min(1.0, v + (r.gauss(0, jitter) if jitter else 0.0))))
    return out


def gen_box(inhale_s, hold_s, cycles, lo=0.05, hi=0.9) -> list[float]:
    def ramp(a, b, secs):
        n = max(1, int(secs * HZ))
        return [a + (b - a) * (i / n) for i in range(n)]

    def flat(v, secs):
        return [v] * max(1, int(secs * HZ))

    out: list[float] = []
    for _ in range(cycles):
        out += ramp(lo, hi, inhale_s) + flat(hi, hold_s)
        out += ramp(hi, lo, inhale_s) + flat(lo, hold_s)
    return out


def _track(name, devices, series, source="generated") -> Track:
    """series: list of per-device amplitude lists, index-aligned with devices."""
    samples: list[tuple[float, int, float]] = []
    for i, amps in enumerate(series):
        for n, a in enumerate(amps):
            samples.append((n * DT, i, a))
    samples.sort(key=lambda s: (s[0], s[1]))
    duration = max((t for t, _, _ in samples), default=0.0)
    return Track(
        name=name, created=datetime.now().isoformat(timespec="seconds"),
        duration_s=duration, source=source, detection=DEFAULT_DETECTION,
        devices=devices, samples=samples,
    )


def _dev(uuid, name, color, inhale=54, exhale=55) -> TrackDevice:
    return TrackDevice(uuid, name, color, inhale, exhale)


def bake_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    specs = [
        ("slow-and-deep", "Slow & Deep",
         [_dev("slow", "Slow & Deep", (120, 170, 230))],
         [gen_sine(10.0, 120, 0.10, 0.95, seed=0)]),
        ("fast-and-shallow", "Fast & Shallow",
         [_dev("fast", "Fast & Shallow", (230, 150, 90))],
         [gen_sine(2.5, 120, 0.10, 0.45, seed=1)]),
        ("irregular", "Irregular",
         [_dev("irr", "Irregular", (200, 110, 180))],
         [gen_sine(5.0, 120, 0.10, 0.80, jitter=0.02, seed=2)]),
        ("box-breathing", "Box Breathing",
         [_dev("box", "Box Breathing", (120, 210, 150))],
         [gen_box(4.0, 4.0, cycles=8)]),
    ]
    for fname, title, devices, series in specs:
        p = out_dir / f"{fname}.breath.json"
        write_track(p, _track(title, devices, series))
        written.append(p)

    # One performer stops early: the gap is longer than the hub's 5s device
    # timeout, so loading this track exercises the fade-out and note release.
    p = out_dir / "dropout.breath.json"
    write_track(p, _track(
        "Dropout",
        [_dev("stayer", "Stayer", (150, 200, 120)),
         _dev("leaver", "Leaver", (220, 120, 120), 56, 57)],
        [gen_sine(5.0, 60, seed=3), gen_sine(5.0, 25, seed=4)],
    ))
    written.append(p)

    # A full group, for checking the panel and MIDI with several at once.
    p = out_dir / "group-of-four.breath.json"
    write_track(p, _track(
        "Group of four",
        [_dev("g1", "Ana", (220, 120, 90), 54, 55),
         _dev("g2", "Bo", (90, 160, 220), 56, 57),
         _dev("g3", "Cy", (200, 200, 110), 58, 59),
         _dev("g4", "Di", (150, 120, 220), 60, 61)],
        [gen_sine(5.0, 90, seed=5), gen_sine(6.0, 90, seed=6),
         gen_sine(4.5, 90, jitter=0.015, seed=7), gen_box(3.0, 2.0, cycles=12)],
    ))
    written.append(p)
    return written


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    for path in bake_all(root / "tracks" / "generated"):
        print(f"wrote {path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bake_tracks.py -q`
Expected: 4 passed

- [ ] **Step 5: Bake the real files**

Run: `.venv/bin/python -m scripts.bake_tracks`
Expected: six paths printed under `tracks/generated/`.

- [ ] **Step 6: Commit**

```bash
git add scripts/ tracks/generated/ tests/test_bake_tracks.py
git commit -m "feat: bake six generated tracks from the tested breath shapes

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Load and stop tracks from the UI

**Files:**
- Modify: `breath_midi/ui/group_breath_tab.py` (the Tracks row, around line 165)
- Test: `tests/test_tracks_ui.py`

**Interfaces:**
- Consumes: `hub.load_track`, `hub.stop_track`, `hub.playing_tracks` (Task 6).
- Produces: tags `gb_track_load`, `gb_track_stop`, `gb_track_list`.

The existing `_tray_button("gb_track_import", into_tray=True)` becomes the load control and
keeps its drawn icon. Clicks use the same mouse-edge polling as the QR and Wi-Fi icons,
because a drawlist has no callback of its own.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracks_ui.py
import dearpygui.dearpygui as dpg
import pytest
from breath_midi.ui.widgets.tray_icon import tray_button


@pytest.fixture
def ctx():
    dpg.create_context()
    with dpg.window(tag="root"):
        yield "root"
    dpg.destroy_context()


def test_track_row_has_load_and_stop(ctx):
    from breath_midi.ui.group_breath_tab import build_track_row
    build_track_row(on_load=lambda: None, on_stop=lambda: None)
    assert dpg.does_item_exist("gb_track_load")
    assert dpg.does_item_exist("gb_track_stop")
    assert dpg.does_item_exist("gb_track_list")


def test_track_list_starts_empty(ctx):
    from breath_midi.ui.group_breath_tab import build_track_row, set_track_list
    build_track_row(on_load=lambda: None, on_stop=lambda: None)
    assert dpg.get_value("gb_track_list") == ""
    set_track_list(["group-of-four"])
    assert "group-of-four" in dpg.get_value("gb_track_list")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tracks_ui.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_track_row'`

- [ ] **Step 3: Write minimal implementation**

Extract the existing Tracks row into a function and add the pieces:

```python
def build_track_row(on_load, on_stop) -> None:
    """The Tracks row: load icon, stop button, and what is playing."""
    with dpg.group(horizontal=True, tag="gb_track_row"):
        dpg.add_text("Tracks", color=(140, 140, 140))
        dpg.add_spacer(width=8)
        _tray_button("gb_track_load", into_tray=True)
        dpg.add_spacer(width=6)
        dpg.add_button(label="Stop", tag="gb_track_stop", callback=lambda: on_stop())
    dpg.add_text("", tag="gb_track_list", color=(120, 120, 120), wrap=300)


def set_track_list(names: list[str]) -> None:
    if dpg.does_item_exist("gb_track_list"):
        dpg.set_value("gb_track_list", ", ".join(names))
```

In `GroupBreathTab`, add the load handler and extend the existing click poll:

```python
def _on_load_track(self) -> None:
    """Open the generated folder; a track is added to the choir, not swapped in."""
    root = Path(__file__).resolve().parents[2]
    dpg.add_file_dialog(
        directory_selector=False, show=True, width=700, height=400,
        default_path=str(root / "tracks"),
        callback=lambda _s, app_data: self._load_track_file(app_data),
    )

def _load_track_file(self, app_data) -> None:
    path = Path(app_data.get("file_path_name", ""))
    if not path.exists():
        return
    try:
        self._hub.load_track(path)
    except ValueError as exc:
        print(f"[Tracks] {path.name}: {exc}")
```

In `_poll_header_clicks`, add a branch for `gb_track_load` using the same
`edge and hovered(...)` pattern already used for the QR and Wi-Fi icons. In `update()`,
call `set_track_list(self._hub.playing_tracks)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tracks_ui.py -q`
Expected: 2 passed

- [ ] **Step 5: Run the whole suite, then check by hand**

Run: `.venv/bin/python -m pytest -q`
Then: `.venv/bin/python -m breath_midi.app`

Confirm, with **no phones connected**: turn the Group Breath circle on, load
`tracks/generated/group-of-four.breath.json`, and check that four performers appear in the
strip panel with their names, the waveforms move, the rhombus changes phase, and MIDI
reaches Ableton. Then load `dropout.breath.json` and confirm "Leaver" fades out on its own
about five seconds after it stops. Quit.

- [ ] **Step 6: Commit**

```bash
git add breath_midi/ui/group_breath_tab.py tests/test_tracks_ui.py
git commit -m "feat: load a track into the choir from the Tracks row

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# STAGE C — RECORDING

### Task 9: Track recorder

**Files:**
- Create: `breath_midi/tracks/recorder.py`
- Test: `tests/test_recorder.py`

**Interfaces:**
- Produces: `TrackRecorder(detection, name)` with `note(uuid, amp)`,
  `set_device_meta(uuid, name, color, inhale_note, exhale_note)`,
  `to_track() -> Track` and `sample_count`.
- Timestamps are taken at `note()` time, relative to the first sample.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recorder.py
import time
from breath_midi.tracks.recorder import TrackRecorder
from .test_presets import make_det


def test_records_samples_in_order():
    r = TrackRecorder(make_det(), name="take 1")
    for i in range(5):
        r.note("phone-a", i / 10)
        time.sleep(0.01)
    assert r.sample_count == 5
    track = r.to_track()
    assert [round(a, 2) for _, _, a in track.samples] == [0.0, 0.1, 0.2, 0.3, 0.4]
    assert [t for t, _, _ in track.samples] == sorted(t for t, _, _ in track.samples)


def test_first_sample_is_at_time_zero():
    r = TrackRecorder(make_det(), name="take 1")
    time.sleep(0.05)
    r.note("phone-a", 0.5)
    assert r.to_track().samples[0][0] == 0.0


def test_devices_are_indexed_in_first_seen_order():
    r = TrackRecorder(make_det(), name="take 1")
    r.note("b", 0.1)
    r.note("a", 0.2)
    r.note("b", 0.3)
    track = r.to_track()
    assert [d.uuid for d in track.devices] == ["b", "a"]
    assert [i for _, i, _ in track.samples] == [0, 1, 0]


def test_device_metadata_is_carried_through():
    r = TrackRecorder(make_det(), name="take 1")
    r.note("a", 0.1)
    r.set_device_meta("a", "Ana", (10, 20, 30), 54, 55)
    d = r.to_track().devices[0]
    assert (d.name, d.color, d.inhale_note) == ("Ana", (10, 20, 30), 54)


def test_records_the_dials_it_was_given():
    det = make_det(inhale_exit_delta=0.09)
    r = TrackRecorder(det, name="take 1")
    r.note("a", 0.1)
    assert r.to_track().detection == det


def test_source_is_recorded():
    r = TrackRecorder(make_det(), name="take 1")
    r.note("a", 0.1)
    assert r.to_track().source == "recorded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recorder.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'breath_midi.tracks.recorder'`

- [ ] **Step 3: Write minimal implementation**

```python
# breath_midi/tracks/recorder.py
"""
Capture live breath into a track.

A tap, not a source: the recorder sits beside the hub's sample path and copies
what goes past.  It stores the raw amplitude the phone sent, never anything the
detector made of it, so a recording can be replayed against different dials.
"""
from __future__ import annotations

import time
from datetime import datetime

from breath_midi.config.model import DetectionConfig
from breath_midi.tracks.file import Track, TrackDevice


class TrackRecorder:
    def __init__(self, detection: DetectionConfig, name: str) -> None:
        self._detection = detection
        self._name = name
        self._t0: float | None = None
        self._order: list[str] = []
        self._meta: dict[str, TrackDevice] = {}
        self._samples: list[tuple[float, int, float]] = []

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def note(self, uuid: str, amp: float) -> None:
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now
        if uuid not in self._order:
            self._order.append(uuid)
        self._samples.append((now - self._t0, self._order.index(uuid), float(amp)))

    def set_device_meta(self, uuid, name, color, inhale_note, exhale_note) -> None:
        self._meta[uuid] = TrackDevice(uuid, name, tuple(color),
                                       int(inhale_note), int(exhale_note))

    def to_track(self) -> Track:
        devices = [
            self._meta.get(u, TrackDevice(u, u, (170, 170, 170), 54, 55))
            for u in self._order
        ]
        duration = max((t for t, _, _ in self._samples), default=0.0)
        return Track(
            name=self._name,
            created=datetime.now().isoformat(timespec="seconds"),
            duration_s=duration, source="recorded",
            detection=self._detection, devices=devices, samples=self._samples,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recorder.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add breath_midi/tracks/recorder.py tests/test_recorder.py
git commit -m "feat: record live breath into a track

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Record from the UI, and ignore recordings in git

**Files:**
- Modify: `breath_midi/every_breath/hub.py` (the tap)
- Modify: `breath_midi/ui/group_breath_tab.py` (record toggle)
- Modify: `.gitignore`
- Test: `tests/test_hub_recording.py`

**Interfaces:**
- Produces: `hub.start_recording(name: str) -> None`, `hub.stop_recording() -> Path | None`,
  `hub.is_recording -> bool`.
- Recordings are written to `tracks/recordings/<name>.breath.json`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_recording.py
import time
from pathlib import Path
from breath_midi.tracks.file import read_track
from breath_midi.every_breath.hub import EveryBreathHub
from breath_midi.types import BreathSample
from .test_hold_triggers import base_config
import pytest


@pytest.fixture
def hub():
    h = EveryBreathHub(config=base_config(), osc_port=8814)
    yield h
    for prefix in list(h.playing_tracks):
        h.stop_track(prefix)


def test_records_live_samples(hub, tmp_path: Path):
    hub._recordings_dir = tmp_path
    hub.registry.get_or_create("phone-a")
    hub.start_recording("take one")
    for i in range(5):
        hub._on_sample(BreathSample(t=i * 0.02, amp=i / 10, source_id="phone-a"))
    path = hub.stop_recording()
    assert path is not None and path.exists()
    track = read_track(path)
    assert len(track.samples) == 5
    assert track.source == "recorded"


def test_not_recording_by_default(hub):
    assert hub.is_recording is False


def test_stop_without_start_returns_none(hub):
    assert hub.stop_recording() is None


def test_recording_carries_the_current_dials(hub, tmp_path: Path):
    hub._recordings_dir = tmp_path
    hub.registry.get_or_create("phone-a")
    hub.start_recording("take two")
    hub._on_sample(BreathSample(t=0.0, amp=0.5, source_id="phone-a"))
    track = read_track(hub.stop_recording())
    assert track.detection == hub._config.detection


def test_recording_is_disabled_while_a_track_plays(hub, tmp_path: Path):
    """Recording a playback would only make a lossy copy of a file we have."""
    from breath_midi.tracks.file import write_track
    from .test_track_file import sample_track
    p = tmp_path / "t.breath.json"
    write_track(p, sample_track())
    hub._recordings_dir = tmp_path
    prefix = hub.load_track(p)
    hub.start_recording("nope")
    assert hub.is_recording is False
    hub.stop_track(prefix)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hub_recording.py -q`
Expected: FAIL — `AttributeError: 'EveryBreathHub' object has no attribute 'start_recording'`

- [ ] **Step 3: Write minimal implementation**

In `EveryBreathHub.__init__`: `self._recorder = None` and
`self._recordings_dir = Path(__file__).resolve().parents[2] / "tracks" / "recordings"`.

```python
@property
def is_recording(self) -> bool:
    return self._recorder is not None


def start_recording(self, name: str) -> None:
    """Capture live breath.  Refused while a track is playing."""
    if self._tracks:
        print("[Tracks] not recording: a track is playing")
        return
    from breath_midi.tracks.recorder import TrackRecorder
    self._recorder = TrackRecorder(self._config.detection, name=name)


def stop_recording(self) -> Path | None:
    rec, self._recorder = self._recorder, None
    if rec is None:
        return None
    for entry in self.registry.all_entries():
        rec.set_device_meta(entry.uuid, entry.name, entry.color,
                            entry.inhale_note, entry.exhale_note)
    from breath_midi.tracks.file import write_track
    safe = "".join(c for c in rec.to_track().name if c.isalnum() or c in " -_").strip()
    path = self._recordings_dir / f"{safe or 'take'}.breath.json"
    write_track(path, rec.to_track())
    return path
```

In `_on_sample`, immediately after the WebSocket publish, add:

```python
        if self._recorder is not None:
            self._recorder.note(uuid, float(sample.amp))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_hub_recording.py -q`
Expected: 5 passed

- [ ] **Step 5: Add the record control and the gitignore**

In the Tracks row, add a record toggle next to the existing export icon:

```python
        dpg.add_spacer(width=6)
        dpg.add_button(label="Rec", tag="gb_track_record", callback=lambda: on_record())
```

`on_record` calls `hub.start_recording(...)` or `hub.stop_recording()` and recolours the
button red while recording. Append to `.gitignore`:

```
# Recordings are of real people, with their names attached, and this repo is public.
tracks/recordings/
```

- [ ] **Step 6: Run the whole suite, then check by hand**

Run: `.venv/bin/python -m pytest -q`
Then, with a phone connected: record ten seconds, stop, confirm the file appears under
`tracks/recordings/`, then load it and confirm it replays as a performer.
Run `git status` and confirm the recording does **not** appear as untracked.

- [ ] **Step 7: Commit**

```bash
git add breath_midi/every_breath/hub.py breath_midi/ui/group_breath_tab.py \
        .gitignore tests/test_hub_recording.py
git commit -m "feat: record live breath to a track, and keep recordings out of git

Recordings carry performer names and a detailed trace of how someone was
breathing.  This repo is public, so tracks/recordings/ is ignored while
tracks/generated/ ships.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Notes for whoever executes this

**The invariant that shaped Task 4.** `hub._on_sample` deliberately runs lock-free and
documents that it assumes one calling thread. Do not "simplify" the feed away by having
playback call the hub directly — that reintroduces exactly the race the comment warns about,
and it would show up as misrouted MIDI activity under load, which is miserable to diagnose
live.

**Verify against a phone before trusting any of this.** The retracement dials shipped on
simulation alone and have never been checked against real hardware. Generated tracks are
clean maths; they will not reproduce the sensor noise that caused the original chatter. The
first real recording is the first honest test this system has had.
