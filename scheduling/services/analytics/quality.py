"""Timetable quality metrics.

These are the interpretable figures a timetable committee actually argues about: how
much preference penalty the placements cost, how much dead time instructors and
students carry between sessions, how the week is distributed, and how concentrated
one day can become for one person or one group.

No composite score is produced. A single opaque "82/100" number would hide which of
these figures is bad, so Phase 14 reports the raw quantities and lets the reader
judge them.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from academics.models import Weekday
from scheduling.services.analytics.domain import EntryFacts, QualityMetrics
from scheduling.services.analytics.gaps import GapTotals


def build_quality(
    facts: tuple[EntryFacts, ...],
    *,
    instructor_gaps: dict[int, GapTotals],
    group_gaps: dict[int, GapTotals],
) -> QualityMetrics:
    """Quality figures of one entry set.

    Preference penalty comes from the stored ``ScheduleEntry.penalty``: it is the
    score the placement was accepted with, and recomputing it from today's preference
    windows would describe a different timetable than the one stored.
    """
    weekday_counts = Counter(fact.day_of_week for fact in facts)
    start_hour_counts: Counter[str] = Counter()
    for fact in facts:
        hour, minute = divmod(fact.start_minute, 60)
        start_hour_counts[f"{hour:02d}:{minute:02d}"] += 1

    return QualityMetrics(
        total_preference_penalty=sum(fact.penalty for fact in facts),
        total_instructor_gap_minutes=sum(
            gap.total_minutes for gap in instructor_gaps.values()
        ),
        total_student_group_gap_minutes=sum(
            gap.total_minutes for gap in group_gaps.values()
        ),
        session_count=len(facts),
        instructor_count=len(instructor_gaps),
        group_count=len(group_gaps),
        # Every weekday is reported, including the unused ones, so two reports can be
        # compared position by position.
        sessions_by_weekday={
            weekday.name: weekday_counts.get(int(weekday), 0) for weekday in Weekday
        },
        sessions_by_start_hour={
            start: start_hour_counts[start] for start in sorted(start_hour_counts)
        },
        max_sessions_for_one_instructor_day=_max_sessions_per_day(
            facts, key="instructor"
        ),
        max_sessions_for_one_group_day=_max_sessions_per_day(facts, key="group"),
    )


def _max_sessions_per_day(facts: tuple[EntryFacts, ...], *, key: str) -> int:
    """Largest number of sessions one resource carries on a single weekday.

    Concurrent sessions are not added together: the figure is the count of sessions
    that land on that day for that resource, which is what makes a day feel overspent.
    """
    per_resource: dict[tuple[int, int], set[int]] = defaultdict(set)
    for fact in facts:
        if key == "instructor":
            resource_ids = [member.instructor_id for member in fact.instructors]
        else:
            resource_ids = [group.group_id for group in fact.groups]
        for resource_id in resource_ids:
            per_resource[(resource_id, fact.day_of_week)].add(fact.entry_id)
    if not per_resource:
        return 0
    return max(len(entry_ids) for entry_ids in per_resource.values())


__all__ = ["build_quality"]
