"""Engine result value objects.

The result is deliberately plain data: application statuses, primitives and
dictionaries. No OR-Tools object and no Django object is returned, so a result can
be logged, diffed or rendered as JSON without the caller knowing CP-SAT exists.

A status is never upgraded or downgraded on the way out. ``UNKNOWN`` (typically a
time limit) stays ``UNKNOWN``, and a merely feasible solution is never reported as
optimal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class SolverStatus(str, Enum):
    """Stable application-level outcome of a solve.

    ``OPTIMAL`` and ``FEASIBLE`` carry placements; the others never do.
    """

    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    MODEL_INVALID = "MODEL_INVALID"
    UNKNOWN = "UNKNOWN"

    @property
    def has_placements(self) -> bool:
        """True when a solution exists, whether proven optimal or not."""
        return self in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)


@dataclass(frozen=True)
class ScheduledPlacement:
    """One session as chosen by the solver.

    Mirrors the accepted candidate plus the identifiers of the demand it serves,
    so a caller can persist or render it without looking anything up.
    """

    session_id: str
    component_id: str
    candidate_id: str
    day_of_week: int
    slot_ids: tuple[int, ...]
    room_id: int | None = None
    instructor_ids: tuple[int, ...] = ()
    student_group_ids: tuple[int, ...] = ()
    penalty: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict, hash=False)

    @property
    def first_slot_id(self) -> int:
        """Lowest slot id, used for deterministic ordering (0 when unset)."""
        return min(self.slot_ids) if self.slot_ids else 0

    @property
    def sort_key(self) -> tuple:
        """Documented deterministic order: day, first slot, component, session, candidate."""
        return (
            self.day_of_week,
            self.first_slot_id,
            self.component_id,
            self.session_id,
            self.candidate_id,
        )

    def as_dict(self) -> dict[str, Any]:
        """Plain, JSON-serializable representation."""
        return {
            "session_id": self.session_id,
            "component_id": self.component_id,
            "candidate_id": self.candidate_id,
            "day_of_week": self.day_of_week,
            "slot_ids": list(self.slot_ids),
            "room_id": self.room_id,
            "instructor_ids": list(self.instructor_ids),
            "student_group_ids": list(self.student_group_ids),
            "penalty": self.penalty,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SolverResult:
    """What one solve produced, including why it ended."""

    status: SolverStatus
    placements: tuple[ScheduledPlacement, ...] = ()
    objective_value: int | None = None
    wall_time_seconds: float = 0.0
    num_conflicts: int = 0
    num_branches: int = 0
    message: str = ""

    @property
    def is_success(self) -> bool:
        """True when a complete, conflict-free assignment exists."""
        return self.status.has_placements

    @property
    def placement_count(self) -> int:
        """Number of sessions placed (0 when no solution was found)."""
        return len(self.placements)

    def placement_for_session(self, session_id: str) -> ScheduledPlacement | None:
        """The placement chosen for ``session_id``, or ``None``."""
        for placement in self.placements:
            if placement.session_id == session_id:
                return placement
        return None

    def as_dict(self) -> dict[str, Any]:
        """Plain, JSON-serializable representation of the whole result."""
        return {
            "status": self.status.value,
            "placements": [placement.as_dict() for placement in self.placements],
            "objective_value": self.objective_value,
            "wall_time_seconds": self.wall_time_seconds,
            "num_conflicts": self.num_conflicts,
            "num_branches": self.num_branches,
            "message": self.message,
        }


__all__ = ["ScheduledPlacement", "SolverResult", "SolverStatus"]
