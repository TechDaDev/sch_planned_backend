"""Persisting a generated timetable as one immutable schedule version.

The service is deliberately narrow: it accepts a generation outcome that succeeded
completely, writes one ``ScheduleVersion`` with all of its entries and child
snapshots, and refuses everything else. It never generates, never solves and never
edits an existing version.

Three rules shape the order of work:

* **Verify before writing.** A partial or failed generation must leave zero rows
  behind, so completeness and scope consistency are checked while the database is
  still untouched.
* **Solve outside the transaction.** The CP-SAT run happens in the caller, before
  this service is invoked, so no row lock is ever held for the length of a solve.
* **All or nothing.** The writes for one version share a single short
  ``transaction.atomic()`` block; a failure rolls the whole version back rather
  than leaving a half-written snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from academics.models import StudentGroup
from scheduling.models import (
    Schedule,
    ScheduleEntry,
    ScheduleEntryInstructor,
    ScheduleEntryStudentGroup,
    ScheduleEntryTimeSlot,
    ScheduleScope,
    ScheduleStatus,
    ScheduleVersion,
    ScheduleVersionSource,
    TimeSlot,
)
from scheduling.services.persistence.snapshots import (
    EntrySnapshot,
    build_entry_snapshots,
)

#: Reason reported when a run looked successful but could not be stored whole.
REASON_RESULT_INCOMPLETE = "GENERATION_RESULT_INCOMPLETE"


@dataclass(frozen=True)
class PersistResult:
    """What one persistence attempt produced.

    ``persisted`` is the only success flag: when it is false nothing was written and
    ``reason`` explains why. A rejected attempt carries no schedule and no version,
    not even an empty one.
    """

    persisted: bool
    reason: str | None = None
    message: str = ""
    schedule: Schedule | None = None
    version: ScheduleVersion | None = None
    entry_count: int = 0


class SchedulePersistenceService:
    """Writes one generated timetable into version history.

    The service owns the two invariants the database alone cannot express: a version
    is only written from a complete, in-scope generation result, and a department
    schedule never stores a placement managed by another department.
    """

    def __init__(
        self,
        *,
        semester,
        scope: str,
        department=None,
        created_by=None,
        notes: str = "",
    ) -> None:
        self.semester = semester
        self.scope = scope
        self.department = department
        self.created_by = created_by
        self.notes = notes or ""
        self.source = (
            ScheduleVersionSource.DEPARTMENT_GENERATION
            if scope == ScheduleScope.DEPARTMENT
            else ScheduleVersionSource.COLLEGE_GENERATION
        )

    # --- entry point -------------------------------------------------------

    def persist(self, outcome) -> PersistResult:
        """Store ``outcome`` as a new version, or explain why it was not stored.

        Nothing is written when the run was not a complete success, when a placement
        falls outside the schedule's scope, or when a referenced period no longer
        exists. Every rejection returns before the transaction opens.
        """
        placements = tuple(getattr(outcome, "placements", ()) or ())

        incomplete = self._incomplete_reason(outcome, placements)
        if incomplete is not None:
            return PersistResult(
                persisted=False, reason=REASON_RESULT_INCOMPLETE, message=incomplete
            )

        snapshots = build_entry_snapshots(
            placements, group_departments=self._group_departments(placements)
        )
        mismatch = self._scope_mismatch(snapshots)
        if mismatch is not None:
            return PersistResult(
                persisted=False, reason=REASON_RESULT_INCOMPLETE, message=mismatch
            )

        missing = self._missing_time_slots(snapshots)
        if missing is not None:
            return PersistResult(
                persisted=False, reason=REASON_RESULT_INCOMPLETE, message=missing
            )

        try:
            with transaction.atomic():
                schedule = self._locked_schedule()
                version = self._create_version(schedule, outcome)
                self._write_entries(version, snapshots)
                self._touch(schedule)
        except IntegrityError:
            # The rollback removed the whole version, so a concurrent request can
            # simply try again; the caller sees a controlled rejection, never a 500.
            return PersistResult(
                persisted=False,
                reason=REASON_RESULT_INCOMPLETE,
                message=(
                    "The generated timetable could not be stored as a new version "
                    "because the data it refers to changed during persistence. "
                    "Nothing was written; run the generation again."
                ),
            )

        return PersistResult(
            persisted=True,
            schedule=schedule,
            version=version,
            entry_count=len(snapshots),
        )

    # --- verification ------------------------------------------------------

    def _incomplete_reason(self, outcome, placements) -> str | None:
        """Why this result must not be persisted, or None when it is complete.

        Only a generated result with a proven-or-feasible solve and exactly one
        placement per required session is allowed through. This is the second line of
        defence: the generators already refuse to solve impossible problems, and the
        check here stops a future caller from storing something structurally short.
        """
        if not getattr(outcome, "generated", False):
            return "Only a successfully generated timetable can be persisted."
        solver = getattr(outcome, "solver", None)
        if solver is None or not solver.status.has_placements:
            return "Only an optimal or feasible solve can be persisted."
        expected = getattr(getattr(outcome, "summary", None), "sessions", None)
        if expected is None:
            return "The generation result does not report how many sessions it covers."
        if len(placements) != expected:
            return (
                f"The generation result placed {len(placements)} sessions but the "
                f"timetable requires {expected}."
            )
        session_ids = {placement.session_id for placement in placements}
        if len(session_ids) != len(placements):
            return "The generation result placed one session more than once."
        return None

    def _scope_mismatch(self, snapshots: tuple[EntrySnapshot, ...]) -> str | None:
        """Why these placements do not belong to this schedule, or None.

        A department schedule holds only its own department's components. College
        generation may hold any department's, because that is the scope it was asked
        for.
        """
        if self.scope != ScheduleScope.DEPARTMENT:
            return None
        department_id = self.department.pk if self.department is not None else None
        foreign = sorted(
            {
                snapshot.managing_department.id
                for snapshot in snapshots
                if snapshot.managing_department.id != department_id
            }
        )
        if not foreign:
            return None
        return (
            "A department schedule can only store placements managed by that "
            f"department, but departments {foreign} appeared in the result."
        )

    def _missing_time_slots(self, snapshots: tuple[EntrySnapshot, ...]) -> str | None:
        """Why a referenced period cannot be stored, or None.

        Entries keep a protective foreign key to every period they occupy, so a
        period that disappeared between generation and persistence stops the write
        instead of producing a version that cannot be rendered.
        """
        slot_ids = {
            slot_id for snapshot in snapshots for slot_id in snapshot.time_slot_ids
        }
        if not slot_ids:
            return None
        existing = set(
            TimeSlot.objects.filter(pk__in=slot_ids).values_list("pk", flat=True)
        )
        missing = sorted(slot_ids - existing)
        if not missing:
            return None
        return (
            "The generated timetable refers to teaching periods that no longer "
            f"exist: {missing}. Nothing was written."
        )

    # --- writes ------------------------------------------------------------

    def _locked_schedule(self) -> Schedule:
        """The logical schedule of this semester and scope, locked for allocation.

        Creating it is a race by construction, so the database uniqueness constraint
        decides: ``get_or_create`` retries its lookup when a concurrent request wins.
        The row is then locked so the next version number is read and used atomically
        instead of being computed from a stale read.
        """
        schedule, _ = Schedule.objects.get_or_create(
            semester=self.semester,
            scope=self.scope,
            department=self.department,
            defaults={"created_by": self.created_by},
        )
        return Schedule.objects.select_for_update().get(pk=schedule.pk)

    def _create_version(self, schedule: Schedule, outcome) -> ScheduleVersion:
        """Append the next immutable version, never touching the previous one."""
        latest = schedule.versions.order_by("-version_number").first()
        solver = getattr(outcome, "solver", None)
        return ScheduleVersion.objects.create(
            schedule=schedule,
            version_number=latest.version_number + 1 if latest is not None else 1,
            status=ScheduleStatus.DRAFT,
            source=self.source,
            parent_version=latest,
            created_by=self.created_by,
            notes=self.notes,
            solver_status=solver.status.value if solver is not None else "",
            objective_value=solver.objective_value if solver is not None else None,
            solver_wall_time_seconds=(
                solver.wall_time_seconds if solver is not None else None
            ),
            solver_num_conflicts=(
                solver.num_conflicts if solver is not None else None
            ),
            solver_num_branches=solver.num_branches if solver is not None else None,
            validation_summary=self._validation_summary(outcome),
            generation_summary=self._generation_summary(outcome),
        )

    def _write_entries(
        self, version: ScheduleVersion, snapshots: tuple[EntrySnapshot, ...]
    ) -> None:
        """Write every entry and its snapshot children inside the open transaction.

        Entries are created one by one because each child row needs its parent's
        primary key; the children themselves are inserted in three bulk statements.
        The write volume is the size of one timetable, not of a bulk import, so this
        stays comfortably inside the short transaction.
        """
        for snapshot in snapshots:
            entry = ScheduleEntry.objects.create(
                schedule_version=version,
                session_id=snapshot.session_id,
                candidate_id=snapshot.candidate_id,
                teaching_component_id=snapshot.teaching_component_id,
                managing_department_id=snapshot.managing_department.id,
                session_ordinal=snapshot.session_ordinal,
                day_of_week=snapshot.day_of_week,
                room_id=snapshot.room.id if snapshot.room is not None else None,
                start_time=snapshot.start_time,
                end_time=snapshot.end_time,
                penalty=snapshot.penalty,
                course_id_snapshot=snapshot.course.id,
                course_code_snapshot=snapshot.course.code,
                course_name_snapshot=snapshot.course.name,
                offering_id_snapshot=snapshot.offering.id,
                offering_code_snapshot=snapshot.offering.offering_code,
                component_type_snapshot=snapshot.component_type,
                component_label_snapshot=snapshot.component_label,
                managing_department_code_snapshot=snapshot.managing_department.code,
                managing_department_name_snapshot=snapshot.managing_department.name,
                room_code_snapshot=(
                    snapshot.room.code if snapshot.room is not None else ""
                ),
                room_name_snapshot=(
                    snapshot.room.name if snapshot.room is not None else ""
                ),
            )
            ScheduleEntryTimeSlot.objects.bulk_create(
                [
                    ScheduleEntryTimeSlot(
                        schedule_entry=entry,
                        time_slot_id=slot.time_slot_id,
                        position=slot.position,
                        sequence_snapshot=slot.sequence,
                        label_snapshot=slot.label,
                        start_time_snapshot=slot.start_time,
                        end_time_snapshot=slot.end_time,
                    )
                    for slot in snapshot.time_slots
                ]
            )
            ScheduleEntryInstructor.objects.bulk_create(
                [
                    ScheduleEntryInstructor(
                        schedule_entry=entry,
                        instructor_id=item.instructor_id,
                        assignment_role_snapshot=item.assignment_role,
                        full_name_snapshot=item.full_name,
                    )
                    for item in snapshot.instructors
                ]
            )
            ScheduleEntryStudentGroup.objects.bulk_create(
                [
                    ScheduleEntryStudentGroup(
                        schedule_entry=entry,
                        student_group_id=group.student_group_id,
                        code_snapshot=group.code,
                        name_snapshot=group.name,
                        department_id_snapshot=group.department_id,
                        department_code_snapshot=group.department_code,
                        department_name_snapshot=group.department_name,
                    )
                    for group in snapshot.student_groups
                ]
            )

    @staticmethod
    def _touch(schedule: Schedule) -> None:
        """Record that the logical schedule gained a version.

        The version rows are immutable, so ``updated_at`` on the schedule is the only
        place a client can see that history grew.
        """
        schedule.updated_at = timezone.now()
        schedule.save(update_fields=["updated_at"])

    # --- supporting reads --------------------------------------------------

    def _group_departments(self, placements) -> dict[int, tuple[int | None, str, str]]:
        """Department facts of every student group in one query.

        The generation preview carries a group's own code and name but not its
        department, so the department snapshot is filled here with a single bulk
        lookup instead of a query per group.
        """
        group_ids = {
            group.id for placement in placements for group in placement.student_groups
        }
        if not group_ids:
            return {}
        facts: dict[int, tuple[int | None, str, str]] = {}
        for group in StudentGroup.objects.filter(pk__in=group_ids).select_related(
            "stage__program__department"
        ):
            program = getattr(group.stage, "program", None)
            department = getattr(program, "department", None)
            if department is None:
                facts[group.pk] = (None, "", "")
            else:
                facts[group.pk] = (department.pk, department.code, department.name)
        return facts

    @staticmethod
    def _validation_summary(outcome) -> dict:
        """The validation outcome as plain JSON, never as a dataclass."""
        validation = getattr(outcome, "validation", None)
        summary = getattr(validation, "summary", None)
        return {
            "ready": getattr(validation, "ready", None),
            "scope": getattr(validation, "scope", None),
            "components_checked": getattr(summary, "components_checked", 0),
            "errors": getattr(summary, "errors", 0),
            "warnings": getattr(summary, "warnings", 0),
        }

    @staticmethod
    def _generation_summary(outcome) -> dict:
        """Build counts plus diagnostics of the generation that produced the version."""
        summary = getattr(outcome, "summary", None)
        data = summary.as_dict() if hasattr(summary, "as_dict") else {}
        diagnostics = getattr(outcome, "diagnostics", None)
        if hasattr(diagnostics, "as_dict"):
            data = {**data, "diagnostics": diagnostics.as_dict()}
        return data


__all__ = ["REASON_RESULT_INCOMPLETE", "PersistResult", "SchedulePersistenceService"]
