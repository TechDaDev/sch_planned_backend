"""Instructor workload.

One instructor is one row, however many departments they teach for: a college-wide
report must not split the same person into two identities. A session counts once, no
matter how many periods it occupies, and the primary/assistant split comes from the
role the version stored, never from today's assignments.
"""

from __future__ import annotations

from collections import defaultdict

from scheduling.services.analytics.domain import (
    EntryFacts,
    InstructorWorkload,
    SnapshotRef,
)
from scheduling.services.analytics.gaps import GapTotals, gap_totals

#: Role value written into the snapshot for a primary instructor.
ROLE_PRIMARY = "PRIMARY"


def build_instructor_workload(
    facts: tuple[EntryFacts, ...], *, gaps: dict[int, GapTotals]
) -> tuple[InstructorWorkload, ...]:
    """Scheduled load per persisted instructor, ordered by name then id.

    Careers of one instructor across departments are merged: the row lists every
    managing department they teach for instead of being duplicated per department.
    """
    sessions: dict[int, list[EntryFacts]] = defaultdict(list)
    names: dict[int, str] = {}
    roles: dict[int, list[str]] = defaultdict(list)
    departments: dict[int, dict[int, str]] = defaultdict(dict)

    for fact in facts:
        for member in fact.instructors:
            sessions[member.instructor_id].append(fact)
            names.setdefault(member.instructor_id, member.full_name)
            roles[member.instructor_id].append(member.assignment_role)
            if fact.department.id is not None:
                departments[member.instructor_id][fact.department.id] = (
                    fact.department.code
                )

    rows: list[InstructorWorkload] = []
    for instructor_id, entries in sessions.items():
        daily_minutes: dict[int, int] = defaultdict(int)
        for entry in entries:
            daily_minutes[entry.day_of_week] += entry.duration_minutes
        gap = gaps.get(instructor_id, GapTotals(0, 0, 0))
        department_codes = departments.get(instructor_id, {})
        rows.append(
            InstructorWorkload(
                instructor=SnapshotRef(
                    id=instructor_id, code="", name=names.get(instructor_id, "")
                ),
                session_count=len(entries),
                primary_session_count=sum(
                    1 for role in roles.get(instructor_id, []) if role == ROLE_PRIMARY
                ),
                assistant_session_count=sum(
                    1 for role in roles.get(instructor_id, []) if role != ROLE_PRIMARY
                ),
                scheduled_minutes=sum(entry.duration_minutes for entry in entries),
                days_used=len(daily_minutes),
                max_daily_scheduled_minutes=max(daily_minutes.values(), default=0),
                department_ids=tuple(sorted(department_codes)),
                department_codes=tuple(
                    department_codes[key] for key in sorted(department_codes)
                ),
                total_gap_minutes=gap.total_minutes,
                max_gap_minutes=gap.max_gap_minutes,
            )
        )
    rows.sort(key=lambda row: (row.instructor.name, row.instructor.id or 0))
    return tuple(rows)


def instructor_gaps(facts: tuple[EntryFacts, ...]) -> dict[int, GapTotals]:
    """Per-instructor gap totals, from the persisted session spans."""
    intervals: dict[int, dict[int, list[tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for fact in facts:
        for member in fact.instructors:
            intervals[member.instructor_id][fact.day_of_week].append(fact.interval)
    return {instructor_id: gap_totals(days) for instructor_id, days in intervals.items()}


__all__ = ["ROLE_PRIMARY", "build_instructor_workload", "instructor_gaps"]
