"""Room usage and utilization.

Usage is snapshot-stable: it counts the periods the version stores and the minutes
those periods cover. Utilization needs a denominator, and the snapshot does not
contain one, so the denominator comes from **today's** configuration: the active
periods of the schedule's semester that fall completely inside an active room
availability window.

Every row therefore names its basis. When current configuration cannot supply a
denominator, ``available_minutes`` and ``utilization_percent`` are ``None`` rather
than a guess. When the historical schedule occupies more time than today's
configuration allows, the percentage is reported above 100 and the mismatch is
flagged: clamping would hide exactly the evidence an administrator needs.
"""

from __future__ import annotations

from django.db.models import Prefetch

from collections import defaultdict

from resources.models import Room, RoomAvailability
from scheduling.models import TimeSlot
from scheduling.services.analytics.domain import (
    UTILIZATION_BASIS,
    EntryFacts,
    RoomUsage,
    SnapshotRef,
)
from scheduling.services.validation.time_grid import interval_minutes

#: Weekday key used by the availability windows map.
DayWindows = dict[int, tuple[tuple[int, int], ...]]


def weeks_availability_by_room(*, semester, room_ids) -> dict[int, int | None]:
    """Current weekly available minutes per room, or None when no basis exists.

    A period counts only when it lies fully inside one active availability window of
    the matching weekday, and it counts once even when several windows overlap it, so
    the denominator is real capacity rather than a sum of overlapping grants.
    """
    if not room_ids:
        return {}

    rows = (
        RoomAvailability.objects.filter(
            semester=semester, is_active=True, room_id__in=room_ids
        )
        .values_list("room_id", "day_of_week", "start_time", "end_time")
        .order_by("room_id", "day_of_week", "start_time")
    )
    windows: dict[int, DayWindows] = defaultdict(dict)
    for room_id, weekday, start, end in rows:
        interval = interval_minutes(start, end)
        if interval is None:
            continue
        windows[room_id].setdefault(int(weekday), []).append(interval)

    grid = _active_grid(semester)
    existing_rooms = set(
        Room.objects.filter(pk__in=room_ids, is_active=True).values_list(
            "pk", flat=True
        )
    )

    totals: dict[int, int | None] = {}
    for room_id in sorted(room_ids):
        if room_id not in existing_rooms:
            # The room is gone or inactive, so no current denominator can be stated.
            totals[room_id] = None
            continue
        room_windows = windows.get(room_id, {})
        covered: set[int] = set()
        minutes = 0
        for slot_id, weekday, start, end in grid:
            day_windows = room_windows.get(weekday, ())
            if not day_windows:
                continue
            inside = any(
                start >= window_start and end <= window_end
                for window_start, window_end in day_windows
            )
            if not inside or slot_id in covered:
                continue
            covered.add(slot_id)
            minutes += end - start
        totals[room_id] = minutes
    return totals


def _active_grid(semester) -> list[tuple[int, int, int, int]]:
    """Active periods of the semester as ``(slot_id, weekday, start, end)`` minutes.

    One query, ordered deterministically, so the denominator never depends on row
    order.
    """
    slots = (
        TimeSlot.objects.filter(
            is_active=True,
            working_day__semester=semester,
            working_day__is_active=True,
        )
        .values_list("pk", "working_day__day_of_week", "start_time", "end_time")
        .order_by("working_day__day_of_week", "start_time", "pk")
    )
    grid: list[tuple[int, int, int, int]] = []
    for slot_id, weekday, start, end in slots:
        interval = interval_minutes(start, end)
        if interval is None:
            continue
        grid.append((slot_id, int(weekday), interval[0], interval[1]))
    return grid


def build_room_usage(
    facts: tuple[EntryFacts, ...], *, available_by_room: dict[int, int | None]
) -> tuple[RoomUsage, ...]:
    """Usage per persisted room, ordered by room code then id.

    ``available_by_room`` maps a room id to its current weekly available minutes, or
    to ``None`` when no denominator can be derived.
    """
    grouped: dict[int, list[EntryFacts]] = defaultdict(list)
    rooms: dict[int, SnapshotRef] = {}
    for fact in facts:
        if fact.room is None or fact.room.id is None:
            continue
        grouped[fact.room.id].append(fact)
        rooms.setdefault(fact.room.id, fact.room)

    rows: list[RoomUsage] = []
    for room_id, entries in grouped.items():
        occupied_minutes = sum(entry.duration_minutes for entry in entries)
        occupied_slots = {
            slot_id for entry in entries for slot_id in entry.slot_ids
        }
        available = available_by_room.get(room_id)
        utilization: float | None = None
        mismatch = False
        if available is not None and available > 0:
            utilization = round(occupied_minutes / available * 100, 2)
            mismatch = occupied_minutes > available
        rows.append(
            RoomUsage(
                room=rooms[room_id],
                session_count=len(entries),
                occupied_minutes=occupied_minutes,
                occupied_slot_count=len(occupied_slots),
                days_used=len({entry.day_of_week for entry in entries}),
                available_minutes=available,
                utilization_percent=utilization,
                configuration_mismatch=mismatch,
                utilization_basis=UTILIZATION_BASIS,
            )
        )
    rows.sort(key=lambda row: (row.room.code, row.room.id or 0))
    return tuple(rows)


def room_ids(facts: tuple[EntryFacts, ...]) -> tuple[int, ...]:
    """Distinct room ids used by an entry set, sorted."""
    return tuple(
        sorted({fact.room.id for fact in facts if fact.room and fact.room.id})
    )


__all__ = [
    "build_room_usage",
    "room_ids",
    "weeks_availability_by_room",
]
