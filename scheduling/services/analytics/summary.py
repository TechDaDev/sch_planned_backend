"""Department and student-group aggregations.

Both are views of the same entry facts: department load groups sessions by the
department that *manages* them, and group load groups the same sessions by the
persisted student groups that attend them. A joint session therefore counts once for
its managing department and once for every attending group, which is exactly how the
workload is distributed in reality.
"""

from __future__ import annotations

from collections import defaultdict

from scheduling.services.analytics.domain import (
    DepartmentLoad,
    DepartmentScope,
    EntryFacts,
    SnapshotRef,
    StudentGroupLoad,
    SummaryMetrics,
)
from scheduling.services.analytics.gaps import GapTotals, gap_totals


def build_summary(facts: tuple[EntryFacts, ...]) -> SummaryMetrics:
    """Headline counts of one entry set."""
    return SummaryMetrics(
        entry_count=len(facts),
        session_count=len(facts),
        scheduled_minutes=sum(fact.duration_minutes for fact in facts),
        unique_courses=len({fact.course.id for fact in facts}),
        unique_teaching_components=len({fact.component_id for fact in facts}),
        unique_departments=len({fact.department.id for fact in facts}),
        unique_instructors=len(
            {member.instructor_id for fact in facts for member in fact.instructors}
        ),
        unique_rooms=len({fact.room.id for fact in facts if fact.room is not None}),
        unique_student_groups=len(
            {group.group_id for fact in facts for group in fact.groups}
        ),
        days_used=len({fact.day_of_week for fact in facts}),
    )


def build_department_load(facts: tuple[EntryFacts, ...]) -> tuple[DepartmentLoad, ...]:
    """Scheduled load per managing department, ordered by department code then id.

    A joint session — one whose persisted groups belong to more than one department —
    is counted once, under the department that manages the component.
    """
    grouped: dict[int | None, list[EntryFacts]] = defaultdict(list)
    for fact in facts:
        grouped[fact.department.id].append(fact)

    rows: list[DepartmentLoad] = []
    for department_id, entries in grouped.items():
        department = entries[0].department
        rows.append(
            DepartmentLoad(
                department=department,
                component_count=len({entry.component_id for entry in entries}),
                session_count=len(entries),
                scheduled_minutes=sum(entry.duration_minutes for entry in entries),
                unique_courses=len({entry.course.id for entry in entries}),
                unique_instructors=len(
                    {member.instructor_id for entry in entries for member in entry.instructors}
                ),
                unique_rooms=len(
                    {entry.room.id for entry in entries if entry.room is not None}
                ),
                unique_student_groups=len(
                    {group.group_id for entry in entries for group in entry.groups}
                ),
                joint_session_count=sum(
                    1
                    for entry in entries
                    if len(entry.participant_department_ids) > 1
                ),
            )
        )
    rows.sort(key=lambda row: (row.department.code, row.department.id or 0))
    return tuple(rows)


def build_department_scope(
    facts: tuple[EntryFacts, ...], *, department: SnapshotRef
) -> DepartmentScope:
    """Split a department-scoped report into managed and participating sessions.

    Only the visible entry set is analysed, so a department's official report never
    counts another department's teaching as its own load.
    """
    department_id = department.id
    managed = [
        fact
        for fact in facts
        if department_id is not None and fact.department.id == department_id
    ]
    participating = [
        fact
        for fact in facts
        if department_id is not None and fact.department.id != department_id
    ]
    return DepartmentScope(
        department=department,
        managed_session_count=len(managed),
        participating_session_count=len(participating),
        total_visible_session_count=len(facts),
        managed_minutes=sum(fact.duration_minutes for fact in managed),
        participating_minutes=sum(fact.duration_minutes for fact in participating),
    )


def build_student_group_load(
    facts: tuple[EntryFacts, ...], *, gaps: dict[int, GapTotals]
) -> tuple[StudentGroupLoad, ...]:
    """Scheduled load per persisted student group.

    Ordering is by the group's own department code, then group code, then group id, so
    a report groups departments together and repeats identically on unchanged data.
    Participation and department come from the version's rows, never from today's
    component links.
    """
    grouped: dict[int, list[EntryFacts]] = defaultdict(list)
    groups: dict[int, SnapshotRef] = {}
    departments: dict[int, SnapshotRef] = {}
    for fact in facts:
        for group in fact.groups:
            groups.setdefault(group.group_id, SnapshotRef(group.group_id, group.code, group.name))
            departments.setdefault(group.group_id, group.department)
            grouped[group.group_id].append(fact)

    rows: list[StudentGroupLoad] = []
    for group_id, entries in grouped.items():
        group = groups[group_id]
        department = departments[group_id]
        gap = gaps.get(group_id, GapTotals(0, 0, 0))
        rows.append(
            StudentGroupLoad(
                group=group,
                department=department,
                session_count=len(entries),
                scheduled_minutes=sum(entry.duration_minutes for entry in entries),
                days_used=len({entry.day_of_week for entry in entries}),
                managing_department_count=len(
                    {entry.department.id for entry in entries}
                ),
                total_gap_minutes=gap.total_minutes,
                max_gap_minutes=gap.max_gap_minutes,
            )
        )
    rows.sort(
        key=lambda row: (
            row.department.code,
            row.group.code,
            row.group.id or 0,
        )
    )
    return tuple(rows)


def group_gaps(facts: tuple[EntryFacts, ...]) -> dict[int, GapTotals]:
    """Per-group gap totals, from the persisted session spans."""
    intervals: dict[int, dict[int, list[tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for fact in facts:
        for group in fact.groups:
            intervals[group.group_id][fact.day_of_week].append(fact.interval)
    return {
        group_id: gap_totals(days) for group_id, days in intervals.items()
    }


__all__ = [
    "build_department_load",
    "build_department_scope",
    "build_student_group_load",
    "build_summary",
    "group_gaps",
]
