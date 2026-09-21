"""Candidate-local instructor preference penalties.

This is the first mapping from stored preferences to the engine's generic
non-negative candidate penalty. The policy is deliberately small and explicit,
because a candidate carries one number and the solver only minimises their sum.

Per instructor, for one candidate time interval:

* ``AVOID`` wins: overlapping an active AVOID window costs :data:`PENALTY_AVOID`.
* otherwise, the interval lying entirely inside an active PREFERRED window costs
  :data:`PENALTY_PREFERRED`.
* otherwise the placement is neutral and costs :data:`PENALTY_NEUTRAL`.

A candidate's penalty is the sum over every assigned instructor, so an assistant
counts exactly like a primary instructor.

Preferences are soft. An AVOID window is never treated as unavailability - that is
what ``InstructorAvailability`` is for - so a session is never made impossible by
a preference alone.

Only candidate-local terms live here. Gap minimisation, day spreading, theory
before practical and daily balancing need pairwise or global terms and belong to a
later optimisation phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from resources.models import PreferenceType

#: Cost of a placement that is fully inside a PREFERRED window.
PENALTY_PREFERRED = 0

#: Cost of an ordinary placement with no applicable preference.
PENALTY_NEUTRAL = 5

#: Cost of a placement that overlaps an AVOID window.
PENALTY_AVOID = 20

#: ``(start_minute, end_minute)`` windows of one instructor on one weekday.
Interval = tuple[int, int]


@dataclass(frozen=True)
class InstructorPreferenceWindows:
    """Preference windows of one instructor, split by weekday and type."""

    preferred: Mapping[int, tuple[Interval, ...]] = field(default_factory=dict)
    avoid: Mapping[int, tuple[Interval, ...]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.preferred and not self.avoid


def _intervals_for(rows: Iterable[tuple[int, int, int]]) -> dict[int, tuple[Interval, ...]]:
    """Group ``(weekday, start_minute, end_minute)`` rows by weekday."""
    grouped: dict[int, list[Interval]] = {}
    for weekday, start_minute, end_minute in rows:
        if end_minute <= start_minute:
            continue
        grouped.setdefault(weekday, []).append((start_minute, end_minute))
    return {
        weekday: tuple(sorted(values)) for weekday, values in grouped.items()
    }


def build_preference_windows(
    rows: Iterable[tuple[int, int, int, int, str]],
) -> dict[int, InstructorPreferenceWindows]:
    """Build per-instructor windows from plain ``(instructor_id, weekday, start, end, type)`` rows.

    Taking plain rows keeps this module free of ORM coupling, so the penalty policy
    can be unit-tested without a database.
    """
    preferred_rows: dict[int, list[tuple[int, int, int]]] = {}
    avoid_rows: dict[int, list[tuple[int, int, int]]] = {}
    for instructor_id, weekday, start_minute, end_minute, preference_type in rows:
        target = (
            avoid_rows if preference_type == PreferenceType.AVOID else preferred_rows
        )
        target.setdefault(instructor_id, []).append(
            (weekday, start_minute, end_minute)
        )

    instructor_ids = set(preferred_rows) | set(avoid_rows)
    return {
        instructor_id: InstructorPreferenceWindows(
            preferred=_intervals_for(preferred_rows.get(instructor_id, [])),
            avoid=_intervals_for(avoid_rows.get(instructor_id, [])),
        )
        for instructor_id in instructor_ids
    }


def penalty_for_one_instructor(
    windows: InstructorPreferenceWindows | None,
    weekday: int,
    start_minute: int,
    end_minute: int,
) -> int:
    """Penalty one instructor contributes for occupying ``[start, end)``."""
    if windows is None or windows.is_empty:
        return PENALTY_NEUTRAL

    for window_start, window_end in windows.avoid.get(weekday, ()):
        if start_minute < window_end and end_minute > window_start:
            return PENALTY_AVOID

    for window_start, window_end in windows.preferred.get(weekday, ()):
        if start_minute >= window_start and end_minute <= window_end:
            return PENALTY_PREFERRED

    return PENALTY_NEUTRAL


class PreferencePenaltyCalculator:
    """Sums the per-instructor penalty of a candidate time interval."""

    def __init__(self, windows_by_instructor: Mapping[int, InstructorPreferenceWindows]) -> None:
        self._windows = dict(windows_by_instructor)

    def penalty_for(
        self,
        instructor_ids: Iterable[int],
        weekday: int,
        start_minute: int,
        end_minute: int,
    ) -> int:
        """Total penalty for every assigned instructor of one candidate."""
        return sum(
            penalty_for_one_instructor(
                self._windows.get(instructor_id), weekday, start_minute, end_minute
            )
            for instructor_id in instructor_ids
        )


__all__ = [
    "PENALTY_AVOID",
    "PENALTY_NEUTRAL",
    "PENALTY_PREFERRED",
    "InstructorPreferenceWindows",
    "PreferencePenaltyCalculator",
    "build_preference_windows",
    "penalty_for_one_instructor",
]
