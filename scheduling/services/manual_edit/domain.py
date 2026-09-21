"""Value objects of validated manual schedule editing.

A manual edit is a *placement* proposal, never a content proposal: the sessions,
their instructors, their student groups and every historical snapshot value stay
exactly as the base version stored them, and only the weekday, the occupied periods
and the room may move. These dataclasses are the in-memory shape of that proposal,
so the validator and the clone step share one description of what the user asked
for.

Nothing here touches the database: a proposal is data, and the service decides when
to read and when to write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any, Mapping

from scheduling.services.persistence.snapshots import SlotSnapshot

#: Sentinel used by ``ManualEditChange`` when the caller omitted a field.
UNSET: Any = None


@dataclass(frozen=True)
class ManualEditChange:
    """One requested relocation of one existing entry.

    ``time_slot_ids`` and ``room_id`` are optional; an omitted field keeps the
    entry's current value. At least one of them must be present, which the request
    serializer enforces before a service ever sees the change.
    """

    entry_id: int
    time_slot_ids: tuple[int, ...] | None = None
    room_id: int | None = None

    @property
    def moves_time(self) -> bool:
        """True when the caller asked for new periods."""
        return self.time_slot_ids is not None

    @property
    def moves_room(self) -> bool:
        """True when the caller asked for a new room."""
        return self.room_id is not None


@dataclass(frozen=True)
class ManualEditIssue:
    """One reason a proposal was refused, or one structural complaint.

    ``entry_id`` names the entry the issue is about, ``conflicting_entry_id`` the
    other entry involved in a collision. Collisions are reported once per pair with
    the overlapping period ids in ``details`` rather than once per period.
    """

    code: str
    message: str
    entry_id: int | None = None
    conflicting_entry_id: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def sort_key(self) -> tuple:
        """Documented deterministic order: code, entry, conflicting entry, details."""
        return (
            self.code,
            self.entry_id if self.entry_id is not None else -1,
            (
                self.conflicting_entry_id
                if self.conflicting_entry_id is not None
                else -1
            ),
            tuple(sorted((str(key), str(value)) for key, value in self.details.items())),
        )


@dataclass(frozen=True)
class EntryPlacement:
    """Where one entry sits in the proposed version.

    ``time_changed`` distinguishes a move from a room swap: a room swap keeps the
    stored periods, including their snapshots, and only the room is rewritten.
    """

    slot_ids: tuple[int, ...]
    room_id: int | None
    changed: bool
    time_changed: bool
    day_of_week: int | None
    start_time: time | None
    end_time: time | None

    @property
    def is_schedulable(self) -> bool:
        """False when the proposal could not resolve a usable placement."""
        return bool(self.slot_ids) and self.day_of_week is not None


@dataclass(frozen=True)
class ProposedEntry:
    """One entry of the proposed version, with everything the clone step needs."""

    entry: Any
    placement: EntryPlacement
    instructor_ids: tuple[int, ...]
    student_group_ids: tuple[int, ...]
    slot_snapshots: tuple[SlotSnapshot, ...]
    penalty: int
    candidate_id: str
    base_duration_minutes: int

    @property
    def entry_id(self) -> int:
        return self.entry.pk

    @property
    def session_id(self) -> str:
        return self.entry.session_id

    @property
    def teaching_component_id(self) -> int:
        return self.entry.teaching_component_id


@dataclass(frozen=True)
class ProposedVersion:
    """The complete timetable the changes would produce, in memory."""

    base_version: Any
    entries: tuple[ProposedEntry, ...]
    changed_entry_ids: tuple[int, ...]

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def changed_entry_count(self) -> int:
        return len(self.changed_entry_ids)


@dataclass(frozen=True)
class ManualEditValidation:
    """The result of validating a proposal.

    ``valid`` is true only when no issue was reported. ``proposal`` is present even
    for an invalid request when the proposal could be built at all, so the apply step
    can reuse exactly what was validated.
    """

    base_version_id: int
    change_count: int
    issues: tuple[ManualEditIssue, ...] = ()
    proposal: ProposedVersion | None = None

    @property
    def valid(self) -> bool:
        """True when nothing blocks the proposal."""
        return not self.issues

    @property
    def error_count(self) -> int:
        """Number of issues reported."""
        return len(self.issues)

    def as_summary(self) -> dict[str, int]:
        """The compact counts block of a validation response."""
        return {"changes": self.change_count, "errors": self.error_count}


@dataclass(frozen=True)
class ManualEditResult:
    """What one apply attempt produced.

    ``persisted`` is the only success flag. A refused attempt explains itself with a
    reason code and never leaves a version behind.
    """

    persisted: bool
    reason: str | None = None
    message: str = ""
    validation: ManualEditValidation | None = None
    version: Any = None
    schedule: Any = None
    base_version_id: int | None = None
    entry_count: int = 0
    changed_entries: int = 0


__all__ = [
    "EntryPlacement",
    "ManualEditChange",
    "ManualEditIssue",
    "ManualEditResult",
    "ManualEditValidation",
    "ProposedEntry",
    "ProposedVersion",
    "UNSET",
]
