"""Turning a generated preview into the rows a persisted version needs.

The generation result is already flat, JSON-safe data: a :class:`PreviewPlacement`
knows its session, its component summary, the periods it occupies, its room, its
instructors and its student groups. This module reshapes that into the frozen
snapshots the persistence service writes, and does nothing else — no database
access, no transaction, no Django model instances.

Keeping the reshaping pure means the rules that decide *what a version keeps* are
readable in one place: every display value a later rename would change is copied
here, so rendering an old version never depends on today's course, room, department
or instructor names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from scheduling.services.generation.domain import (
    CourseInfo,
    DepartmentInfo,
    GroupInfo,
    OfferingInfo,
    PreviewPlacement,
    RoomInfo,
)
from scheduling.services.generation.preview import session_ordinal


def parse_clock(value: str) -> time:
    """Parse a preview ``"HH:MM"`` string into a :class:`datetime.time`.

    Preview rows carry formatted clock strings, not time objects, so persistence
    converts once here instead of every writer reimplementing the rule.
    """
    return time.fromisoformat(value)


@dataclass(frozen=True)
class SlotSnapshot:
    """One occupied period of an entry, with the values it had when generated."""

    time_slot_id: int
    position: int
    sequence: int
    label: str
    start_time: time
    end_time: time


@dataclass(frozen=True)
class InstructorSnapshot:
    """One instructor of an entry, with the role and name it had when generated."""

    instructor_id: int
    full_name: str
    assignment_role: str


@dataclass(frozen=True)
class GroupSnapshot:
    """One student group of an entry, with its own department snapshot."""

    student_group_id: int
    code: str
    name: str
    department_id: int | None
    department_code: str
    department_name: str


@dataclass(frozen=True)
class EntrySnapshot:
    """Everything needed to write one ``ScheduleEntry`` and its child rows.

    ``managing_department`` is kept as a value object rather than an id so the
    persistence service can check entry scope consistency without a query.
    """

    session_id: str
    candidate_id: str
    session_ordinal: int
    teaching_component_id: int
    managing_department: DepartmentInfo
    day_of_week: int
    room: RoomInfo | None
    start_time: time
    end_time: time
    penalty: int
    course: CourseInfo
    offering: OfferingInfo
    component_type: str
    component_label: str
    time_slots: tuple[SlotSnapshot, ...]
    instructors: tuple[InstructorSnapshot, ...]
    student_groups: tuple[GroupSnapshot, ...]

    @property
    def time_slot_ids(self) -> tuple[int, ...]:
        """Ids of the occupied periods, in the order the entry occupies them."""
        return tuple(slot.time_slot_id for slot in self.time_slots)

    @property
    def instructor_ids(self) -> tuple[int, ...]:
        """Ids of the instructors included in this entry."""
        return tuple(snapshot.instructor_id for snapshot in self.instructors)

    @property
    def student_group_ids(self) -> tuple[int, ...]:
        """Ids of the student groups included in this entry."""
        return tuple(snapshot.student_group_id for snapshot in self.student_groups)


def build_entry_snapshots(
    placements,
    *,
    group_departments: dict[int, tuple[int | None, str, str]] | None = None,
) -> tuple[EntrySnapshot, ...]:
    """Snapshot every placement, in the order the preview returned them.

    ``group_departments`` maps a student group id to
    ``(department_id, department_code, department_name)``. The generation preview
    deliberately carries only a group's own display values, so the caller supplies
    the department facts it loaded in one query; a group without an entry keeps null
    department snapshots rather than failing the whole version.
    """
    departments = group_departments or {}
    return tuple(
        _entry_snapshot(placement, departments) for placement in placements
    )


def _entry_snapshot(
    placement: PreviewPlacement,
    group_departments: dict[int, tuple[int | None, str, str]],
) -> EntrySnapshot:
    """Reshape one preview row into its persisted snapshot."""
    department = placement.managing_department
    if department is None:
        raise ValueError(
            "A placement cannot be persisted without its managing department."
        )

    slots = tuple(
        SlotSnapshot(
            time_slot_id=slot.id,
            position=position,
            sequence=slot.sequence,
            label=slot.label,
            start_time=parse_clock(slot.start_time),
            end_time=parse_clock(slot.end_time),
        )
        for position, slot in enumerate(placement.slots, start=1)
    )
    instructors = tuple(
        InstructorSnapshot(
            instructor_id=item.instructor.id,
            full_name=item.instructor.full_name,
            assignment_role=item.assignment_role or "",
        )
        for item in placement.instructors
    )
    groups = tuple(
        _group_snapshot(group, group_departments) for group in placement.student_groups
    )

    return EntrySnapshot(
        session_id=placement.session_id,
        candidate_id=_candidate_id(placement),
        session_ordinal=session_ordinal(placement.session_id),
        teaching_component_id=placement.teaching_component.id,
        managing_department=department,
        day_of_week=placement.day_of_week,
        room=placement.room,
        start_time=parse_clock(placement.start_time),
        end_time=parse_clock(placement.end_time),
        penalty=placement.penalty,
        course=placement.course,
        offering=placement.offering,
        component_type=placement.teaching_component.component_type,
        component_label=placement.teaching_component.label,
        time_slots=slots,
        instructors=instructors,
        student_groups=groups,
    )


def _group_snapshot(
    group: GroupInfo,
    group_departments: dict[int, tuple[int | None, str, str]],
) -> GroupSnapshot:
    """Snapshot one student group, including the department it belongs to."""
    department_id, code, name = group_departments.get(group.id, (None, "", ""))
    return GroupSnapshot(
        student_group_id=group.id,
        code=group.code,
        name=group.name,
        department_id=department_id,
        department_code=code,
        department_name=name,
    )


def _candidate_id(placement: PreviewPlacement) -> str:
    """The deterministic candidate id of a preview row.

    The preview keeps the solver's own record alongside the rendered row, so the
    candidate id is read from there instead of being rebuilt.
    """
    if placement.raw is None:
        raise ValueError("A placement cannot be persisted without its candidate id.")
    return placement.raw.candidate_id


__all__ = [
    "EntrySnapshot",
    "GroupSnapshot",
    "InstructorSnapshot",
    "SlotSnapshot",
    "build_entry_snapshots",
    "parse_clock",
]
