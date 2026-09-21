"""The analytics service.

One entry point, two callers: the management endpoint passes a version the caller is
allowed to read, and the published endpoint passes the authoritative published
version. Both go through the same loader, the same aggregation and the same JSON
shape, so Phase 15 can import :class:`ScheduleAnalyticsService` and render exports
without touching HTTP.

The service is read-only by construction: it selects rows, reshapes them in memory and
returns value objects. Nothing here calls ``save``, ``update``, ``create`` or
``delete``.
"""

from __future__ import annotations

from django.db.models import Prefetch, Q

from academics.models import Department
from scheduling.models import (
    ScheduleEntry,
    ScheduleEntryInstructor,
    ScheduleEntryStudentGroup,
    ScheduleEntryTimeSlot,
)
from scheduling.services.analytics.domain import (
    EntryFacts,
    GroupFact,
    InstructorFact,
    SnapshotRef,
    VersionAnalytics,
    VersionRef,
)
from scheduling.services.analytics.quality import build_quality
from scheduling.services.analytics.rooms import (
    build_room_usage,
    room_ids,
    weeks_availability_by_room,
)
from scheduling.services.analytics.summary import (
    build_department_load,
    build_department_scope,
    build_student_group_load,
    build_summary,
    group_gaps,
)
from scheduling.services.analytics.workload import (
    build_instructor_workload,
    instructor_gaps,
)
from scheduling.services.validation.time_grid import (
    interval_minutes,
    time_to_minutes,
)


class ScheduleAnalyticsService:
    """Builds one analytics report from one persisted schedule version.

    ``scope`` says how the entry set was narrowed for this caller: a management report
    follows its schedule's own scope, while a published report is narrowed to
    ``DEPARTMENT`` when a department user asked for it, even though the version itself
    is the college-wide one.
    """

    def __init__(self, *, version, department=None, scope: str | None = None) -> None:
        self.version = version
        self.department = department
        self.scope = scope or version.schedule.scope

    # --- construction ------------------------------------------------------

    @classmethod
    def for_version(cls, version) -> "ScheduleAnalyticsService":
        """Analytics of one whole persisted version.

        Used by the management endpoint, whose caller has already been scoped to the
        version, and by Phase 15 exports.
        """
        return cls(version=version, scope=version.schedule.scope)

    @classmethod
    def for_published(cls, schedule, *, department=None) -> "ScheduleAnalyticsService":
        """Analytics of a published version, optionally narrowed to one department.

        The version comes from the schedule's authoritative ``published_version``
        pointer, never from a ``status=PUBLISHED`` query, because earlier publications
        keep that status as history.
        """
        return cls(
            version=schedule.published_version,
            department=department,
            scope="DEPARTMENT" if department is not None else schedule.scope,
        )

    def build(self) -> VersionAnalytics:
        """Compute the report."""
        facts = self._load_facts()
        instructor_gap_totals = instructor_gaps(facts)
        group_gap_totals = group_gaps(facts)
        availability = weeks_availability_by_room(
            semester=self.version.schedule.semester, room_ids=room_ids(facts)
        )
        return VersionAnalytics(
            scope=self.scope,
            version=self._version_ref(),
            summary=build_summary(facts),
            department_load=build_department_load(facts),
            instructor_workload=build_instructor_workload(
                facts, gaps=instructor_gap_totals
            ),
            room_utilization=build_room_usage(
                facts, available_by_room=availability
            ),
            student_group_load=build_student_group_load(
                facts, gaps=group_gap_totals
            ),
            quality=build_quality(
                facts,
                instructor_gaps=instructor_gap_totals,
                group_gaps=group_gap_totals,
            ),
            department_scope=(
                None
                if self.department is None
                else build_department_scope(
                    facts,
                    department=SnapshotRef(
                        id=self.department.pk,
                        code=self.department.code,
                        name=self.department.name,
                    ),
                )
            ),
        )

    # --- loading -----------------------------------------------------------

    def _load_facts(self) -> tuple[EntryFacts, ...]:
        """Reshape the version's entries, and only the allowed ones, into facts.

        A department-scoped report filters the entry set *before* aggregation, so a
        foreign department's sessions never influence a total, a workload or a
        utilization figure. Children are prefetched, so nothing below queries per
        entry.
        """
        queryset = (
            ScheduleEntry.objects.filter(schedule_version=self.version)
            .select_related("teaching_component", "managing_department", "room")
            .prefetch_related(
                Prefetch(
                    "time_slots",
                    queryset=ScheduleEntryTimeSlot.objects.order_by("position"),
                ),
                Prefetch(
                    "instructors",
                    queryset=ScheduleEntryInstructor.objects.order_by("instructor_id"),
                ),
                Prefetch(
                    "student_groups",
                    queryset=ScheduleEntryStudentGroup.objects.order_by(
                        "student_group_id"
                    ),
                ),
            )
            .order_by("id")
        )
        if self.department is not None:
            queryset = queryset.filter(self._department_filter()).distinct()

        return tuple(
            facts
            for facts in (self._entry_facts(entry) for entry in queryset)
            if facts is not None
        )

    def _department_filter(self) -> Q:
        """Entries a department's official report covers.

        The department's own sessions, plus the joint sessions another department
        manages whose persisted student groups belong to it.
        """
        return Q(managing_department=self.department) | Q(
            student_groups__department_id_snapshot=self.department.pk
        )

    @staticmethod
    def _entry_facts(entry) -> EntryFacts | None:
        """One entry as facts, or None when its stored span is unusable."""
        slots = list(entry.time_slots.all())
        duration = 0
        for row in slots:
            interval = interval_minutes(row.start_time_snapshot, row.end_time_snapshot)
            if interval is not None:
                duration += interval[1] - interval[0]
        start_minute = time_to_minutes(entry.start_time)
        end_minute = time_to_minutes(entry.end_time)
        if start_minute is None or end_minute is None or end_minute <= start_minute:
            return None
        if duration <= 0:
            # Without usable period snapshots the stored span is still authoritative
            # for minutes, so the entry is reported rather than dropped.
            duration = end_minute - start_minute

        return EntryFacts(
            entry_id=entry.pk,
            session_id=entry.session_id,
            day_of_week=int(entry.day_of_week),
            start_minute=start_minute,
            end_minute=end_minute,
            duration_minutes=duration,
            penalty=entry.penalty,
            course=SnapshotRef(
                id=entry.course_id_snapshot,
                code=entry.course_code_snapshot,
                name=entry.course_name_snapshot,
            ),
            component_id=entry.teaching_component_id,
            component_type=entry.component_type_snapshot,
            component_label=entry.component_label_snapshot,
            department=SnapshotRef(
                id=entry.managing_department_id,
                code=entry.managing_department_code_snapshot,
                name=entry.managing_department_name_snapshot,
            ),
            room=(
                None
                if entry.room_id is None
                else SnapshotRef(
                    id=entry.room_id,
                    code=entry.room_code_snapshot,
                    name=entry.room_name_snapshot,
                )
            ),
            instructors=tuple(
                InstructorFact(
                    instructor_id=row.instructor_id,
                    full_name=row.full_name_snapshot,
                    assignment_role=row.assignment_role_snapshot or "",
                )
                for row in entry.instructors.all()
            ),
            groups=tuple(
                GroupFact(
                    group_id=row.student_group_id,
                    code=row.code_snapshot,
                    name=row.name_snapshot,
                    department_id=row.department_id_snapshot,
                    department_code=row.department_code_snapshot,
                    department_name=row.department_name_snapshot,
                )
                for row in entry.student_groups.all()
            ),
            slot_ids=tuple(row.time_slot_id for row in slots),
        )

    def _version_ref(self) -> VersionRef:
        """Identity and provenance of the analysed version."""
        schedule = self.version.schedule
        published_by = self.version.published_by
        return VersionRef(
            schedule_id=schedule.pk,
            schedule_scope=schedule.scope,
            semester_id=schedule.semester_id,
            semester_label=str(schedule.semester),
            version_id=self.version.pk,
            version_number=self.version.version_number,
            status=self.version.status,
            source=self.version.source,
            created_at=self.version.created_at,
            published_at=self.version.published_at,
            published_by=(
                None
                if published_by is None
                else {
                    "id": published_by.pk,
                    "username": published_by.get_username(),
                    "role": published_by.role,
                }
            ),
        )


def department_by_id(department_id: int | None) -> Department | None:
    """Load one department by id, or None."""
    if department_id is None:
        return None
    return Department.objects.filter(pk=department_id).first()


def analytics_for_version(version):
    """Convenience wrapper used by the API and by Phase 15."""
    return ScheduleAnalyticsService.for_version(version).build()


__all__ = [
    "ScheduleAnalyticsService",
    "analytics_for_version",
    "department_by_id",
]
