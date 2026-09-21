"""Time-grid mathematics for the pre-scheduling validator.

Everything here is pure apart from :meth:`TimeGrid.load`, which reads the active
grid of one semester. Durations are handled in whole minutes derived from
``Decimal`` hours, never through binary floating point, so ``1.50`` hours is
exactly ``90`` minutes.

The central idea is the *contiguous block*: consecutive teaching periods that are
adjacent in time can host one longer session. ``08:00-08:45`` followed by
``08:45-09:30`` supports a 90-minute session, while ``08:00-08:45`` followed by
``09:00-09:45`` (a gap) does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Mapping

from django.db.models import Prefetch

from scheduling.models import TimeSlot, WorkingDay

MINUTES_PER_HOUR = Decimal(60)

#: ``(start_minute, end_minute)`` interval inside one weekday.
Interval = tuple[int, int]

#: Instructor/room availability windows per weekday, in minutes.
WindowMap = Mapping[int, tuple[Interval, ...]]


def hours_to_minutes(hours: Decimal | int | float | str | None) -> int:
    """Convert positive decimal hours into whole minutes.

    ``1.00 -> 60``, ``1.50 -> 90``, ``2.00 -> 120``. Uses ``Decimal`` throughout
    so no binary floating-point error can creep in, and half-up rounds the only
    way a two-decimal hour value can land between two minutes.
    """
    if hours is None:
        return 0
    try:
        value = Decimal(str(hours))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    if value <= 0:
        return 0
    return int((value * MINUTES_PER_HOUR).to_integral_value(rounding=ROUND_HALF_UP))


def time_to_minutes(value: time | None) -> int | None:
    """Minutes since midnight for a ``time``, or ``None`` when unset."""
    if value is None:
        return None
    return value.hour * 60 + value.minute


def interval_minutes(start: time | None, end: time | None) -> Interval | None:
    """Normalise a time window into minutes, dropping unusable windows."""
    start_minute = time_to_minutes(start)
    end_minute = time_to_minutes(end)
    if start_minute is None or end_minute is None or end_minute <= start_minute:
        return None
    return (start_minute, end_minute)


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """Merge overlapping or exactly adjacent intervals.

    Intervals that merely *touch* (``08:45-09:30`` after ``08:00-08:45``) are
    merged because the covered stretch of time is continuous; intervals with a
    real gap stay separate. The result is sorted by start.
    """
    ordered = sorted(
        (start, end) for start, end in intervals if end > start
    )
    merged: list[Interval] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def max_contiguous_minutes(intervals: Iterable[Interval]) -> int:
    """Longest continuous stretch of time covered by ``intervals``.

    Because merged intervals contain no gaps, any session whose duration is at
    most this value can be placed inside one of them.
    """
    merged = merge_intervals(intervals)
    if not merged:
        return 0
    return max(end - start for start, end in merged)


def total_minutes(intervals: Iterable[Interval]) -> int:
    """Total covered minutes, counting overlapping intervals once."""
    return sum(end - start for start, end in merge_intervals(intervals))


def group_windows(rows: Iterable[tuple[int, time, time]]) -> dict[int, tuple[Interval, ...]]:
    """Group ``(weekday, start, end)`` rows into availability windows per day."""
    grouped: dict[int, list[Interval]] = {}
    for weekday, start, end in rows:
        interval = interval_minutes(start, end)
        if interval is None:
            continue
        grouped.setdefault(weekday, []).append(interval)
    return {weekday: tuple(values) for weekday, values in grouped.items()}


@dataclass(frozen=True)
class UsableGrid:
    """How much of the time grid a resource may actually use."""

    total_minutes: int
    days: int
    max_contiguous_minutes: int


@dataclass(frozen=True)
class TimeGrid:
    """The active grid of one semester: working days and their active slots.

    Inactive working days and inactive slots are not part of the grid, because
    nothing may be scheduled into them. The grid is loaded once per validation
    run and then queried in memory.
    """

    working_days: tuple[WorkingDay, ...]
    slots_by_weekday: Mapping[int, tuple[Interval, ...]]
    days_without_slots: tuple[WorkingDay, ...]

    @classmethod
    def load(cls, semester) -> "TimeGrid":
        """Read the active grid of ``semester`` in two queries at most."""
        working_days = list(
            WorkingDay.objects.filter(semester=semester, is_active=True)
            .prefetch_related(
                Prefetch(
                    "time_slots",
                    queryset=TimeSlot.objects.filter(is_active=True).order_by(
                        "start_time", "end_time"
                    ),
                )
            )
            .order_by("day_of_week")
        )

        slots_by_weekday: dict[int, tuple[Interval, ...]] = {}
        days_without_slots: list[WorkingDay] = []
        for working_day in working_days:
            intervals: list[Interval] = []
            for slot in working_day.time_slots.all():
                interval = interval_minutes(slot.start_time, slot.end_time)
                if interval is not None:
                    intervals.append(interval)
            slots_by_weekday[working_day.day_of_week] = tuple(
                sorted(set(intervals))
            )
            if not intervals:
                days_without_slots.append(working_day)

        return cls(
            working_days=tuple(working_days),
            slots_by_weekday=slots_by_weekday,
            days_without_slots=tuple(days_without_slots),
        )

    @property
    def has_working_days(self) -> bool:
        return bool(self.working_days)

    @property
    def has_slots(self) -> bool:
        return any(self.slots_by_weekday.values())

    @property
    def total_slot_minutes(self) -> int:
        """Weekly minutes available in the grid (adjacency counted once)."""
        return sum(total_minutes(slots) for slots in self.slots_by_weekday.values())

    @property
    def max_contiguous_minutes(self) -> int:
        """Longest single-session block the grid can host in one day."""
        if not self.slots_by_weekday:
            return 0
        return max(
            max_contiguous_minutes(slots) for slots in self.slots_by_weekday.values()
        )

    def usable_within(self, windows: WindowMap) -> UsableGrid:
        """Restrict the grid to slots fully covered by ``windows``.

        A slot counts only when it lies entirely inside one availability window
        of the matching weekday; a partially covered slot is not usable, because
        neither the instructor nor the room is available for the whole period.
        Because windows are continuous, merging the surviving adjacent slots
        yields a continuous block per run of windows.

        Totals are summed across the week, but contiguous blocks stay per weekday:
        a session has to fit inside a single day, so the block lengths of two
        different days must never be merged into one another.
        """
        covered_minutes = 0
        days = 0
        best_block = 0
        for weekday, slots in self.slots_by_weekday.items():
            day_windows = windows.get(weekday, ())
            day_usable = [
                (start, end)
                for start, end in slots
                if any(
                    start >= window_start and end <= window_end
                    for window_start, window_end in day_windows
                )
            ]
            if day_usable:
                days += 1
                covered_minutes += total_minutes(day_usable)
                best_block = max(best_block, max_contiguous_minutes(day_usable))
        return UsableGrid(
            total_minutes=covered_minutes,
            days=days,
            max_contiguous_minutes=best_block,
        )
