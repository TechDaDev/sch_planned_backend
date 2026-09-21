"""Building and validating a proposed manual timetable.

The validator answers one question: *if these changes were applied together, would
the resulting version be a valid weekly timetable?* It therefore builds the complete
proposed version first — every unchanged entry keeps its stored placement, every
changed entry takes its requested placement — and only then checks it. A swap of two
entries is evaluated as one final state, so an intermediate collision that exists
only because the changes were applied in some order never fails the request.

Two kinds of check run against that proposal:

* **placement checks** describe what is wrong with a requested placement on its own:
  the periods do not exist, are inactive, sit in another semester, span two days,
  leave a gap, no longer last the session's stored duration, or the entry's
  instructors or the target room are not usable at that time. Instructors and groups
  are never reassigned, so these checks only ask whether the *existing* resources
  still allow the *requested* times.
* **collision checks** describe the finished timetable: one instructor, room,
  student group or teaching component may not occupy the same period twice.

Placement checks are skipped for an entry whose periods could not be resolved into a
usable block, because every later answer would be noise; collision checks always run
over the whole proposed version.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from django.db.models import Prefetch
from resources.models import (
    InstructorAvailability,
    InstructorPreference,
    Room,
    RoomAvailability,
    TeachingComponentCapabilityRequirement,
    TeachingComponentRoomRequirement,
)
from scheduling.models import ScheduleEntry, ScheduleEntryTimeSlot, TimeSlot
from scheduling.services.generation.preferences import (
    PreferencePenaltyCalculator,
    build_preference_windows,
)
from scheduling.services.manual_edit.domain import (
    EntryPlacement,
    ManualEditChange,
    ManualEditIssue,
    ManualEditValidation,
    ProposedEntry,
    ProposedVersion,
)
from scheduling.services.manual_edit.issues import ManualEditIssueCode
from scheduling.services.persistence.snapshots import SlotSnapshot
from scheduling.services.validation.time_grid import (
    interval_minutes,
    time_to_minutes,
)

#: Interval inside one weekday, as minutes from midnight.
Interval = tuple[int, int]

#: Issue codes that stop the proposal from being built at all.
REQUEST_SHAPE_CODES: tuple[str, ...] = (
    ManualEditIssueCode.DUPLICATE_ENTRY_CHANGE,
    ManualEditIssueCode.ENTRY_NOT_IN_VERSION,
)


def _windows_by_key(rows: Iterable[tuple[int, int, Any, Any]]) -> dict[int, dict[int, tuple[Interval, ...]]]:
    """Group ``(key, weekday, start, end)`` rows into per-key weekday windows.

    Absence of a window is never treated as unrestricted availability, matching the
    generation adapter: an instructor or room without a row cannot host a session.
    """
    grouped: dict[int, dict[int, list[Interval]]] = {}
    for key, weekday, start, end in rows:
        interval = interval_minutes(start, end)
        if interval is None:
            continue
        grouped.setdefault(key, {}).setdefault(int(weekday), []).append(interval)
    return {
        key: {day: tuple(sorted(values)) for day, values in days.items()}
        for key, days in grouped.items()
    }


def _covers(windows: tuple[Interval, ...], start_minute: int, end_minute: int) -> bool:
    """True when one window fully contains ``[start_minute, end_minute)``."""
    return any(
        start_minute >= start and end_minute <= end for start, end in windows
    )


class ManualEditValidator:
    """Validates one set of placement changes against one base version."""

    def __init__(
        self,
        *,
        version,
        changes: Iterable[ManualEditChange],
    ) -> None:
        self.version = version
        self.changes = tuple(changes)
        self.schedule = version.schedule
        self.semester = self.schedule.semester
        self._issues: list[ManualEditIssue] = []
        self._entries: list[ScheduleEntry] = []
        self._base_slot_ids: dict[int, tuple[int, ...]] = {}
        self._base_durations: dict[int, int] = {}
        self._instructor_ids: dict[int, tuple[int, ...]] = {}
        self._group_ids: dict[int, tuple[int, ...]] = {}
        self._candidate_ids: dict[int, str] = {}
        self._slots: dict[int, TimeSlot] = {}
        self._rooms: dict[int, Any] = {}
        self._target_room_ids: set[int] = set()
        self._requirements: dict[int, Any] = {}
        self._placements: dict[int, EntryPlacement] = {}
        self._penalties: dict[int, int] = {}
        self._slot_snapshots: dict[int, tuple[SlotSnapshot, ...]] = {}

    # --- entry point -------------------------------------------------------

    def validate(self) -> ManualEditValidation:
        """Run every check and return the structured result."""
        self._entries = list(self._load_entries())
        self._check_request_shape()
        if self._has_codes(REQUEST_SHAPE_CODES):
            # The request itself names entries that cannot be trusted, so no honest
            # proposal can be built and the remaining checks would be guesses.
            return self._result(proposal=None)

        self._load_targets()
        proposal = self._build_proposal()
        self._check_placements()
        self._check_conflicts(proposal)
        return self._result(proposal=proposal)

    # --- loading -----------------------------------------------------------

    def _load_entries(self):
        """Base entries with the children a proposal and a clone both need.

        One pass loads the version's entries with their slot rows, instructors and
        groups, so no check below queries per entry.
        """
        return (
            ScheduleEntry.objects.filter(schedule_version=self.version)
            .select_related(
                "teaching_component",
                "teaching_component__offering",
                "managing_department",
                "room",
            )
            .prefetch_related(
                Prefetch(
                    "time_slots",
                    queryset=ScheduleEntryTimeSlot.objects.select_related(
                        "time_slot"
                    ).order_by("position"),
                ),
                "instructors",
                "student_groups",
            )
            .order_by("pk")
        )

    def _load_targets(self) -> None:
        """Bulk-load everything the requested placements refer to.

        Loading the periods, rooms, requirements, availability and preferences in a
        handful of queries is what keeps the validator independent of the size of the
        version: nothing below this point queries per entry, per period or per
        instructor.
        """
        slot_ids = {
            slot_id
            for change in self.changes
            if change.time_slot_ids is not None
            for slot_id in change.time_slot_ids
        }
        # An entry whose time does not move still needs its stored periods loaded: the
        # instructor and room checks ask about the time the session keeps, and a room
        # swap is only meaningful if that time is known.
        by_id = {entry.pk: entry for entry in self._entries}
        for change in self.changes:
            if change.time_slot_ids is not None:
                continue
            entry = by_id.get(change.entry_id)
            if entry is None:
                continue
            slot_ids.update(row.time_slot_id for row in entry.time_slots.all())

        # The target room of a change is the requested one, or the room the entry keeps
        # when only its time moves: a kept room still has to be available at the new
        # time, so it is checked like any other target.
        room_ids = set()
        for change in self.changes:
            room_id = change.room_id
            if room_id is None:
                entry = by_id.get(change.entry_id)
                room_id = entry.room_id if entry is not None else None
            if room_id is not None:
                room_ids.add(room_id)
        self._target_room_ids = room_ids
        room_ids = {
            change.room_id for change in self.changes if change.room_id is not None
        }
        if slot_ids:
            self._slots = {
                slot.pk: slot
                for slot in TimeSlot.objects.filter(pk__in=slot_ids).select_related(
                    "working_day"
                )
            }
        if room_ids:
            self._rooms = {
                room.pk: room
                for room in self._load_rooms(room_ids)
            }
        missing_slots = sorted(slot_ids - set(self._slots))
        for slot_id in missing_slots:
            self._add(
                ManualEditIssueCode.TIME_SLOT_NOT_FOUND,
                "The requested teaching period does not exist.",
                entry_id=self._entry_for_slot(slot_id),
                details={"time_slot_id": slot_id},
            )
        missing_rooms = sorted(room_ids - set(self._rooms))
        for room_id in missing_rooms:
            self._add(
                ManualEditIssueCode.ROOM_NOT_FOUND,
                "The requested room does not exist.",
                entry_id=self._entry_for_room(room_id),
                details={"room_id": room_id},
            )

        self._load_requirements()
        self._load_instructor_facts()

    def _load_rooms(self, room_ids):
        return (
            Room.objects.filter(pk__in=room_ids)
            .select_related("room_type")
            .prefetch_related("capability_assignments__capability", "department_access")
        )

    def _load_requirements(self) -> None:
        """The components' current active room requirements, capability links included.

        The capability links are prefetched *with* their capability so the canonical
        Phase 5 suitability helper never point-looks-up a capability per link, which is
        the Phase 7 N+1 fix reused here.
        """
        component_ids = {
            entry.teaching_component_id
            for entry in self._entries
            if entry.pk in self._changed_entry_ids()
        }
        if not component_ids:
            return
        requirements = (
            TeachingComponentRoomRequirement.objects.filter(
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
                )
            )
        )
        for requirement in requirements:
            self._requirements.setdefault(requirement.teaching_component_id, requirement)

    def _load_instructor_facts(self) -> None:
        """Availability and preferences of the instructors a change touches."""
        instructor_ids = {
            instructor_id
            for entry in self._entries
            if entry.pk in self._changed_entry_ids()
            for instructor_id in self._instructors_for(entry)
        }
        if not instructor_ids:
            self._preferences = PreferencePenaltyCalculator({})
            self._instructor_windows = {}
            self._room_windows = _windows_by_key(
                RoomAvailability.objects.filter(
                    semester=self.semester,
                    is_active=True,
                    room_id__in=self._target_room_ids,
                )
                .values_list("room_id", "day_of_week", "start_time", "end_time")
                .order_by("room_id", "day_of_week", "start_time")
            )
            return

        self._instructor_windows = _windows_by_key(
            InstructorAvailability.objects.filter(
                semester=self.semester,
                is_active=True,
                instructor_id__in=instructor_ids,
            )
            .values_list("instructor_id", "day_of_week", "start_time", "end_time")
            .order_by("instructor_id", "day_of_week", "start_time")
        )

        preference_rows = list(
            InstructorPreference.objects.filter(
                semester=self.semester,
                is_active=True,
                instructor_id__in=instructor_ids,
            )
            .values_list(
                "instructor_id",
                "day_of_week",
                "start_time",
                "end_time",
                "preference_type",
            )
            .order_by("instructor_id", "day_of_week", "start_time")
        )
        rows: list[tuple[int, int, int, int, str]] = []
        for instructor_id, weekday, start, end, preference_type in preference_rows:
            interval = interval_minutes(start, end)
            if interval is None:
                continue
            rows.append(
                (instructor_id, int(weekday), interval[0], interval[1], preference_type)
            )
        self._preferences = PreferencePenaltyCalculator(build_preference_windows(rows))

        self._room_windows = _windows_by_key(
            RoomAvailability.objects.filter(
                semester=self.semester,
                is_active=True,
                room_id__in=self._target_room_ids,
            )
            .values_list("room_id", "day_of_week", "start_time", "end_time")
            .order_by("room_id", "day_of_week", "start_time")
        )

    # --- request shape -----------------------------------------------------

    def _check_request_shape(self) -> None:
        """Duplicates and entries that do not belong to this version."""
        seen: dict[int, int] = {}
        for change in self.changes:
            seen[change.entry_id] = seen.get(change.entry_id, 0) + 1
        for entry_id in sorted(seen):
            if seen[entry_id] > 1:
                self._add(
                    ManualEditIssueCode.DUPLICATE_ENTRY_CHANGE,
                    "The same entry was changed more than once in one request.",
                    entry_id=entry_id,
                    details={"occurrences": seen[entry_id]},
                )
        known = {entry.pk for entry in self._entries}
        for change in self.changes:
            if change.entry_id not in known:
                self._add(
                    ManualEditIssueCode.ENTRY_NOT_IN_VERSION,
                    "The entry does not belong to this schedule version.",
                    entry_id=change.entry_id,
                )

    def _changed_entry_ids(self) -> set[int]:
        return {change.entry_id for change in self.changes}

    # --- proposal ----------------------------------------------------------

    def _build_proposal(self) -> ProposedVersion:
        """Resolve every entry's placement in the finished timetable.

        Unchanged entries keep what the base version stored. Changed entries take the
        requested periods and room, or the stored value for whichever half of the
        placement the caller left out.
        """
        self._resolve_placements()
        proposed: list[ProposedEntry] = []
        for entry in self._entries:
            placement = self._placements[entry.pk]
            self._slot_snapshots[entry.pk] = self._snapshots_for(entry, placement)
            if placement.changed:
                self._penalties[entry.pk] = self._penalty_for(entry, placement)
            else:
                self._penalties[entry.pk] = entry.penalty
            proposed.append(
                ProposedEntry(
                    entry=entry,
                    placement=placement,
                    instructor_ids=self._instructors_for(entry),
                    student_group_ids=self._groups_for(entry),
                    slot_snapshots=self._slot_snapshots[entry.pk],
                    penalty=self._penalties[entry.pk],
                    candidate_id=self._candidate_id_for(entry, placement),
                    base_duration_minutes=self._base_durations[entry.pk],
                )
            )
        return ProposedVersion(
            base_version=self.version,
            entries=tuple(proposed),
            changed_entry_ids=tuple(sorted(self._changed_entry_ids())),
        )

    def _resolve_placements(self) -> None:
        """Work out the placement of every entry, changed or not."""
        changes = {change.entry_id: change for change in self.changes}
        for entry in self._entries:
            slot_rows = list(entry.time_slots.all())
            base_slot_ids = tuple(row.time_slot_id for row in slot_rows)
            self._base_slot_ids[entry.pk] = base_slot_ids
            self._base_durations[entry.pk] = sum(
                self._row_minutes(row) for row in slot_rows
            )
            self._instructor_ids[entry.pk] = self._instructors_for(entry)
            self._group_ids[entry.pk] = self._groups_for(entry)
            self._candidate_ids[entry.pk] = entry.candidate_id

            change = changes.get(entry.pk)
            if change is None:
                self._placements[entry.pk] = EntryPlacement(
                    slot_ids=base_slot_ids,
                    room_id=entry.room_id,
                    changed=False,
                    time_changed=False,
                    day_of_week=entry.day_of_week,
                    start_time=entry.start_time,
                    end_time=entry.end_time,
                )
                continue

            time_changed = change.time_slot_ids is not None
            target_slots = (
                self._requested_slots(change)
                if time_changed
                else tuple(self._slots_for_ids(base_slot_ids))
            )
            room_id = change.room_id if change.room_id is not None else entry.room_id
            self._placements[entry.pk] = EntryPlacement(
                slot_ids=tuple(slot.pk for slot in target_slots),
                room_id=room_id,
                changed=True,
                time_changed=time_changed,
                day_of_week=(
                    int(target_slots[0].working_day.day_of_week)
                    if target_slots
                    else entry.day_of_week
                ),
                start_time=target_slots[0].start_time if target_slots else entry.start_time,
                end_time=target_slots[-1].end_time if target_slots else entry.end_time,
            )

    def _requested_slots(self, change: ManualEditChange) -> tuple[TimeSlot, ...]:
        """Requested periods in canonical timetable order, ignoring client order.

        Unknown ids are dropped here; they were already reported, and the placement
        checks that follow treat the entry as one whose block could not be resolved.
        """
        requested = [
            self._slots[slot_id]
            for slot_id in (change.time_slot_ids or ())
            if slot_id in self._slots
        ]
        requested.sort(key=lambda slot: (slot.start_time, slot.sequence, slot.pk))
        return tuple(requested)

    def _slots_for_ids(self, slot_ids: Iterable[int]) -> list[TimeSlot]:
        """Loaded periods of a list of ids, in the order given."""
        return [self._slots[slot_id] for slot_id in slot_ids if slot_id in self._slots]

    def _snapshots_for(
        self, entry: ScheduleEntry, placement: EntryPlacement
    ) -> tuple[SlotSnapshot, ...]:
        """Period rows of the proposed version for one entry.

        An entry whose periods do not move keeps its stored rows, including their
        snapshots, so a historical period label is never rewritten from today's
        configuration and a room swap does not refresh the timetable. Only a move
        writes fresh snapshots of the periods it now occupies.
        """
        if not placement.time_changed:
            return tuple(
                SlotSnapshot(
                    time_slot_id=row.time_slot_id,
                    position=row.position,
                    sequence=row.sequence_snapshot,
                    label=row.label_snapshot,
                    start_time=row.start_time_snapshot,
                    end_time=row.end_time_snapshot,
                )
                for row in entry.time_slots.all()
            )
        return tuple(
            SlotSnapshot(
                time_slot_id=slot.pk,
                position=position,
                sequence=slot.sequence,
                label=slot.label or "",
                start_time=slot.start_time,
                end_time=slot.end_time,
            )
            for position, slot in enumerate(self._slots_for(placement), start=1)
        )

    # --- placement checks --------------------------------------------------

    def _check_placements(self) -> None:
        """Per-entry checks of a requested placement."""
        for change in self.changes:
            placement = self._placements.get(change.entry_id)
            if placement is None or not placement.changed:
                continue
            entry = self._entry_by_id(change.entry_id)
            if entry is None:
                continue
            if not self._check_slot_block(entry, placement):
                continue
            self._check_instructors(entry, placement)
            self._check_room(entry, placement)

    def _check_slot_block(self, entry: ScheduleEntry, placement: EntryPlacement) -> bool:
        """Whether the requested periods form a usable block; report why not.

        A placement whose time did not move is already the stored one, so there is
        nothing to re-derive. Returns False when a moved block is unusable, because the
        instructor and room checks would then describe a session that cannot exist.
        """
        if not placement.time_changed:
            return True
        slots = list(self._slots_for(placement))
        if len(slots) != len(placement.slot_ids):
            return False

        usable = True
        for slot in slots:
            if not slot.is_active or not slot.working_day.is_active:
                usable = False
                self._add(
                    ManualEditIssueCode.TIME_SLOT_INACTIVE,
                    "The requested teaching period is not active.",
                    entry_id=entry.pk,
                    details={
                        "time_slot_id": slot.pk,
                        "reason": (
                            "inactive_time_slot"
                            if not slot.is_active
                            else "inactive_working_day"
                        ),
                    },
                )
            elif slot.working_day.semester_id != self.semester.pk:
                usable = False
                self._add(
                    ManualEditIssueCode.TIME_SLOT_WRONG_SEMESTER,
                    "The requested teaching period belongs to another semester.",
                    entry_id=entry.pk,
                    details={"time_slot_id": slot.pk},
                )
        if not usable:
            return False

        weekdays = {slot.working_day.day_of_week for slot in slots}
        if len(weekdays) > 1:
            self._add(
                ManualEditIssueCode.TIME_SLOTS_DIFFERENT_DAY,
                "One session cannot span more than one weekday.",
                entry_id=entry.pk,
                details={"days": sorted(int(day) for day in weekdays)},
            )
            return False

        if not self._is_contiguous(slots):
            self._add(
                ManualEditIssueCode.TIME_SLOTS_NOT_CONTIGUOUS,
                "The requested teaching periods are not adjacent.",
                entry_id=entry.pk,
                details={"slot_ids": [slot.pk for slot in slots]},
            )
            return False

        proposed_minutes = sum(self._slot_minutes(slot) for slot in slots)
        required_minutes = self._base_durations[entry.pk]
        if proposed_minutes != required_minutes:
            self._add(
                ManualEditIssueCode.SESSION_DURATION_MISMATCH,
                "The requested periods do not last as long as the stored session.",
                entry_id=entry.pk,
                details={
                    "required_minutes": required_minutes,
                    "proposed_minutes": proposed_minutes,
                },
            )
            return False
        return True

    @staticmethod
    def _is_contiguous(slots: list[TimeSlot]) -> bool:
        """True when each period starts exactly when the previous one ends."""
        for previous, current in zip(slots, slots[1:]):
            if previous.end_time != current.start_time:
                return False
        return True

    def _check_instructors(self, entry: ScheduleEntry, placement: EntryPlacement) -> None:
        """The entry's own instructors must still allow the requested periods."""
        slots = self._slots_for(placement)
        day = placement.day_of_week
        for row in entry.instructors.all():
            instructor = row.instructor
            if not instructor.is_active:
                self._add(
                    ManualEditIssueCode.INSTRUCTOR_INACTIVE,
                    "An instructor of this session is no longer active.",
                    entry_id=entry.pk,
                    details={"instructor_id": row.instructor_id},
                )
                continue
            if not instructor.can_teach_in_department(entry.managing_department):
                self._add(
                    ManualEditIssueCode.INSTRUCTOR_NOT_ELIGIBLE,
                    "An instructor of this session may no longer teach for the "
                    "managing department.",
                    entry_id=entry.pk,
                    details={"instructor_id": row.instructor_id},
                )
                continue
            windows = self._instructor_windows.get(row.instructor_id, {}).get(day, ())
            uncovered = [
                slot.pk
                for slot in slots
                if not _covers(
                    windows,
                    time_to_minutes(slot.start_time),
                    time_to_minutes(slot.end_time),
                )
            ]
            if uncovered:
                self._add(
                    ManualEditIssueCode.INSTRUCTOR_UNAVAILABLE,
                    "An instructor of this session is not available at the "
                    "requested time.",
                    entry_id=entry.pk,
                    details={
                        "instructor_id": row.instructor_id,
                        "slot_ids": uncovered,
                    },
                )

    def _check_room(self, entry: ScheduleEntry, placement: EntryPlacement) -> None:
        """The target room must be usable, suitable and available at that time."""
        room = self._rooms.get(placement.room_id) if placement.room_id else None
        if room is None:
            return
        if not room.is_active or not room.room_type.is_active:
            self._add(
                ManualEditIssueCode.ROOM_INACTIVE,
                "The target room or its room type is not active.",
                entry_id=entry.pk,
                details={"room_id": room.pk},
            )
            return
        if not room.can_be_used_by_department(entry.managing_department):
            self._add(
                ManualEditIssueCode.ROOM_NOT_ELIGIBLE,
                "The target room is not shared with the session's managing "
                "department.",
                entry_id=entry.pk,
                details={"room_id": room.pk},
            )
            return

        requirement = self._requirements.get(entry.teaching_component_id)
        if requirement is None:
            self._add(
                ManualEditIssueCode.ROOM_REQUIREMENT_UNSATISFIED,
                "The teaching component has no active room requirement, so no room "
                "can be confirmed as suitable.",
                entry_id=entry.pk,
                details={"reason": "requirement_missing_or_inactive"},
            )
            return
        reasons = room.evaluate_suitability(requirement)
        if reasons:
            self._add(
                ManualEditIssueCode.ROOM_REQUIREMENT_UNSATISFIED,
                "The target room does not satisfy the component's room requirement.",
                entry_id=entry.pk,
                details={"room_id": room.pk, "reasons": reasons},
            )
            return

        windows = self._room_windows.get(room.pk, {}).get(placement.day_of_week, ())
        uncovered = [
            slot.pk
            for slot in self._slots_for(placement)
            if not _covers(
                windows, time_to_minutes(slot.start_time), time_to_minutes(slot.end_time)
            )
        ]
        if uncovered:
            self._add(
                ManualEditIssueCode.ROOM_UNAVAILABLE,
                "The target room is not available at the requested time.",
                entry_id=entry.pk,
                details={"room_id": room.pk, "slot_ids": uncovered},
            )

    # --- collision checks --------------------------------------------------

    def _check_conflicts(self, proposal: ProposedVersion) -> None:
        """Nobody may occupy one period twice in the finished timetable.

        Overlaps are detected at *period* granularity: two sessions collide when they
        share a teaching period, which is exactly how the solver reasons about its own
        candidates. Every pair is reported once, with the shared periods listed, so a
        two-period clash produces one issue instead of two identical ones.
        """
        occupancy: dict[tuple[str, int, int], set[int]] = {}

        def occupy(kind: str, resource_id: int, slot_ids: Iterable[int], entry_id: int):
            for slot_id in slot_ids:
                occupancy.setdefault((kind, resource_id, slot_id), set()).add(entry_id)

        for proposed in proposal.entries:
            entry_id = proposed.entry_id
            for instructor_id in proposed.instructor_ids:
                occupy("instructor", instructor_id, proposed.placement.slot_ids, entry_id)
            if proposed.placement.room_id is not None:
                occupy("room", proposed.placement.room_id, proposed.placement.slot_ids, entry_id)
            for group_id in proposed.student_group_ids:
                occupy("group", group_id, proposed.placement.slot_ids, entry_id)
            occupy(
                "component",
                proposed.teaching_component_id,
                proposed.placement.slot_ids,
                entry_id,
            )

        codes = {
            "instructor": ManualEditIssueCode.INSTRUCTOR_CONFLICT,
            "room": ManualEditIssueCode.ROOM_CONFLICT,
            "group": ManualEditIssueCode.STUDENT_GROUP_CONFLICT,
            "component": ManualEditIssueCode.COMPONENT_CONFLICT,
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
                    key = (kind, resource_id, first, second)
                    pairs.setdefault(key, set()).add(slot_id)

        for kind, resource_id, first, second in sorted(pairs):
            slot_ids = sorted(pairs[(kind, resource_id, first, second)])
            self._add(
                codes[kind],
                messages[kind],
                entry_id=first,
                conflicting_entry_id=second,
                details={
                    "resource": kind,
                    "resource_id": resource_id,
                    "slot_ids": slot_ids,
                },
            )

    # --- helpers -----------------------------------------------------------

    def _slots_for(self, placement: EntryPlacement) -> list[TimeSlot]:
        """The loaded periods of a placement, in the order the placement lists them."""
        return [
            self._slots[slot_id]
            for slot_id in placement.slot_ids
            if slot_id in self._slots
        ]

    def _instructors_for(self, entry: ScheduleEntry) -> tuple[int, ...]:
        """Instructor ids persisted on the entry, in a stable order.

        Membership is never re-derived from the component's current assignments: the
        stored rows are the historical truth, and a manual edit may not change them.
        """
        cached = self._instructor_ids.get(entry.pk)
        if cached is not None:
            return cached
        return tuple(sorted(row.instructor_id for row in entry.instructors.all()))

    def _groups_for(self, entry: ScheduleEntry) -> tuple[int, ...]:
        """Student group ids persisted on the entry, in a stable order."""
        cached = self._group_ids.get(entry.pk)
        if cached is not None:
            return cached
        return tuple(sorted(row.student_group_id for row in entry.student_groups.all()))

    def _penalty_for(self, entry: ScheduleEntry, placement: EntryPlacement) -> int:
        """Preference penalty of the requested interval, using the Phase 9 policy.

        Only the entry's own instructors count, and nothing is re-optimised: the
        number is reported for the placement the user asked for.
        """
        start_minute = time_to_minutes(placement.start_time)
        end_minute = time_to_minutes(placement.end_time)
        if start_minute is None or end_minute is None or placement.day_of_week is None:
            return entry.penalty
        return self._preferences.penalty_for(
            self._instructors_for(entry),
            placement.day_of_week,
            start_minute,
            end_minute,
        )

    @staticmethod
    def _candidate_id_for(entry: ScheduleEntry, placement: EntryPlacement) -> str:
        """Candidate identity of the proposed placement.

        A solver candidate id names a *generated* alternative, which stops being true
        once a session is moved by hand, so a changed entry gets a documented manual
        identifier instead. An unchanged entry keeps its solver candidate id.
        """
        if not placement.changed:
            return entry.candidate_id
        slots = "-".join(str(slot_id) for slot_id in placement.slot_ids)
        return (
            f"manual:{entry.pk}:day:{placement.day_of_week}"
            f":slots:{slots}:room:{placement.room_id}"
        )

    def _entry_by_id(self, entry_id: int) -> ScheduleEntry | None:
        for entry in self._entries:
            if entry.pk == entry_id:
                return entry
        return None

    def _entry_for_slot(self, slot_id: int) -> int | None:
        for change in self.changes:
            if change.time_slot_ids and slot_id in change.time_slot_ids:
                return change.entry_id
        return None

    def _entry_for_room(self, room_id: int) -> int | None:
        for change in self.changes:
            if change.room_id == room_id:
                return change.entry_id
        return None

    @staticmethod
    def _row_minutes(row: ScheduleEntryTimeSlot) -> int:
        """Duration of one stored period snapshot, in minutes."""
        interval = interval_minutes(row.start_time_snapshot, row.end_time_snapshot)
        return 0 if interval is None else interval[1] - interval[0]

    @staticmethod
    def _slot_minutes(slot: TimeSlot) -> int:
        """Duration of one teaching period, in minutes."""
        interval = interval_minutes(slot.start_time, slot.end_time)
        return 0 if interval is None else interval[1] - interval[0]

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
            ManualEditIssue(
                code=code,
                message=message,
                entry_id=entry_id,
                conflicting_entry_id=conflicting_entry_id,
                details=dict(details or {}),
            )
        )

    def _has_codes(self, codes: Iterable[str]) -> bool:
        wanted = set(codes)
        return any(issue.code in wanted for issue in self._issues)

    def _result(self, *, proposal: ProposedVersion | None) -> ManualEditValidation:
        """Deterministic, deduplicated result of this run.

        Repeated issues of the same code about the same entry pair are merged, and
        identical duplicates are dropped, so one clash between two multi-period
        sessions is reported once with all shared periods listed.
        """
        kept: dict[tuple, ManualEditIssue] = {}
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
                kept[key] = ManualEditIssue(
                    code=issue.code,
                    message=issue.message,
                    entry_id=issue.entry_id,
                    conflicting_entry_id=issue.conflicting_entry_id,
                    details={**issue.details, "slot_ids": sorted(merged)},
                )
        issues = tuple(sorted(kept.values(), key=lambda issue: issue.sort_key))
        return ManualEditValidation(
            base_version_id=self.version.pk,
            change_count=len(self.changes),
            issues=issues,
            proposal=proposal,
        )


__all__ = [
    "REQUEST_SHAPE_CODES",
    "ManualEditValidator",
]
