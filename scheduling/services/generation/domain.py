"""Data shapes exchanged between the generation modules.

Plain frozen dataclasses holding primitives, ids and display strings. Nothing here
is a Django model instance and nothing here is a Phase 8 solver type: the bundle is
the adapter's own view of the problem, so the preview layer never needs to touch
the database again and no ORM object can leak into a response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from scheduling.services.solver import (
    PlacementCandidate,
    ScheduledPlacement,
    SessionDemand,
    SolverProblem,
    SolverResult,
)


@dataclass(frozen=True)
class CourseInfo:
    """Shallow course summary."""

    id: int
    code: str
    name: str


@dataclass(frozen=True)
class OfferingInfo:
    """Shallow offering summary."""

    id: int
    offering_code: str


@dataclass(frozen=True)
class ComponentInfo:
    """Shallow teaching-component summary, plus what it needs from the grid."""

    id: int
    component_type: str
    label: str
    session_duration_minutes: int
    weekly_minutes: int
    course: CourseInfo
    offering: OfferingInfo


@dataclass(frozen=True)
class SlotInfo:
    """One teaching period as the preview shows it."""

    id: int
    sequence: int
    label: str
    start_time: str
    end_time: str


@dataclass(frozen=True)
class RoomInfo:
    """Shallow room summary."""

    id: int
    code: str
    name: str


@dataclass(frozen=True)
class InstructorInfo:
    """Shallow instructor summary."""

    id: int
    full_name: str


@dataclass(frozen=True)
class GroupInfo:
    """Shallow student-group summary."""

    id: int
    code: str
    name: str


@dataclass(frozen=True)
class PlacementInstructor:
    """An instructor as used by one placement, with the role held on the component."""

    instructor: InstructorInfo
    assignment_role: str | None = None


@dataclass(frozen=True)
class SessionContext:
    """Everything needed to describe a session without further queries."""

    session_id: str
    ordinal: int
    component: ComponentInfo
    instructor_ids: tuple[int, ...]
    student_group_ids: tuple[int, ...]
    assignment_roles: Mapping[int, str] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class SessionCandidateCount:
    """How many candidates one session was offered, for diagnostics."""

    session_id: str
    component_id: int
    candidate_count: int


@dataclass(frozen=True)
class GenerationDiagnostics:
    """Counts gathered while building, never presented as a root cause."""

    components: int
    sessions: int
    candidates: int
    min_candidates_per_session: int
    max_candidates_per_session: int
    sessions_with_fewest_candidates: tuple[SessionCandidateCount, ...]
    sessions_without_candidates: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Plain, JSON-serializable representation."""
        return {
            "components": self.components,
            "sessions": self.sessions,
            "candidates": self.candidates,
            "min_candidates_per_session": self.min_candidates_per_session,
            "max_candidates_per_session": self.max_candidates_per_session,
            "sessions_with_fewest_candidates": [
                {
                    "session_id": item.session_id,
                    "component_id": item.component_id,
                    "candidate_count": item.candidate_count,
                }
                for item in self.sessions_with_fewest_candidates
            ],
            "sessions_without_candidates": list(self.sessions_without_candidates),
        }


@dataclass(frozen=True)
class ProblemBundle:
    """The built problem plus everything the preview needs to describe it."""

    solver_problem: SolverProblem
    sessions: tuple[SessionDemand, ...]
    candidates: tuple[PlacementCandidate, ...]
    session_context: Mapping[str, SessionContext]
    slot_map: Mapping[int, SlotInfo]
    room_map: Mapping[int, RoomInfo]
    instructor_map: Mapping[int, InstructorInfo]
    group_map: Mapping[int, GroupInfo]
    diagnostics: GenerationDiagnostics
    issues: tuple[Any, ...] = ()

    @property
    def is_buildable(self) -> bool:
        """False when something stopped generation before the engine could run."""
        return not self.issues


@dataclass(frozen=True)
class GenerationSummary:
    """Success summary counts."""

    components: int
    sessions: int
    candidates: int
    placements: int

    def as_dict(self) -> dict[str, int]:
        return {
            "components": self.components,
            "sessions": self.sessions,
            "candidates": self.candidates,
            "placements": self.placements,
        }


@dataclass(frozen=True)
class PreviewPlacement:
    """One scheduled session, ready to serialize."""

    session_id: str
    course: CourseInfo
    offering: OfferingInfo
    teaching_component: ComponentInfo
    day_of_week: int
    day_display: str
    slots: tuple[SlotInfo, ...]
    start_time: str
    end_time: str
    room: RoomInfo | None
    instructors: tuple[PlacementInstructor, ...]
    student_groups: tuple[GroupInfo, ...]
    penalty: int
    raw: ScheduledPlacement | None = None

    def as_dict(self) -> dict[str, Any]:
        """Plain, JSON-serializable representation."""
        return {
            "session_id": self.session_id,
            "course": {"id": self.course.id, "code": self.course.code, "name": self.course.name},
            "offering": {"id": self.offering.id, "offering_code": self.offering.offering_code},
            "teaching_component": {
                "id": self.teaching_component.id,
                "component_type": self.teaching_component.component_type,
                "label": self.teaching_component.label,
            },
            "day_of_week": self.day_of_week,
            "day_display": self.day_display,
            "slots": [
                {
                    "id": slot.id,
                    "sequence": slot.sequence,
                    "label": slot.label,
                    "start_time": slot.start_time,
                    "end_time": slot.end_time,
                }
                for slot in self.slots
            ],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "room": (
                None
                if self.room is None
                else {"id": self.room.id, "code": self.room.code, "name": self.room.name}
            ),
            "instructors": [
                {
                    "id": item.instructor.id,
                    "full_name": item.instructor.full_name,
                    "assignment_role": item.assignment_role,
                }
                for item in self.instructors
            ],
            "student_groups": [
                {"id": group.id, "code": group.code, "name": group.name}
                for group in self.student_groups
            ],
            "penalty": self.penalty,
        }


@dataclass(frozen=True)
class GenerationOutcome:
    """The complete result of one generation request.

    ``rejected`` marks the two cases the endpoint answers ``409`` for: the Phase 7
    gate refused the scope, or no candidate could be built for some session. All
    other outcomes, including an infeasible or timed-out solve, are a normal ``200``
    because the request itself was valid.
    """

    generated: bool = False
    persisted: bool = False
    rejected: bool = False
    reason: str | None = None
    message: str = ""
    semester: Any = None
    department: Any = None
    validation: Any = None
    solver: SolverResult | None = None
    summary: GenerationSummary | None = None
    placements: tuple[PreviewPlacement, ...] = ()
    generation_issues: tuple[Any, ...] = ()
    diagnostics: GenerationDiagnostics | None = None


__all__ = [
    "ComponentInfo",
    "CourseInfo",
    "GenerationDiagnostics",
    "GenerationOutcome",
    "GenerationSummary",
    "GroupInfo",
    "InstructorInfo",
    "OfferingInfo",
    "PlacementInstructor",
    "PreviewPlacement",
    "ProblemBundle",
    "RoomInfo",
    "SessionCandidateCount",
    "SessionContext",
    "SlotInfo",
]
