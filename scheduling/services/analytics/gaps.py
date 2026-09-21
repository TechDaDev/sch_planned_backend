"""Gap arithmetic for timetables.

A gap is free time *between* teaching, seen from one resource's point of view. Time
before that resource's first session and after its last one is not a gap: a
timetable that teaches 08:00-09:30 and nothing else has no gap, even though the rest
of the day is empty.

Intervals come from the persisted per-entry spans, are merged defensively (touching
and overlapping sessions count as one continuous stretch), and are then measured
between the merged stretches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from scheduling.services.validation.time_grid import merge_intervals


@dataclass(frozen=True)
class GapTotals:
    """Gap summary of one resource across the week."""

    total_minutes: int
    max_gap_minutes: int
    active_days: int


def gap_totals(intervals_by_day: Mapping[int, Iterable[tuple[int, int]]]) -> GapTotals:
    """Total, largest and per-day gap figures for one resource.

    ``intervals_by_day`` maps a weekday to the occupied ``(start, end)`` minute spans
    of that day. Only the stretches between merged sessions contribute.
    """
    total = 0
    largest = 0
    active_days = 0
    for day in sorted(intervals_by_day):
        merged = merge_intervals(intervals_by_day[day])
        if not merged:
            continue
        active_days += 1
        for (_, previous_end), (start, _) in zip(merged, merged[1:]):
            gap = start - previous_end
            if gap <= 0:
                continue
            total += gap
            largest = max(largest, gap)
    return GapTotals(total_minutes=total, max_gap_minutes=largest, active_days=active_days)


__all__ = ["GapTotals", "gap_totals"]
