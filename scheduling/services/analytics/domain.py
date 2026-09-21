"""Value objects of schedule analytics.

Analytics never invent data: they reshape what a persisted version already stores.
The objects here are that reshape. An :class:`EntryFacts` is one entry with every
value a metric needs — the snapshot display strings, the occupied minute span, the
period ids, the persisted instructors and groups — and the report objects are
aggregates over those facts.

Two categories are separated on purpose, because only one of them is historical:

* **snapshot-stable** metrics come from the version alone (sessions, minutes,
  workloads, gaps, penalties). Renaming a live course, room, department, instructor
  or group changes nothing here.
* **current-configuration** metrics need a denominator that the snapshot does not
  contain, such as a room's present weekly availability. Every room row carries the
  ``utilization_basis`` label so a live denominator is never mistaken for history.

Nothing here writes, and nothing here is a Django object: every value is a primitive
that serializes straight to JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

#: Label of the denominator basis used by room utilization rows.
UTILIZATION_BASIS = "CURRENT_ROOM_AVAILABILITY"

HOUR_IN_MINUTES = 60


def hours_of(minutes: int) -> float:
    """Decimal hours for a minute count, rounded for display.

    Minutes stay the authoritative integer figure; hours are a convenience derived
    from them, never a second source of truth.
    """
    return round(minutes / HOUR_IN_MINUTES, 2)


def average(total: int, count: int) -> float:
    """Rounded mean, or 0 when there is nothing to average.

    Aggregates report ``0`` rather than ``None`` when a total exists but no rows do;
    ``None`` is reserved for a genuinely missing basis, such as a room denominator
    that current configuration cannot provide.
    """
    if count <= 0:
        return 0.0
    return round(total / count, 2)


@dataclass(frozen=True)
class SnapshotRef:
    """A shallow display reference taken from the version's snapshot columns."""

    id: int | None
    code: str
    name: str

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "code": self.code, "name": self.name}


@dataclass(frozen=True)
class InstructorFact:
    """One persisted instructor of one entry."""

    instructor_id: int
    full_name: str
    assignment_role: str


@dataclass(frozen=True)
class GroupFact:
    """One persisted student group of one entry, with its own department snapshot."""

    group_id: int
    code: str
    name: str
    department_id: int | None
    department_code: str
    department_name: str

    @property
    def department(self) -> SnapshotRef:
        return SnapshotRef(
            id=self.department_id,
            code=self.department_code,
            name=self.department_name,
        )


@dataclass(frozen=True)
class EntryFacts:
    """Everything one persisted entry contributes to a report."""

    entry_id: int
    session_id: str
    day_of_week: int
    start_minute: int
    end_minute: int
    duration_minutes: int
    penalty: int
    course: SnapshotRef
    component_id: int
    component_type: str
    component_label: str
    offering_code: str
    periods: tuple[str, ...]
    department: SnapshotRef
    room: SnapshotRef | None
    instructors: tuple[InstructorFact, ...]
    groups: tuple[GroupFact, ...]
    slot_ids: tuple[int, ...]

    @property
    def interval(self) -> tuple[int, int]:
        """Occupied stretch of the day, for gap arithmetic."""
        return (self.start_minute, self.end_minute)

    @property
    def participant_department_ids(self) -> tuple[int, ...]:
        """Departments of the persisted student groups, deduplicated and sorted."""
        return tuple(
            sorted({group.department_id for group in self.groups if group.department_id})
        )


@dataclass(frozen=True)
class VersionRef:
    """Identity of the version a report describes."""

    schedule_id: int
    schedule_scope: str
    semester_id: int
    semester_label: str
    version_id: int
    version_number: int
    status: str
    source: str
    created_at: Any = None
    published_at: Any = None
    published_by: Any = None


@dataclass(frozen=True)
class DepartmentScope:
    """How a department-scoped report divides the official timetable.

    ``managed_session_count`` is the department's own teaching load;
    ``participating_session_count`` is the joint teaching another department manages
    that this department's groups attend. They are never added together into the
    local load.
    """

    department: SnapshotRef
    managed_session_count: int
    participating_session_count: int
    total_visible_session_count: int
    managed_minutes: int
    participating_minutes: int

    @property
    def managed_hours(self) -> float:
        return hours_of(self.managed_minutes)

    @property
    def participating_hours(self) -> float:
        return hours_of(self.participating_minutes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "department": self.department.as_dict(),
            "managed_session_count": self.managed_session_count,
            "participating_session_count": self.participating_session_count,
            "total_visible_session_count": self.total_visible_session_count,
            "managed_minutes": self.managed_minutes,
            "managed_hours": hours_of(self.managed_minutes),
            "participating_minutes": self.participating_minutes,
            "participating_hours": hours_of(self.participating_minutes),
        }


@dataclass(frozen=True)
class SummaryMetrics:
    """Headline counts of the analysed entry set."""

    entry_count: int
    session_count: int
    scheduled_minutes: int
    unique_courses: int
    unique_teaching_components: int
    unique_departments: int
    unique_instructors: int
    unique_rooms: int
    unique_student_groups: int
    days_used: int

    @property
    def scheduled_hours(self) -> float:
        return hours_of(self.scheduled_minutes)


@dataclass(frozen=True)
class DepartmentLoad:
    """Scheduled teaching load of one managing department."""

    department: SnapshotRef
    component_count: int
    session_count: int
    scheduled_minutes: int
    unique_courses: int
    unique_instructors: int
    unique_rooms: int
    unique_student_groups: int
    joint_session_count: int

    @property
    def scheduled_hours(self) -> float:
        return hours_of(self.scheduled_minutes)


@dataclass(frozen=True)
class InstructorWorkload:
    """One instructor's scheduled load, from the version's persisted rows."""

    instructor: SnapshotRef
    session_count: int
    primary_session_count: int
    assistant_session_count: int
    scheduled_minutes: int
    days_used: int
    max_daily_scheduled_minutes: int
    department_ids: tuple[int, ...]
    department_codes: tuple[str, ...]
    total_gap_minutes: int
    max_gap_minutes: int

    @property
    def scheduled_hours(self) -> float:
        return hours_of(self.scheduled_minutes)

    @property
    def max_daily_scheduled_hours(self) -> float:
        return hours_of(self.max_daily_scheduled_minutes)

    @property
    def department_count(self) -> int:
        """How many departments this instructor teaches for inside this version."""
        return len(self.department_ids)

    @property
    def average_gap_minutes_per_active_day(self) -> float:
        return average(self.total_gap_minutes, self.days_used)


@dataclass(frozen=True)
class RoomUsage:
    """Snapshot usage of one room, plus its current-configuration denominator.

    ``available_minutes`` and ``utilization_percent`` describe *today's*
    configuration, which is why every row names its basis. When the current grid
    cannot supply a denominator both are ``None`` rather than invented.
    """

    room: SnapshotRef
    session_count: int
    occupied_minutes: int
    occupied_slot_count: int
    days_used: int
    available_minutes: int | None
    utilization_percent: float | None
    configuration_mismatch: bool
    utilization_basis: str = UTILIZATION_BASIS

    @property
    def occupied_hours(self) -> float:
        return hours_of(self.occupied_minutes)

    @property
    def available_hours(self) -> float | None:
        """Current-configuration capacity in hours, or None when there is no basis."""
        if self.available_minutes is None:
            return None
        return hours_of(self.available_minutes)


@dataclass(frozen=True)
class StudentGroupLoad:
    """One student group's scheduled load, from the version's persisted rows."""

    group: SnapshotRef
    department: SnapshotRef
    session_count: int
    scheduled_minutes: int
    days_used: int
    managing_department_count: int
    total_gap_minutes: int
    max_gap_minutes: int

    @property
    def scheduled_hours(self) -> float:
        return hours_of(self.scheduled_minutes)

    @property
    def average_gap_minutes_per_active_day(self) -> float:
        return average(self.total_gap_minutes, self.days_used)


@dataclass(frozen=True)
class QualityMetrics:
    """Interpretable timetable quality figures, with no invented score.

    The average figures divide by the population they describe: sessions for the
    preference penalty, instructors for instructor gaps, groups for group gaps. A zero
    population yields ``0.0`` rather than an undefined value.
    """

    total_preference_penalty: int
    total_instructor_gap_minutes: int
    total_student_group_gap_minutes: int
    session_count: int
    instructor_count: int
    group_count: int
    sessions_by_weekday: Mapping[str, int] = field(default_factory=dict)
    sessions_by_start_hour: Mapping[str, int] = field(default_factory=dict)
    max_sessions_for_one_instructor_day: int = 0
    max_sessions_for_one_group_day: int = 0

    @property
    def average_preference_penalty_per_session(self) -> float:
        return average(self.total_preference_penalty, self.session_count)

    @property
    def average_instructor_gap_minutes(self) -> float:
        return average(self.total_instructor_gap_minutes, self.instructor_count)

    @property
    def average_student_group_gap_minutes(self) -> float:
        return average(self.total_student_group_gap_minutes, self.group_count)


@dataclass(frozen=True)
class VersionAnalytics:
    """The whole report for one version and one visibility scope.

    ``scope`` is ``COLLEGE`` or ``DEPARTMENT``: it says how the entry set was
    narrowed, not what kind of schedule the version belongs to.
    """

    scope: str
    version: VersionRef
    summary: SummaryMetrics
    department_load: tuple[DepartmentLoad, ...] = ()
    instructor_workload: tuple[InstructorWorkload, ...] = ()
    room_utilization: tuple[RoomUsage, ...] = ()
    student_group_load: tuple[StudentGroupLoad, ...] = ()
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    department_scope: DepartmentScope | None = None

    def as_dict(self) -> dict[str, Any]:
        """Plain, JSON-serializable representation of the whole report."""
        return {
            "scope": self.scope,
            "version": {
                "schedule_id": self.version.schedule_id,
                "scope": self.version.schedule_scope,
                "semester_id": self.version.semester_id,
                "semester_label": self.version.semester_label,
                "id": self.version.version_id,
                "version_number": self.version.version_number,
                "status": self.version.status,
                "source": self.version.source,
                "created_at": self.version.created_at,
                "published_at": self.version.published_at,
                "published_by": self.version.published_by,
            },
            "summary": {
                "entry_count": self.summary.entry_count,
                "session_count": self.summary.session_count,
                "scheduled_minutes": self.summary.scheduled_minutes,
                "scheduled_hours": self.summary.scheduled_hours,
                "unique_courses": self.summary.unique_courses,
                "unique_teaching_components": self.summary.unique_teaching_components,
                "unique_departments": self.summary.unique_departments,
                "unique_instructors": self.summary.unique_instructors,
                "unique_rooms": self.summary.unique_rooms,
                "unique_student_groups": self.summary.unique_student_groups,
                "days_used": self.summary.days_used,
            },
            "department_scope": (
                None if self.department_scope is None else self.department_scope.as_dict()
            ),
            "department_load": [
                {
                    "department": row.department.as_dict(),
                    "component_count": row.component_count,
                    "session_count": row.session_count,
                    "scheduled_minutes": row.scheduled_minutes,
                    "scheduled_hours": row.scheduled_hours,
                    "unique_courses": row.unique_courses,
                    "unique_instructors": row.unique_instructors,
                    "unique_rooms": row.unique_rooms,
                    "unique_student_groups": row.unique_student_groups,
                    "joint_session_count": row.joint_session_count,
                }
                for row in self.department_load
            ],
            "instructor_workload": [
                {
                    "instructor": row.instructor.as_dict(),
                    "session_count": row.session_count,
                    "primary_session_count": row.primary_session_count,
                    "assistant_session_count": row.assistant_session_count,
                    "scheduled_minutes": row.scheduled_minutes,
                    "scheduled_hours": row.scheduled_hours,
                    "days_used": row.days_used,
                    "max_daily_scheduled_minutes": row.max_daily_scheduled_minutes,
                    "max_daily_scheduled_hours": row.max_daily_scheduled_hours,
                    "department_count": row.department_count,
                    "department_ids": list(row.department_ids),
                    "department_codes": list(row.department_codes),
                    "total_gap_minutes": row.total_gap_minutes,
                    "average_gap_minutes_per_active_day": (
                        row.average_gap_minutes_per_active_day
                    ),
                    "max_gap_minutes": row.max_gap_minutes,
                }
                for row in self.instructor_workload
            ],
            "room_utilization": [
                {
                    "room": row.room.as_dict(),
                    "session_count": row.session_count,
                    "occupied_minutes": row.occupied_minutes,
                    "occupied_hours": row.occupied_hours,
                    "occupied_slot_count": row.occupied_slot_count,
                    "days_used": row.days_used,
                    "utilization_basis": row.utilization_basis,
                    "available_minutes": row.available_minutes,
                    "available_hours": row.available_hours,
                    "utilization_percent": row.utilization_percent,
                    "configuration_mismatch": row.configuration_mismatch,
                }
                for row in self.room_utilization
            ],
            "student_group_load": [
                {
                    "group": row.group.as_dict(),
                    "department": row.department.as_dict(),
                    "session_count": row.session_count,
                    "scheduled_minutes": row.scheduled_minutes,
                    "scheduled_hours": row.scheduled_hours,
                    "days_used": row.days_used,
                    "managing_department_count": row.managing_department_count,
                    "total_gap_minutes": row.total_gap_minutes,
                    "average_gap_minutes_per_active_day": (
                        row.average_gap_minutes_per_active_day
                    ),
                    "max_gap_minutes": row.max_gap_minutes,
                }
                for row in self.student_group_load
            ],
            "quality": {
                "total_preference_penalty": self.quality.total_preference_penalty,
                "average_preference_penalty_per_session": (
                    self.quality.average_preference_penalty_per_session
                ),
                "total_instructor_gap_minutes": (
                    self.quality.total_instructor_gap_minutes
                ),
                "average_instructor_gap_minutes": (
                    self.quality.average_instructor_gap_minutes
                ),
                "total_student_group_gap_minutes": (
                    self.quality.total_student_group_gap_minutes
                ),
                "average_student_group_gap_minutes": (
                    self.quality.average_student_group_gap_minutes
                ),
                "sessions_by_weekday": dict(self.quality.sessions_by_weekday),
                "sessions_by_start_hour": dict(self.quality.sessions_by_start_hour),
                "max_sessions_for_one_instructor_day": (
                    self.quality.max_sessions_for_one_instructor_day
                ),
                "max_sessions_for_one_group_day": (
                    self.quality.max_sessions_for_one_group_day
                ),
            },
        }


__all__ = [
    "HOUR_IN_MINUTES",
    "UTILIZATION_BASIS",
    "DepartmentLoad",
    "DepartmentScope",
    "EntryFacts",
    "GroupFact",
    "InstructorFact",
    "InstructorWorkload",
    "QualityMetrics",
    "RoomUsage",
    "SnapshotRef",
    "StudentGroupLoad",
    "SummaryMetrics",
    "VersionAnalytics",
    "VersionRef",
    "average",
    "hours_of",
]
