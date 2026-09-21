"""Copy-on-write creation of a manually edited version.

A manual version is a complete timetable, never a delta. Every entry of the base
version is cloned, so each version stays independently readable, and the three child
tables are copied row by row. Only a changed entry has its placement replaced:

* placement fields — weekday, periods, room, the room snapshots, the derived start
  and end, the manual candidate id and the recomputed penalty — come from the
  request;
* everything historical — session id, ordinal, component, managing department,
  course/offering/component/department snapshots, instructor rows and student-group
  rows — is copied from the base version and never re-read from today's models.

The base version is never touched: it is immutable, and this step only reads it.
"""

from __future__ import annotations

from django.utils import timezone

from resources.models import Room
from scheduling.models import (
    Schedule,
    ScheduleEntry,
    ScheduleEntryInstructor,
    ScheduleEntryStudentGroup,
    ScheduleEntryTimeSlot,
    ScheduleStatus,
    ScheduleVersion,
    ScheduleVersionSource,
)
from scheduling.services.manual_edit.domain import ProposedEntry, ProposedVersion


def clone_version(
    *,
    proposal: ProposedVersion,
    created_by=None,
    notes: str = "",
) -> ScheduleVersion:
    """Write the proposed timetable as the schedule's next version.

    The caller owns the transaction and the schedule lock: the next version number is
    read here, so this must run while the schedule row is locked.
    """
    base = proposal.base_version
    schedule = base.schedule
    latest = schedule.versions.order_by("-version_number").first()

    version = ScheduleVersion.objects.create(
        schedule=schedule,
        version_number=latest.version_number + 1 if latest is not None else 1,
        status=ScheduleStatus.DRAFT,
        source=ScheduleVersionSource.MANUAL_EDIT,
        parent_version=base,
        created_by=created_by,
        notes=notes or "",
        # No solver produced this timetable, so no solver metadata is recorded.
        solver_status=None,
        objective_value=None,
        solver_wall_time_seconds=None,
        solver_num_conflicts=None,
        solver_num_branches=None,
        validation_summary={
            "manual_edit": True,
            "base_version": base.pk,
            "changed_entries": proposal.changed_entry_count,
            "validation_errors": 0,
        },
        generation_summary={
            "manual_edit": True,
            "source_version_number": base.version_number,
            "entries": proposal.entry_count,
            "changed_entries": proposal.changed_entry_count,
        },
    )

    target_rooms = _target_rooms(proposal)
    for proposed in proposal.entries:
        _clone_entry(version=version, proposed=proposed, target_rooms=target_rooms)

    _touch(schedule)
    return version


def _target_rooms(proposal: ProposedVersion) -> dict[int, Room]:
    """The rooms new placements refer to, loaded in one query.

    Only their display values are needed, because the room snapshot must describe the
    room as it is now, at the moment of the edit.
    """
    room_ids = {
        proposed.placement.room_id
        for proposed in proposal.entries
        if proposed.placement.changed and proposed.placement.room_id is not None
    }
    if not room_ids:
        return {}
    return {
        room.pk: room for room in Room.objects.filter(pk__in=room_ids)
    }


def _clone_entry(
    *,
    version: ScheduleVersion,
    proposed: ProposedEntry,
    target_rooms: dict[int, Room],
) -> None:
    """Clone one entry, replacing its placement when the user changed it."""
    entry = proposed.entry
    placement = proposed.placement

    if placement.changed:
        room = target_rooms.get(placement.room_id) if placement.room_id else None
        day_of_week = placement.day_of_week
        start_time = placement.start_time
        end_time = placement.end_time
        room_id = placement.room_id
        room_code = room.code if room is not None else ""
        room_name = room.name if room is not None else ""
    else:
        day_of_week = entry.day_of_week
        start_time = entry.start_time
        end_time = entry.end_time
        room_id = entry.room_id
        room_code = entry.room_code_snapshot
        room_name = entry.room_name_snapshot

    cloned = ScheduleEntry.objects.create(
        schedule_version=version,
        session_id=entry.session_id,
        candidate_id=proposed.candidate_id,
        teaching_component_id=entry.teaching_component_id,
        managing_department_id=entry.managing_department_id,
        session_ordinal=entry.session_ordinal,
        day_of_week=day_of_week,
        room_id=room_id,
        start_time=start_time,
        end_time=end_time,
        penalty=proposed.penalty,
        # Historical display values are copied, never re-derived from live models.
        course_id_snapshot=entry.course_id_snapshot,
        course_code_snapshot=entry.course_code_snapshot,
        course_name_snapshot=entry.course_name_snapshot,
        offering_id_snapshot=entry.offering_id_snapshot,
        offering_code_snapshot=entry.offering_code_snapshot,
        component_type_snapshot=entry.component_type_snapshot,
        component_label_snapshot=entry.component_label_snapshot,
        managing_department_code_snapshot=entry.managing_department_code_snapshot,
        managing_department_name_snapshot=entry.managing_department_name_snapshot,
        room_code_snapshot=room_code,
        room_name_snapshot=room_name,
    )

    ScheduleEntryTimeSlot.objects.bulk_create(
        [
            ScheduleEntryTimeSlot(
                schedule_entry=cloned,
                time_slot_id=slot.time_slot_id,
                position=slot.position,
                sequence_snapshot=slot.sequence,
                label_snapshot=slot.label,
                start_time_snapshot=slot.start_time,
                end_time_snapshot=slot.end_time,
            )
            for slot in proposed.slot_snapshots
        ]
    )
    ScheduleEntryInstructor.objects.bulk_create(
        [
            ScheduleEntryInstructor(
                schedule_entry=cloned,
                instructor_id=row.instructor_id,
                assignment_role_snapshot=row.assignment_role_snapshot,
                full_name_snapshot=row.full_name_snapshot,
            )
            for row in entry.instructors.all()
        ]
    )
    ScheduleEntryStudentGroup.objects.bulk_create(
        [
            ScheduleEntryStudentGroup(
                schedule_entry=cloned,
                student_group_id=row.student_group_id,
                code_snapshot=row.code_snapshot,
                name_snapshot=row.name_snapshot,
                department_id_snapshot=row.department_id_snapshot,
                department_code_snapshot=row.department_code_snapshot,
                department_name_snapshot=row.department_name_snapshot,
            )
            for row in entry.student_groups.all()
        ]
    )


def _touch(schedule: Schedule) -> None:
    """Record that the logical schedule gained a version."""
    schedule.updated_at = timezone.now()
    schedule.save(update_fields=["updated_at"])


__all__ = ["clone_version"]
