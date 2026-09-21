"""Instructor and room facts the pre-scheduling validator needs.

Two rules shape this module:

* **No second rule set.** Instructor eligibility and room suitability reuse the
  canonical Phase 4/5 model methods (``InstructorProfile.can_teach_in_department``
  and ``Room.meets_requirement``). Sharing scope, access grants, room type,
  capacity and capability behaviour therefore cannot drift away from the rest of
  the API.
* **No N+1.** Availability rows for the semester are read once and grouped in
  memory, and the verdict of the canonical room helper is memoised per
  ``(room, requirement shape)`` so the cost is bounded by the number of distinct
  requirement shapes rather than by the number of teaching components.
"""

from __future__ import annotations

from datetime import time

from resources.models import InstructorAvailability, Room, RoomAvailability

from scheduling.services.validation.time_grid import (
    TimeGrid,
    UsableGrid,
    WindowMap,
    group_windows,
)


class ResourceFacts:
    """Read-only instructor and room availability for one semester."""

    def __init__(self, *, semester, grid: TimeGrid) -> None:
        self.semester = semester
        self.grid = grid
        self._instructor_windows: dict[int, WindowMap] = {}
        self._instructor_availability_loaded = False
        self._instructor_usable: dict[int, UsableGrid] = {}
        self._room_availability: dict[int, WindowMap] = {}
        self._room_availability_loaded = False
        self._room_usable: dict[int, UsableGrid] = {}
        self._eligibility: dict[tuple[int, int], bool] = {}
        self._room_pool: list[Room] | None = None
        self._suitability: dict[tuple[int, tuple], bool] = {}

    # --- instructors -------------------------------------------------------

    def _load_instructor_availability(self) -> None:
        if self._instructor_availability_loaded:
            return
        rows = (
            InstructorAvailability.objects.filter(
                semester=self.semester, is_active=True
            )
            .values_list("instructor_id", "day_of_week", "start_time", "end_time")
            .order_by("instructor_id", "day_of_week", "start_time")
        )
        grouped: dict[int, list[tuple[int, time, time]]] = {}
        for instructor_id, weekday, start, end in rows:
            grouped.setdefault(instructor_id, []).append((weekday, start, end))
        self._instructor_windows = {
            instructor_id: group_windows(values)
            for instructor_id, values in grouped.items()
        }
        self._instructor_availability_loaded = True

    def has_instructor_availability(self, instructor_id: int) -> bool:
        """True when the instructor configured any active window this semester.

        Absence is never read as unrestricted availability.
        """
        self._load_instructor_availability()
        return instructor_id in self._instructor_windows

    def usable_for_instructor(self, instructor_id: int) -> UsableGrid:
        """Grid time the instructor's availability actually covers."""
        cached = self._instructor_usable.get(instructor_id)
        if cached is None:
            self._load_instructor_availability()
            cached = self.grid.usable_within(
                self._instructor_windows.get(instructor_id, {})
            )
            self._instructor_usable[instructor_id] = cached
        return cached

    def is_eligible(self, instructor, department) -> bool:
        """Whether ``instructor`` may still teach for ``department``.

        Memoised per instructor/department pair because the canonical helper asks
        the database about sharing grants.
        """
        if instructor is None or department is None:
            return False
        key = (instructor.pk, department.pk)
        if key not in self._eligibility:
            self._eligibility[key] = instructor.can_teach_in_department(department)
        return self._eligibility[key]

    # --- rooms -------------------------------------------------------------

    def _load_room_availability(self) -> None:
        if self._room_availability_loaded:
            return
        rows = (
            RoomAvailability.objects.filter(semester=self.semester, is_active=True)
            .values_list("room_id", "day_of_week", "start_time", "end_time")
            .order_by("room_id", "day_of_week", "start_time")
        )
        grouped: dict[int, list[tuple[int, time, time]]] = {}
        for room_id, weekday, start, end in rows:
            grouped.setdefault(room_id, []).append((weekday, start, end))
        self._room_availability = {
            room_id: group_windows(values) for room_id, values in grouped.items()
        }
        self._room_availability_loaded = True

    def has_room_availability(self, room_id: int) -> bool:
        """True when the room has any active availability row this semester."""
        self._load_room_availability()
        return room_id in self._room_availability

    def usable_for_room(self, room_id: int) -> UsableGrid:
        """Grid time the room's own availability actually covers."""
        cached = self._room_usable.get(room_id)
        if cached is None:
            self._load_room_availability()
            cached = self.grid.usable_within(self._room_availability.get(room_id, {}))
            self._room_usable[room_id] = cached
        return cached

    def room_pool(self) -> list[Room]:
        """All active rooms, loaded once with their type, capabilities and grants."""
        if self._room_pool is None:
            self._room_pool = list(
                Room.objects.filter(is_active=True)
                .select_related("room_type")
                .prefetch_related(
                    "capability_assignments__capability",
                    "department_access",
                )
                .order_by("pk")
            )
        return self._room_pool

    @staticmethod
    def requirement_signature(requirement) -> tuple:
        """The requirement inputs the canonical suitability helper reads.

        Two requirements with the same signature get the same answer for a given
        room, which is what makes memoising the verdict sound.
        """
        component = requirement.teaching_component
        return (
            component.offering.managing_department_id,
            requirement.required_room_type_id,
            requirement.effective_minimum_capacity,
            tuple(
                sorted(
                    link.capability_id
                    for link in requirement.capability_requirements.all()
                )
            ),
        )

    @staticmethod
    def _may_satisfy_shape(room: Room, requirement) -> bool:
        """Cheap necessary conditions used only to keep the room pool small.

        Every condition is implied by ``Room.meets_requirement``: a room failing
        one of them could never be suitable. Narrowing on them therefore cannot
        change the outcome; it only keeps the canonical check - which reads
        sharing rows and capabilities - off obviously hopeless rooms.
        """
        if not room.is_active or not room.room_type.is_active:
            return False
        if room.capacity < requirement.effective_minimum_capacity:
            return False
        required_type_id = requirement.required_room_type_id
        return required_type_id is None or required_type_id == room.room_type_id

    def candidate_rooms(self, requirement) -> list[Room]:
        """Rooms that currently satisfy ``requirement``, via the Phase 5 helper.

        Ownership/sharing, room type, effective capacity and the
        "all required capabilities" rule are all decided by
        ``Room.meets_requirement``; no parallel suitability rule exists here.
        """
        signature = self.requirement_signature(requirement)
        candidates: list[Room] = []
        for room in self.room_pool():
            if not self._may_satisfy_shape(room, requirement):
                continue
            key = (room.pk, signature)
            verdict = self._suitability.get(key)
            if verdict is None:
                verdict = room.meets_requirement(requirement)
                self._suitability[key] = verdict
            if verdict:
                candidates.append(room)
        return candidates
