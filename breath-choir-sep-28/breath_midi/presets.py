"""
Named detection presets.

config.toml holds exactly one dial set, and autosave rewrites it on every knob
turn, so a tuning you liked is gone the moment you nudge the next dial.  A
preset is that dial set, named and kept.

Presets are *intent* — a dial set you chose and named.  A track's stored dials
are *provenance* — whatever happened to be set when it was captured.  Same ten
numbers, different meaning, so they live in different files and neither is
written by the other.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import tomli_w

try:
    import tomllib  # pyright: ignore[reportMissingImports]
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

from breath_midi.config.model import DetectionConfig

_SUFFIX = ".preset.toml"


def _path(directory: Path, name: str) -> Path:
    """
    Resolve a preset name to a file.

    The name becomes a filename, so it is checked rather than sanitised: a
    silent rewrite would save "hive/show" as something the user never typed and
    cannot find again.  A leading dot is refused too — it would hide the file
    from the listing that is meant to show it.
    """
    if not name.strip():
        raise ValueError("preset name must not be blank")
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"illegal preset name: {name!r}")
    return directory / f"{name}{_SUFFIX}"


def save_preset(directory: Path, name: str, detection: DetectionConfig) -> Path:
    """Write a dial set under `name`, overwriting any preset already there."""
    path = _path(directory, name)
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(asdict(detection)), encoding="utf-8")
    return path


def load_preset(directory: Path, name: str) -> DetectionConfig:
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("tomllib not available; use Python 3.11+")
    path = _path(directory, name)
    if not path.exists():
        raise FileNotFoundError(f"no preset named {name!r}")
    return DetectionConfig(**tomllib.loads(path.read_text(encoding="utf-8")))


def list_presets(directory: Path) -> list[str]:
    """Every preset name in the folder, sorted.  Missing folder means none."""
    if not directory.exists():
        return []
    return sorted(p.name[: -len(_SUFFIX)] for p in directory.glob(f"*{_SUFFIX}"))
