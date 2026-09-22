"""One typed recorder per audited operation.

These functions own the *shape* of each event: which fields carry the operation, which
metadata is worth keeping and how the semantic target is named. Business services call the
recorder that matches what they just committed, so no service has to remember the model's
column layout - and no service invents a new action name.

Each recorder is called from inside the transaction that performed the mutation. If the
record fails, the mutation fails with it.
"""

from __future__ import annotations

from typing import Any, Mapping

from scheduling.models import AuditAction, AuditEvent, ScheduleScope
from scheduling.services.audit.service import AuditService

#: Object type of a generated or edited version.
OBJECT_SCHEDULE_VERSION = "ScheduleVersion"

#: Object type of an imported teaching plan; its id names the department and semester,
#: because the import creates many rows and has no single row to point at.
OBJECT_SEMESTER_PLAN_IMPORT = "SemesterPlanImport"


def record_department_draft(
    *,
    actor,
    semester,
    schedule,
    schedule_version,
    entry_count: int,
    source: str,
    department=None,
    solver_status: str | None = None,
    solver_wall_time_seconds: float | None = None,
    base_version_id: int | None = None,
) -> AuditEvent:
    """A department draft generation that was stored as a new version."""
    return AuditService.record(
        action=AuditAction.DEPARTMENT_DRAFT_GENERATED,
        actor=actor,
        department=department or schedule.department,
        semester=semester,
        schedule=schedule,
        schedule_version=schedule_version,
        object_type=OBJECT_SCHEDULE_VERSION,
        object_id=schedule_version.pk,
        metadata={
            "version_number": schedule_version.version_number,
            "entry_count": entry_count,
            "source": source,
            "scope": ScheduleScope.DEPARTMENT,
            "solver_status": solver_status,
            "solver_wall_time_seconds": solver_wall_time_seconds,
            "base_version_id": base_version_id,
        },
    )


def record_college_draft(
    *,
    actor,
    semester,
    schedule,
    schedule_version,
    entry_count: int,
    source: str,
    department_count: int | None = None,
    solver_status: str | None = None,
    solver_wall_time_seconds: float | None = None,
    base_version_id: int | None = None,
) -> AuditEvent:
    """A college-wide draft generation that was stored as a new version.

    No department is stored: the operation covers every department, and attributing it to
    one of them would leak a college-level action into that department's audit view.
    """
    return AuditService.record(
        action=AuditAction.COLLEGE_DRAFT_GENERATED,
        actor=actor,
        department=None,
        semester=semester,
        schedule=schedule,
        schedule_version=schedule_version,
        object_type=OBJECT_SCHEDULE_VERSION,
        object_id=schedule_version.pk,
        metadata={
            "version_number": schedule_version.version_number,
            "entry_count": entry_count,
            "department_count": department_count,
            "source": source,
            "scope": ScheduleScope.COLLEGE,
            "solver_status": solver_status,
            "solver_wall_time_seconds": solver_wall_time_seconds,
            "base_version_id": base_version_id,
        },
    )


def record_manual_edit(
    *,
    actor,
    version,
    base_version_id: int,
    entry_count: int,
    changed_entries: int,
) -> AuditEvent:
    """A manual edit that was stored as the schedule's next version.

    Only counts are kept: the proposed changes themselves are not an audit concern, and
    storing them would duplicate version history into the trail.
    """
    schedule = version.schedule
    return AuditService.record(
        action=AuditAction.MANUAL_EDIT_APPLIED,
        actor=actor,
        department=schedule.department,
        semester=schedule.semester,
        schedule=schedule,
        schedule_version=version,
        object_type=OBJECT_SCHEDULE_VERSION,
        object_id=version.pk,
        metadata={
            "base_version_id": base_version_id,
            "new_version_id": version.pk,
            "new_version_number": version.version_number,
            "changed_entries": changed_entries,
            "total_entries": entry_count,
        },
    )


def record_workflow_transition(
    *,
    actor,
    version,
    from_status: str,
    to_status: str,
    became_authoritative: bool = False,
) -> AuditEvent:
    """One successful workflow stage change, including publication."""
    schedule = version.schedule
    return AuditService.record(
        action=_WORKFLOW_ACTIONS[to_status],
        actor=actor,
        department=schedule.department,
        semester=schedule.semester,
        schedule=schedule,
        schedule_version=version,
        object_type=OBJECT_SCHEDULE_VERSION,
        object_id=version.pk,
        metadata={
            "from_status": from_status,
            "to_status": to_status,
            "version_number": version.version_number,
            "became_authoritative": became_authoritative,
        },
    )


def record_semester_plan_import(
    *,
    actor,
    department,
    semester,
    created: Mapping[str, Any],
    warning_count: int,
) -> AuditEvent:
    """One applied semester teaching plan import.

    The workbook itself is not an audit artefact: no bytes, no file name, no sheet
    contents. The created counts and the warning count describe what changed.
    """
    return AuditService.record(
        action=AuditAction.SEMESTER_PLAN_IMPORTED,
        actor=actor,
        department=department,
        semester=semester,
        object_type=OBJECT_SEMESTER_PLAN_IMPORT,
        object_id=f"department:{department.pk}:semester:{semester.pk}",
        metadata={
            "created": dict(created),
            "created_total": sum(int(value) for value in created.values()),
            "warning_count": warning_count,
        },
    )


#: Which action name each workflow destination status records.
_WORKFLOW_ACTIONS = {
    "SUBMITTED": AuditAction.SCHEDULE_SUBMITTED,
    "REVIEWED": AuditAction.SCHEDULE_REVIEWED,
    "APPROVED": AuditAction.SCHEDULE_APPROVED,
    "PUBLISHED": AuditAction.SCHEDULE_PUBLISHED,
}


__all__ = [
    "OBJECT_SCHEDULE_VERSION",
    "OBJECT_SEMESTER_PLAN_IMPORT",
    "record_college_draft",
    "record_department_draft",
    "record_manual_edit",
    "record_semester_plan_import",
    "record_workflow_transition",
]
