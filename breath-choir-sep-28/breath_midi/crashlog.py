"""
Crash capture and per-frame resilience.

Two problems this solves, both of which only bite in performance:

1. Launched from the .app bundle there is no terminal, so an uncaught exception
   kills the window with no visible reason. Everything goes to a log file too.
2. A single bad frame — a stale DPG tag, a device disconnecting at the wrong
   moment — should not end the set. `guard()` logs and keeps the loop running.

The suppression counter matters: a broken frame usually breaks *every* frame, so
without it a crash becomes tens of thousands of log lines a minute.
"""

from __future__ import annotations

import sys
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[1] / "breath.log"

_MAX_REPEATS = 5
_seen: dict[str, int] = {}


def _write(header: str, body: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"\n===== {stamp}  {header} =====\n{body}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass
    # Still print, for when there *is* a terminal.
    print(line, file=sys.stderr, flush=True)


def install() -> None:
    """Route uncaught exceptions to the log as well as stderr."""
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        _write("UNCAUGHT", "".join(traceback.format_exception(exc_type, exc, tb)))
        previous(exc_type, exc, tb)

    sys.excepthook = hook
    _write("START", f"breath.log — {LOG_PATH}")


@contextmanager
def guard(label: str):
    """
    Run a block; on failure log it and carry on.

    Used around the per-frame UI update. Losing one frame is invisible; losing
    the app mid-performance is not.
    """
    try:
        yield
    except Exception:
        tb = traceback.format_exc()
        key = f"{label}:{tb.splitlines()[-1] if tb.splitlines() else label}"
        count = _seen.get(key, 0) + 1
        _seen[key] = count
        if count <= _MAX_REPEATS:
            suffix = "  (further repeats suppressed)" if count == _MAX_REPEATS else ""
            _write(f"{label} — recovered, occurrence {count}{suffix}", tb)


def error_counts() -> dict[str, int]:
    """Distinct recovered errors and how often each fired. For the UI."""
    return dict(_seen)
