"""Mapping solver placements onto preview rows.

A preview row is a flat, human-readable description of one scheduled session: what
it is, when it happens, where, and who is involved. Everything it needs was already
loaded while building the problem, so no query runs here and no Django object
appears in the result.

Only resources that participate in the generated problem are described, which keeps
a preview from leaking another department's catalogue: a department preview cannot
name a foreign instructor, while a college preview legitimately covers the whole
college because that is what it was asked to schedule.
"""

from __future__ import annotations

from academics.models import Weekday
from scheduling.services.generation.domain import (
    PlacementInstructor,
    PreviewPlacement,
    ProblemBundle,
    SlotInfo,
)
from scheduling.services.solver import ScheduledPlacement


def session_ordinal(session_id: str) -> int:
    """Numeric ordinal of a ``component:<id>:session:<ordinal>`` identifier.

    Used only for ordering. An identifier that does not follow the convention sorts
    first rather than raising, so a future identifier shape cannot break a preview.
    """
    _, _, tail = session_id.rpartition(":")
    try:
        return int(tail)
    except ValueError:
        return 0


class PreviewBuilder:
    """Turns engine placements into preview rows using a built problem bundle."""

    def __init__(self, bundle: ProblemBundle) -> None:
        self._bundle = bundle

    def build(
        self, placements: tuple[ScheduledPlacement, ...]
    ) -> tuple[PreviewPlacement, ...]:
        """Preview rows for ``placements``, ordered as the engine returned them."""
        previews: list[PreviewPlacement] = []
        for placement in placements:
            # The bundle creates a context for every session that can be scheduled,
            # so a missing one is unreachable by construction; skipping keeps a
            # programming slip from ever surfacing as a server error.
            context = self._bundle.session_context.get(placement.session_id)
            if context is None:
                continue
            slots = self._slots(placement.slot_ids)
            previews.append(
                PreviewPlacement(
                    session_id=placement.session_id,
                    course=context.component.course,
                    offering=context.component.offering,
                    teaching_component=context.component,
                    day_of_week=placement.day_of_week,
                    day_display=self._day_display(placement.day_of_week),
                    slots=slots,
                    start_time=slots[0].start_time if slots else "",
                    end_time=slots[-1].end_time if slots else "",
                    room=self._bundle.room_map.get(placement.room_id),
                    instructors=tuple(
                        PlacementInstructor(
                            instructor=self._bundle.instructor_map[instructor_id],
                            assignment_role=context.assignment_roles.get(instructor_id),
                        )
                        for instructor_id in placement.instructor_ids
                        if instructor_id in self._bundle.instructor_map
                    ),
                    student_groups=tuple(
                        self._bundle.group_map[group_id]
                        for group_id in placement.student_group_ids
                        if group_id in self._bundle.group_map
                    ),
                    penalty=placement.penalty,
                    managing_department=context.component.managing_department,
                    raw=placement,
                )
            )
        return tuple(previews)

    def _slots(self, slot_ids: tuple[int, ...]) -> tuple[SlotInfo, ...]:
        """Selected periods in timetable order, ignoring unknown ids."""
        selected = [
            self._bundle.slot_map[slot_id]
            for slot_id in slot_ids
            if slot_id in self._bundle.slot_map
        ]
        selected.sort(key=lambda slot: (slot.start_time, slot.sequence, slot.id))
        return tuple(selected)

    @staticmethod
    def _day_display(day_of_week: int) -> str:
        """Human label of a weekday, falling back to the raw number."""
        try:
            return Weekday(day_of_week).label
        except ValueError:
            return str(day_of_week)


class CollegePreviewBuilder(PreviewBuilder):
    """Preview rows of a college-wide solve, in a documented stable order.

    The engine's own order is already deterministic but groups by day rather than
    by department. A college preview is far more readable grouped per managing
    department, so rows are re-sorted by department code, weekday, first period,
    course code, component id and session ordinal - all values that come straight
    from stored data, so the order repeats exactly on an unchanged database.
    """

    def build(
        self, placements: tuple[ScheduledPlacement, ...]
    ) -> tuple[PreviewPlacement, ...]:
        previews = super().build(placements)
        return tuple(
            sorted(
                previews,
                key=lambda preview: (
                    (
                        preview.managing_department.code,
                        preview.managing_department.id,
                    )
                    if preview.managing_department is not None
                    else ("", 0),
                    preview.day_of_week,
                    preview.start_time,
                    preview.course.code,
                    preview.teaching_component.id,
                    session_ordinal(preview.session_id),
                ),
            )
        )


__all__ = ["CollegePreviewBuilder", "PreviewBuilder", "session_ordinal"]
