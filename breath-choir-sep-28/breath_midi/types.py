from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class BreathSample:
    t: float
    amp: float
    source_id: str


@dataclass(frozen=True)
class ProcessedSample:
    t: float
    amp_raw: float
    amp_proc: float
    source_id: str


class Phase(str, Enum):
    """
    Breath phases.

    Three states drive the performance: INHALE, HOLD, EXHALE.  The cycle
    visits HOLD twice — once at the top of a breath and once at the bottom —
    but it is the *same* state and fires the same note.  Where in the range a
    hold happened is available from the amplitude for display purposes; it is
    not a separate phase.

    A hold requires the breath to be inside the peak band or the valley band
    and to stay still there.  A pause halfway up an inhale is a hesitation,
    not a hold, and leaves the phase unchanged.

    REST is *not* part of the cycle.  It is the cold-start state before the
    first breath is seen; once breathing begins the FSM never returns to it.
    A device that goes quiet is handled at the hub level by the device
    timeout, not here.
    """

    REST = "rest"
    INHALE = "inhale"
    HOLD = "hold"
    EXHALE = "exhale"


@dataclass(frozen=True)
class CycleMetrics:
    period_s: float
    peak_amp: float


@dataclass(frozen=True)
class RollingStats:
    avg_period_s: float | None
    avg_peak_amp: float | None


@dataclass(frozen=True)
class FeatureFrame:
    t: float
    amp: float
    d_amp: float
    phase: Phase
    phase_changed: bool
    phase_entered: Phase | None
    cycle_completed: bool
    cycle: CycleMetrics | None
    rolling: RollingStats
    source_id: str


class TriggerKind(str, Enum):
    NOTE_ON = "note_on"
    NOTE_OFF = "note_off"
    CC = "cc"


@dataclass(frozen=True)
class TriggerEvent:
    name: str
    kind: TriggerKind
    t: float
    value: float | int | None = None
    meta: dict[str, Any] | None = None
    mono_t: float = 0.0


@dataclass(frozen=True)
class RuntimeState:
    t: float
    amp: float
    phase: Phase
    d_amp: float
    last_cycle: CycleMetrics | None
    rolling: RollingStats
    recent_triggers: list[TriggerEvent]
    source_id: str
    input_mode: str = "osc"
    input_status: str = "disconnected"
    rx_hz: float = 0.0
    consistent_streak: int = 0
    consistent_target: int = 0
    consistent_held: bool = False

