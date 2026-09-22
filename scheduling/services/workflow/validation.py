"""Full-version validation for the workflow.

Phase 12 validates what a *change* would do to a draft. This module answers a
different question: is a **stored timetable still valid today**? A version that was
generated weeks ago can decay — an instructor loses a sharing grant, a room is
deactivated, a component's weekly hours change, the time grid is re-cut — and a
workflow must not let a stale snapshot quietly become an official timetable.

So every entry of the version is measured against today's configuration:

* academic activity — the component, offering, course and managing department are
  still active;
* session structure — the component still requires the number of sessions and the
  session length the version was built from;
* teaching assignments — the persisted instructors still match the component's
  current active assignments, are still active, still allowed to teach for the
  managing department and still available for the stored periods;
* student groups — the persisted groups still match the component's current group
  links and are still active;
* rooms — the stored room is still active, still shared with the managing
  department, still satisfies the component's current room requirement, and is
  available for the stored periods;
* the time grid — every saved period still exists, is active, belongs to this
  semester, and its current definition still matches the stored placement;
* collisions — instructor, room, student group and teaching component may not
  overlap anywhere in the version.

Every issue is blocking. Nothing here writes, and nothing here re-derives a
placement: the stored snapshot is what will be published, so the checks only decide
whether that snapshot is still true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from django.db.models import Prefetch
from resources.models import (
    InstructorAvailability,
    Room,
    RoomAvailability,
    TeachingAssignment,
    TeachingComponentCapabilityRequirement,
    TeachingComponentRoomRequirement,
)
from academics.models import TeachingComponent, TeachingComponentGroup, StudentGroup
from scheduling.models import (
    ScheduleEntry,
    ScheduleEntryInstructor,
    ScheduleEntryStudentGroup,
    ScheduleEntryTimeSlot,
)
from scheduling.services.validation.time_grid import (
    group_windows,
    hours_to_minutes,
    interval_minutes,
    time_to_minutes,
)
from scheduling.services.workflow.issues import WorkflowIssueCode


@dataclass(frozen=True)
class WorkflowIssue:
    """One blocking reason a stored version cannot progress through workflow."""

    code: str
    message: str
    severity: str = "ERROR"
    entry_id: int | None = None
    conflicting_entry_id: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def sort_key(self) -> tuple:
        """Documented deterministic order: code, entry, conflicting entry, details."""
        return (
            self.code,
            self.entry_id if self.entry_id is not None else -1,
            self.conflicting_entry_id if self.conflicting_entry_id is not None else -1,
            tuple(sorted((str(key), str(value)) for key, value in self.details.items())),
        )


@dataclass(frozen=True)
class WorkflowValidation:
    """The result of validating a stored version against current configuration."""

    version_id: int
    status: str
    entry_count: int
    issues: tuple[WorkflowIssue, ...] = ()

    @property
    def valid(self) -> bool:
        """True when nothing blocks progression."""
        return not self.issues

    @property
    def error_count(self) -> int:
        return len(self.issues)

    def as_summary(self) -> dict[str, int]:
        """The compact counts block of a validation response."""
        return {"entries": self.entry_count, "errors": self.error_count}


class WorkflowVersionValidator:
    """Validates one stored version against today's academic and resource data."""

    def __init__(self, *, version) -> None:
        self.version = version
        self.schedule = version.schedule
        self.semester = self.schedule.semester
        self._issues: list[WorkflowIssue] = []
        self._entries: list[ScheduleEntry] = []
        self._components: dict[int, TeachingComponent] = {}
        self._requirements: dict[int, Any] = {}
        self._assignments: dict[int, set[tuple[int, str]]] = {}
        self._component_groups: dict[int, set[int]] = {}
        self._rooms: dict[int, Room] = {}
        self._group_facts: dict[int, Any] = {}
        self._instructor_windows: dict[int, dict[int, tuple[tuple[int, int], ...]]] = {}
        self._room_windows: dict[int, dict[int, tuple[tuple[int, int], ...]]] = {}

    # --- entry point -------------------------------------------------------

    def validate(self, *, require_entries: bool = False) -> WorkflowValidation:
        """Run every check over the whole version.

        ``require_entries`` adds the publication completeness rule: an empty timetable
        is never published, because an accidentally empty official schedule is worse
        than a refusal.
        """
        self._entries = list(self._load_entries())
        if require_entries and not self._entries:
            self._add(
                WorkflowIssueCode.EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED,
                "The version contains no sessions, so it cannot become the official "
                "timetable.",
            )
        if not self._entries:
            return self._result()

        self._load_configuration()
        for entry in self._entries:
            self._check_entry(entry)
        self._check_structure_drift()
        self._check_conflicts()
        return self._result()

    # --- loading -----------------------------------------------------------

    def _load_entries(self):
        """Every entry of the version with its saved identity, slots and members."""
        return (
            ScheduleEntry.objects.filter(schedule_version=self.version)
            .select_related(
                "teaching_component",
                "teaching_component__offering",
                "teaching_component__offering__course",
                "teaching_component__offering__managing_department",
                "managing_department",
                "room",
                "room__room_type",
            )
            .prefetch_related(
                Prefetch(
                    "time_slots",
                    queryset=ScheduleEntryTimeSlot.objects.select_related(
                        "time_slot", "time_slot__working_day"
                    ).order_by("position"),
                ),
                Prefetch(
                    "instructors",
                    queryset=ScheduleEntryInstructor.objects.select_related(
                        "instructor"
                    ).order_by("instructor_id"),
                ),
                Prefetch(
                    "student_groups",
                    queryset=ScheduleEntryStudentGroup.objects.select_related(
                        "student_group",
                        "student_group__stage",
                        "student_group__stage__program",
                        "student_group__stage__program__department",
                    ).order_by("student_group_id"),
                ),
            )
            .order_by("pk")
        )

    def _load_configuration(self) -> None:
        """Today's facts for everything the version refers to, in bulk.

        Nothing below this point queries per entry or per resource: the component,
        requirement, assignment, group, room and availability facts are all loaded
        once for the whole version.
        """
        component_ids = {entry.teaching_component_id for entry in self._entries}
        room_ids = {entry.room_id for entry in self._entries if entry.room_id}
        instructor_ids = {
            row.instructor_id
            for entry in self._entries
            for row in entry.instructors.all()
        }
        group_ids = {
            row.student_group_id
            for entry in self._entries
            for row in entry.student_groups.all()
        }

        self._components = {
            component.pk: component
            for component in TeachingComponent.objects.filter(
                pk__in=component_ids
            ).select_related(
                "offering",
                "offering__course",
                "offering__managing_department",
            ).prefetch_related(
                # ``expected_student_count`` uses the ``attached_group_links`` prefetch
                # when it exists, so loading it here keeps the capacity checks from
                # issuing one aggregate query per entry.
                Prefetch(
                    "group_links",
                    queryset=TeachingComponentGroup.objects.select_related(
                        "student_group"
                    ).order_by("student_group_id"),
                    to_attr="attached_group_links",
                )
            )
        }
        self._requirements = {
            requirement.teaching_component_id: requirement
            for requirement in TeachingComponentRoomRequirement.objects.filter(
                teaching_component_id__in=component_ids, is_active=True
            )
            .select_related(
                "required_room_type",
                "teaching_component",
                "teaching_component__offering",
                "teaching_component__offering__managing_department",
            )
            .prefetch_related(
                Prefetch(
                    "capability_requirements",
                    queryset=TeachingComponentCapabilityRequirement.objects.select_related(
                        "capability"
                    ).order_by("capability_id"),
                ),
                Prefetch(
                    "teaching_component__group_links",
                    queryset=TeachingComponentGroup.objects.select_related(
                        "student_group"
                    ).order_by("student_group_id"),
                    to_attr="attached_group_links",
                ),
            )
        }
        self._assignments = {component_id: set() for component_id in component_ids}
        for assignment in (
            TeachingAssignment.objects.filter(
                teaching_component_id__in=component_ids, is_active=True
            )
            .select_related("instructor")
            .order_by("teaching_component_id", "instructor_id")
        ):
            self._assignments[assignment.teaching_component_id].add(
                (assignment.instructor_id, str(assignment.assignment_role))
            )
        self._component_groups = {component_id: set() for component_id in component_ids}
        for link in (
            TeachingComponentGroup.objects.filter(
                teaching_component_id__in=component_ids
            )
            .select_related("student_group")
            .order_by("teaching_component_id", "student_group_id")
        ):
            self._component_groups[link.teaching_component_id].add(link.student_group_id)

        if room_ids:
            self._rooms = {
                room.pk: room
                for room in Room.objects.filter(pk__in=room_ids)
                .select_related("room_type")
                .prefetch_related(
                    "capability_assignments__capability", "department_access"
                )
            }
        if instructor_ids:
            self._instructor_windows = _windows_by_key(
                InstructorAvailability.objects.filter(
                    semester=self.semester,
                    is_active=True,
                    instructor_id__in=instructor_ids,
                )
                .values_list("instructor_id", "day_of_week", "start_time", "end_time")
                .order_by("instructor_id", "day_of_week", "start_time")
            )
        if room_ids:
            self._room_windows = _windows_by_key(
                RoomAvailability.objects.filter(
                    semester=self.semester,
                    is_active=True,
                    room_id__in=room_ids,
                )
                .values_list("room_id", "day_of_week", "start_time", "end_time")
                .order_by("room_id", "day_of_week", "start_time")
            )

        if group_ids:
            self._group_facts = {
                group.pk: group
                for group in StudentGroup.objects.filter(pk__in=group_ids).select_related(
                    "stage", "stage__program", "stage__program__department"
                )
            }
        else:
            self._group_facts = {}

    # --- per-entry checks --------------------------------------------------

    def _check_entry(self, entry: ScheduleEntry) -> None:
        """Everything one entry has to satisfy today."""
        component = self._components.get(entry.teaching_component_id)
        self._check_academic_activity(entry, component)
        self._check_slots(entry)
        self._check_instructors(entry)
        self._check_room(entry, component)
        self._check_teaching_assignment(entry)
        self._check_student_groups(entry)

    def _check_academic_activity(self, entry: ScheduleEntry, component) -> None:
        """The component and its academic chain must still be active."""
        if component is None:
            self._add(
                WorkflowIssueCode.INACTIVE_ACADEMIC_DEPENDENCY,
                "The teaching component of this session no longer exists.",
                entry_id=entry.pk,
                details={"reason": "component_missing"},
            )
            return
        offering = component.offering
        course = offering.course
        department = offering.managing_department
        inactive = [
            name
            for name, value in (
                ("teaching_component", component.is_active),
                ("course_offering", offering.is_active),
                ("course", course.is_active),
                ("managing_department", department.is_active),
            )
            if not value
        ]
        if inactive:
            self._add(
                WorkflowIssueCode.INACTIVE_ACADEMIC_DEPENDENCY,
                "The academic chain of this session is no longer fully active.",
                entry_id=entry.pk,
                details={"inactive": inactive},
            )

    def _check_slots(self, entry: ScheduleEntry) -> None:
        """Saved periods must still exist, be active, and describe the same slots."""
        for row in entry.time_slots.all():
            slot = row.time_slot
            working_day = slot.working_day
            if not slot.is_active or not working_day.is_active:
                self._add(
                    WorkflowIssueCode.TIME_SLOT_INACTIVE,
                    "A saved teaching period is no longer active.",
                    entry_id=entry.pk,
                    details={"time_slot_id": slot.pk},
                )
                continue
            if working_day.semester_id != self.semester.pk:
                self._add(
                    WorkflowIssueCode.TIME_SLOT_WRONG_SEMESTER,
                    "A saved teaching period now belongs to another semester.",
                    entry_id=entry.pk,
                    details={"time_slot_id": slot.pk},
                )
                continue
            if (
                int(working_day.day_of_week) != entry.day_of_week
                or slot.start_time != row.start_time_snapshot
                or slot.end_time != row.end_time_snapshot
                or slot.sequence != row.sequence_snapshot
            ):
                self._add(
                    WorkflowIssueCode.TIME_SLOT_CONFIGURATION_CHANGED,
                    "A saved teaching period was redefined after this version was "
                    "created, so its stored placement no longer matches the calendar.",
                    entry_id=entry.pk,
                    details={
                        "time_slot_id": slot.pk,
                        "saved": {
                            "day_of_week": entry.day_of_week,
                            "start_time": str(row.start_time_snapshot),
                            "end_time": str(row.end_time_snapshot),
                            "sequence": row.sequence_snapshot,
                        },
                        "current": {
                            "day_of_week": int(working_day.day_of_week),
                            "start_time": str(slot.start_time),
                            "end_time": str(slot.end_time),
                            "sequence": slot.sequence,
                        },
                    },
                )

    def _check_instructors(self, entry: ScheduleEntry) -> None:
        """Saved instructors must still be active, eligible and available."""
        for row in entry.instructors.all():
            instructor = row.instructor
            if not instructor.is_active:
                self._add(
                    WorkflowIssueCode.INSTRUCTOR_INACTIVE,
                    "An instructor of this session is no longer active.",
                    entry_id=entry.pk,
                    details={"instructor_id": row.instructor_id},
                )
                continue
            if not instructor.can_teach_in_department(entry.managing_department):
                self._add(
                    WorkflowIssueCode.INSTRUCTOR_NOT_ELIGIBLE,
                    "An instructor of this session may no longer teach for the "
                    "managing department.",
                    entry_id=entry.pk,
                    details={"instructor_id": row.instructor_id},
                )
                continue
            uncovered = self._uncovered_slots(
                self._instructor_windows.get(row.instructor_id, {}), entry
            )
            if uncovered:
                self._add(
                    WorkflowIssueCode.INSTRUCTOR_UNAVAILABLE,
                    "An instructor of this session is not available for the saved "
                    "periods.",
                    entry_id=entry.pk,
                    details={
                        "instructor_id": row.instructor_id,
                        "slot_ids": uncovered,
                    },
                )

    def _check_room(self, entry: ScheduleEntry, component) -> None:
        """The saved room must still be usable, suitable and available."""
        if entry.room_id is None:
            return
        room = self._rooms.get(entry.room_id)
        if room is None:
            self._add(
                WorkflowIssueCode.ROOM_INACTIVE,
                "The saved room no longer exists.",
                entry_id=entry.pk,
                details={"room_id": entry.room_id},
            )
            return
        if not room.is_active or not room.room_type.is_active:
            self._add(
                WorkflowIssueCode.ROOM_INACTIVE,
                "The saved room or its room type is not active.",
                entry_id=entry.pk,
                details={"room_id": room.pk},
            )
            return
        if not room.can_be_used_by_department(entry.managing_department):
            self._add(
                WorkflowIssueCode.ROOM_NOT_ELIGIBLE,
                "The saved room is no longer shared with the session's managing "
                "department.",
                entry_id=entry.pk,
                details={"room_id": room.pk},
            )
            return

        requirement = self._requirements.get(entry.teaching_component_id)
        if requirement is None:
            self._add(
                WorkflowIssueCode.ROOM_REQUIREMENT_UNSATISFIED,
                "The teaching component has no active room requirement, so the saved "
                "room can no longer be confirmed as suitable.",
                entry_id=entry.pk,
                details={"reason": "requirement_missing_or_inactive"},
            )
            return
        reasons = room.evaluate_suitability(requirement)
        if reasons:
            self._add(
                WorkflowIssueCode.ROOM_REQUIREMENT_UNSATISFIED,
                "The saved room no longer satisfies the component's room requirement.",
                entry_id=entry.pk,
                details={"room_id": room.pk, "reasons": reasons},
            )
            return

        uncovered = self._uncovered_slots(
            self._room_windows.get(room.pk, {}), entry
        )
        if uncovered:
            self._add(
                WorkflowIssueCode.ROOM_UNAVAILABLE,
                "The saved room is not available for the saved periods.",
                entry_id=entry.pk,
                details={"room_id": room.pk, "slot_ids": uncovered},
            )

    def _check_teaching_assignment(self, entry: ScheduleEntry) -> None:
        """The saved instructors must still be the component's current assignment."""
        current = self._assignments.get(entry.teaching_component_id, set())
        persisted = {
            (row.instructor_id, str(row.assignment_role_snapshot or ""))
            for row in entry.instructors.all()
        }
        if current != persisted:
            self._add(
                WorkflowIssueCode.TEACHING_ASSIGNMENT_CHANGED,
                "The component's current teaching assignment differs from the one "
                "stored in this version.",
                entry_id=entry.pk,
                details={
                    "persisted": sorted(f"{i}:{role}" for i, role in persisted),
                    "current": sorted(f"{i}:{role}" for i, role in current),
                },
            )

    def _check_student_groups(self, entry: ScheduleEntry) -> None:
        """Saved groups must still be the component's groups, and still be active."""
        current = self._component_groups.get(entry.teaching_component_id, set())
        persisted = {row.student_group_id for row in entry.student_groups.all()}
        if current != persisted:
            self._add(
                WorkflowIssueCode.STUDENT_GROUP_CONFIGURATION_CHANGED,
                "The component's current student groups differ from the ones stored "
                "in this version.",
                entry_id=entry.pk,
                details={
                    "persisted": sorted(persisted),
                    "current": sorted(current),
                },
            )
        for row in entry.student_groups.all():
            group = self._group_facts.get(row.student_group_id)
            if group is None:
                self._add(
                    WorkflowIssueCode.STUDENT_GROUP_INACTIVE,
                    "A stored student group no longer exists.",
                    entry_id=entry.pk,
                    details={"student_group_id": row.student_group_id},
                )
                continue
            inactive = [name for name, value in _group_activity(group) if not value]
            if inactive:
                self._add(
                    WorkflowIssueCode.STUDENT_GROUP_INACTIVE,
                    "A stored student group or its academic chain is no longer active.",
                    entry_id=entry.pk,
                    details={
                        "student_group_id": row.student_group_id,
                        "inactive": inactive,
                    },
                )

    # --- version-wide checks ----------------------------------------------

    def _check_structure_drift(self) -> None:
        """Compare each component's current demand with what the version stores."""
        per_component: dict[int, list[ScheduleEntry]] = {}
        for entry in self._entries:
            per_component.setdefault(entry.teaching_component_id, []).append(entry)

        for component_id, entries in sorted(per_component.items()):
            component = self._components.get(component_id)
            if component is None:
                continue
            required_sessions = component.sessions_per_week or 0
            saved_sessions = len({entry.session_id for entry in entries})
            if saved_sessions != required_sessions:
                self._add(
                    WorkflowIssueCode.SESSION_COUNT_MISMATCH,
                    "The component's weekly session count changed after this version "
                    "was created.",
                    details={
                        "teaching_component_id": component_id,
                        "saved_sessions": saved_sessions,
                        "current_sessions": required_sessions,
                    },
                )
            required_minutes = hours_to_minutes(component.session_duration_hours)
            saved_minutes = {
                _entry_minutes(entry) for entry in entries
            }
            if required_minutes not in saved_minutes:
                self._add(
                    WorkflowIssueCode.SESSION_DURATION_MISMATCH,
                    "The component's session duration changed after this version was "
                    "created.",
                    details={
                        "teaching_component_id": component_id,
                        "saved_minutes": sorted(saved_minutes),
                        "current_minutes": required_minutes,
                    },
                )

    def _check_conflicts(self) -> None:
        """Nobody may occupy one saved period twice inside the version.

        The stored version should already be conflict free, so a hit here means the
        snapshot is broken rather than stale; it still blocks workflow, because
        publishing a self-conflicting official timetable is worse than refusing.
        """
        occupancy: dict[tuple[str, int, int], set[int]] = {}

        def occupy(kind: str, resource_id: int, slot_ids: Iterable[int], entry_id: int):
            for slot_id in slot_ids:
                occupancy.setdefault((kind, resource_id, slot_id), set()).add(entry_id)

        for entry in self._entries:
            slot_ids = [row.time_slot_id for row in entry.time_slots.all()]
            for row in entry.instructors.all():
                occupy("instructor", row.instructor_id, slot_ids, entry.pk)
            if entry.room_id is not None:
                occupy("room", entry.room_id, slot_ids, entry.pk)
            for row in entry.student_groups.all():
                occupy("group", row.student_group_id, slot_ids, entry.pk)
            occupy("component", entry.teaching_component_id, slot_ids, entry.pk)

        codes = {
            "instructor": WorkflowIssueCode.INSTRUCTOR_CONFLICT,
            "room": WorkflowIssueCode.ROOM_CONFLICT,
            "group": WorkflowIssueCode.STUDENT_GROUP_CONFLICT,
            "component": WorkflowIssueCode.COMPONENT_CONFLICT,
        }
        messages = {
            "instructor": "An instructor teaches two sessions at the same time.",
            "room": "A room hosts two sessions at the same time.",
            "group": "A student group attends two sessions at the same time.",
            "component": "Two sessions of one teaching component overlap.",
        }
        pairs: dict[tuple[str, int, int, int], set[int]] = {}
        for (kind, resource_id, slot_id), entry_ids in occupancy.items():
            if len(entry_ids) < 2:
                continue
            ordered = sorted(entry_ids)
            for index, first in enumerate(ordered):
                for second in ordered[index + 1 :]:
                    pairs.setdefault((kind, resource_id, first, second), set()).add(
                        slot_id
                    )

        for kind, resource_id, first, second in sorted(pairs):
            self._add(
                codes[kind],
                messages[kind],
                entry_id=first,
                conflicting_entry_id=second,
                details={
                    "resource": kind,
                    "resource_id": resource_id,
                    "slot_ids": sorted(pairs[(kind, resource_id, first, second)]),
                },
            )

    # --- helpers -----------------------------------------------------------

    def _uncovered_slots(
        self, windows_by_weekday: Mapping[int, tuple[tuple[int, int], ...]], entry
    ) -> list[int]:
        """Saved periods not fully covered by one availability window that weekday."""
        windows = windows_by_weekday.get(entry.day_of_week, ())
        uncovered: list[int] = []
        for row in entry.time_slots.all():
            start = time_to_minutes(row.start_time_snapshot)
            end = time_to_minutes(row.end_time_snapshot)
            if start is None or end is None:
                continue
            if not any(start >= window_start and end <= window_end for window_start, window_end in windows):
                uncovered.append(row.time_slot_id)
        return uncovered

    def _add(
        self,
        code: str,
        message: str,
        *,
        entry_id: int | None = None,
        conflicting_entry_id: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self._issues.append(
            WorkflowIssue(
                code=code,
                message=message,
                entry_id=entry_id,
                conflicting_entry_id=conflicting_entry_id,
                details=dict(details or {}),
            )
        )

    def _result(self) -> WorkflowValidation:
        """Deterministic, deduplicated result."""
        kept: dict[tuple, WorkflowIssue] = {}
        for issue in self._issues:
            key = (issue.code, issue.entry_id, issue.conflicting_entry_id)
            previous = kept.get(key)
            if previous is None:
                kept[key] = issue
                continue
            if isinstance(issue.details.get("slot_ids"), list):
                merged = set(previous.details.get("slot_ids", [])) | set(
                    issue.details["slot_ids"]
                )
                kept[key] = WorkflowIssue(
                    code=issue.code,
                    message=issue.message,
                    entry_id=issue.entry_id,
                    conflicting_entry_id=issue.conflicting_entry_id,
                    details={**issue.details, "slot_ids": sorted(merged)},
                )
        issues = tuple(sorted(kept.values(), key=lambda issue: issue.sort_key))
        return WorkflowValidation(
            version_id=self.version.pk,
            status=self.version.status,
            entry_count=len(self._entries),
            issues=issues,
        )


def _windows_by_key(rows) -> dict[int, dict[int, tuple[tuple[int, int], ...]]]:
    """Group ``(key, weekday, start, end)`` rows into per-key weekday windows.

    The grouping rule is the one the generation adapter uses: absence of a window is
    never unrestricted availability, and a period counts only when it sits fully
    inside a single window.
    """
    grouped: dict[int, list[tuple[int, Any, Any]]] = {}
    for key, weekday, start, end in rows:
        grouped.setdefault(key, []).append((int(weekday), start, end))
    return {
        key: group_windows(values) for key, values in grouped.items()
    }


def _entry_minutes(entry: ScheduleEntry) -> int:
    """Total minutes the entry occupies, from its stored period snapshots."""
    total = 0
    for row in entry.time_slots.all():
        interval = interval_minutes(row.start_time_snapshot, row.end_time_snapshot)
        if interval is not None:
            total += interval[1] - interval[0]
    return total


def _group_activity(group) -> list[tuple[str, bool]]:
    """Activity flags of a student group and its academic chain."""
    stage = getattr(group, "stage", None)
    program = getattr(stage, "program", None)
    department = getattr(program, "department", None)
    return [
        ("student_group", bool(group.is_active)),
        ("study_stage", bool(getattr(stage, "is_active", False))),
        ("study_program", bool(getattr(program, "is_active", False))),
        ("department", bool(getattr(department, "is_active", False))),
    ]


__all__ = ["WorkflowIssue", "WorkflowValidation", "WorkflowVersionValidator"]
