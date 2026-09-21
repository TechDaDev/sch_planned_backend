"""Exact contiguous slot-block construction.

A session has to occupy whole teaching periods: the timetable grid is discrete, so
a 90-minute session fits a pair of 45-minute periods but not a pair of 60-minute
ones. Choosing the latter would reserve 120 minutes for a 90-minute session, which
silently steals teaching time from the rest of the grid.

The rule enforced here is therefore *exact*: a block is valid only when its
periods are adjacent in time (``previous end == next start``) and their durations
sum to precisely the required session length. Periods may differ in length, so
``30 + 60``, ``45 + 45`` and ``30 + 30 + 30`` are all valid 90-minute blocks.

This module is pure: it holds no Django, ORM or OR-Tools imports, and works on
minute integers supplied by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class GridSlot:
    """One teaching period of the weekly grid, in minute arithmetic."""

    slot_id: int
    weekday: int
    sequence: int
    start_minute: int
    end_minute: int

    @property
    def duration_minutes(self) -> int:
        """Length of the period, or 0 when the stored times are unusable."""
        if self.end_minute <= self.start_minute:
            return 0
        return self.end_minute - self.start_minute


@dataclass(frozen=True)
class SlotBlock:
    """One or more adjacent periods that together hold exactly one session."""

    weekday: int
    slots: tuple[GridSlot, ...]

    @property
    def slot_ids(self) -> tuple[int, ...]:
        """Period identifiers in timetable order."""
        return tuple(slot.slot_id for slot in self.slots)

    @property
    def start_minute(self) -> int:
        """Start minute of the first period."""
        return self.slots[0].start_minute

    @property
    def end_minute(self) -> int:
        """End minute of the last period."""
        return self.slots[-1].end_minute

    @property
    def duration_minutes(self) -> int:
        """Total length of the block."""
        return sum(slot.duration_minutes for slot in self.slots)


def find_exact_contiguous_slot_blocks(
    ordered_slots: Sequence[GridSlot],
    required_minutes: int,
) -> tuple[SlotBlock, ...]:
    """Return every block of ``ordered_slots`` that is exactly ``required_minutes`` long.

    ``ordered_slots`` must contain the periods of **one** weekday, ordered by start
    time. A run stops as soon as a gap appears or the running total would exceed
    the requirement, so every returned block is contiguous and exact. The result
    keeps the input order, which makes candidate generation deterministic.
    """
    if required_minutes <= 0:
        return ()

    slots = tuple(ordered_slots)
    blocks: list[SlotBlock] = []
    for start_index in range(len(slots)):
        running_minutes = 0
        group: list[GridSlot] = []
        for slot in slots[start_index:]:
            if group and slot.start_minute != group[-1].end_minute:
                break
            running_minutes += slot.duration_minutes
            if running_minutes > required_minutes:
                break
            group.append(slot)
            if running_minutes == required_minutes:
                blocks.append(SlotBlock(weekday=slot.weekday, slots=tuple(group)))
                break
    return tuple(blocks)


def find_exact_blocks_by_weekday(
    slots_by_weekday: Mapping[int, Sequence[GridSlot]],
    required_minutes: int,
) -> tuple[SlotBlock, ...]:
    """Exact blocks for every weekday, ordered by weekday then start time.

    Weekdays are visited in ascending order so two runs over the same data produce
    the same candidate order.
    """
    blocks: list[SlotBlock] = []
    for weekday in sorted(slots_by_weekday):
        blocks.extend(
            find_exact_contiguous_slot_blocks(
                slots_by_weekday[weekday], required_minutes
            )
        )
    return tuple(blocks)


def group_slots_by_weekday(slots: Iterable[GridSlot]) -> dict[int, tuple[GridSlot, ...]]:
    """Group grid periods by weekday, each group ordered by start then sequence."""
    grouped: dict[int, list[GridSlot]] = {}
    for slot in slots:
        grouped.setdefault(slot.weekday, []).append(slot)
    return {
        weekday: tuple(sorted(values, key=lambda item: (item.start_minute, item.sequence, item.slot_id)))
        for weekday, values in grouped.items()
    }


__all__ = [
    "GridSlot",
    "SlotBlock",
    "find_exact_blocks_by_weekday",
    "find_exact_contiguous_slot_blocks",
    "group_slots_by_weekday",
]
