"""Read-only structural verification of the operational database.

This answers one question: *is the stored data internally consistent?* It checks the
things the schema cannot express - that the publication pointer points at a published
version of its own schedule, that version numbers and lineage form one chain, that every
stored entry has its periods, instructors and groups, and that nothing duplicated a session
identifier.

It deliberately does **not** answer whether a timetable is still feasible. Current
feasibility is Phase 13's ``WorkflowVersionValidator``, which re-checks instructor
availability, room suitability and component hours against today's configuration. Mixing
the two would mean an integrity command that starts failing when a teaching assignment
changes, which is not corruption.

Nothing is repaired here. Not one row is updated, deleted or reparented: the command
detects and reports, and a human decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Count, F, Max, Min, Q

from scheduling.models import (
    Schedule,
    ScheduleEntry,
    ScheduleEntryTimeSlot,
    ScheduleScope,
    ScheduleStatus,
    ScheduleVersion,
)

#: Stable issue codes. An operator (or a monitoring rule) can rely on these strings.
DATABASE_CONNECTIVITY_FAILED = "DATABASE_CONNECTIVITY_FAILED"
UNAPPLIED_MIGRATIONS = "UNAPPLIED_MIGRATIONS"
MIGRATION_GRAPH_INCONSISTENT = "MIGRATION_GRAPH_INCONSISTENT"
INVALID_PUBLISHED_POINTER = "INVALID_PUBLISHED_POINTER"
VERSION_NUMBER_SEQUENCE_INVALID = "VERSION_NUMBER_SEQUENCE_INVALID"
VERSION_PARENT_LINEAGE_INVALID = "VERSION_PARENT_LINEAGE_INVALID"
ENTRY_WITHOUT_TIME_SLOTS = "ENTRY_WITHOUT_TIME_SLOTS"
ENTRY_WITHOUT_INSTRUCTORS = "ENTRY_WITHOUT_INSTRUCTORS"
ENTRY_WITHOUT_STUDENT_GROUPS = "ENTRY_WITHOUT_STUDENT_GROUPS"
ENTRY_TIME_RANGE_INVALID = "ENTRY_TIME_RANGE_INVALID"
ENTRY_SLOT_POSITION_INVALID = "ENTRY_SLOT_POSITION_INVALID"
DUPLICATE_SESSION_ID = "DUPLICATE_SESSION_ID"
DUPLICATE_SESSION_ORDINAL = "DUPLICATE_SESSION_ORDINAL"


@dataclass(frozen=True)
class IntegrityIssue:
    """One detected inconsistency."""

    code: str
    object_type: str
    object_id: Any
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "object": self.object_type,
            "object_id": self.object_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class IntegrityReport:
    """The outcome of one integrity pass."""

    checks: dict[str, Any] = field(default_factory=dict)
    issues: tuple[IntegrityIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": dict(self.checks),
            "issues": [issue.as_dict() for issue in self.issues],
        }

    def summary_lines(self) -> tuple[str, ...]:
        """Concise operator output: one line per check, then one per issue."""
        lines = [
            f"{name}: {_format_check(value)}" for name, value in self.checks.items()
        ]
        if not self.issues:
            lines.append("result: ok - no structural inconsistency found")
            return tuple(lines)
        lines.append(f"result: {len(self.issues)} issue(s) found")
        for issue in self.issues:
            lines.append(
                f"  [{issue.code}] {issue.object_type} {issue.object_id}: {issue.message}"
            )
        return tuple(lines)


def _format_check(value: Any) -> str:
    if isinstance(value, bool):
        return "ok" if value else "FAILED"
    return str(value)


def run_integrity_checks() -> IntegrityReport:
    """Run every structural check and collect what is wrong.

    Read-only: the only database calls are SELECTs.
    """
    checks: dict[str, Any] = {}
    issues: list[IntegrityIssue] = []

    if not _check_connectivity(checks, issues):
        return IntegrityReport(checks=checks, issues=tuple(issues))

    _check_migrations(checks, issues)
    _check_published_pointers(checks, issues)
    _check_version_history(checks, issues)
    _check_entries(checks, issues)
    return IntegrityReport(checks=checks, issues=tuple(issues))


def _check_connectivity(
    checks: dict[str, Any], issues: list[IntegrityIssue]
) -> bool:
    """Confirm the database answers before anything else is queried."""
    from django.db import DatabaseError

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        checks["database_connectivity"] = False
        issues.append(
            IntegrityIssue(
                code=DATABASE_CONNECTIVITY_FAILED,
                object_type="Database",
                object_id="default",
                message=f"The database did not answer: {exc}",
            )
        )
        return False
    checks["database_connectivity"] = True
    return True


# --- migrations ----------------------------------------------------------------


def _check_migrations(checks: dict[str, Any], issues: list[IntegrityIssue]) -> None:
    """Every project migration is applied, and no applied row is unknown.

    Migrations are never run from here: a missing migration is reported, and applying it
    stays an explicit operator decision.
    """
    connection = connections["default"]
    applied = MigrationRecorder(connection).applied_migrations()
    loader = MigrationExecutor(connection).loader
    graph_nodes = set(loader.graph.nodes)

    unapplied = sorted(node for node in graph_nodes if node not in applied)
    checks["applied_migrations"] = len(applied)
    checks["unapplied_migrations"] = len(unapplied)
    if unapplied:
        issues.append(
            IntegrityIssue(
                code=UNAPPLIED_MIGRATIONS,
                object_type="Migration",
                object_id=", ".join(f"{app}.{name}" for app, name in unapplied),
                message=(
                    f"{len(unapplied)} project migration(s) are not applied to this "
                    "database. Run 'manage.py migrate' deliberately; this check never "
                    "applies anything."
                ),
            )
        )

    unknown = sorted(node for node in applied if node not in graph_nodes)
    checks["unknown_applied_migrations"] = len(unknown)
    if unknown:
        issues.append(
            IntegrityIssue(
                code=MIGRATION_GRAPH_INCONSISTENT,
                object_type="Migration",
                object_id=", ".join(f"{app}.{name}" for app, name in unknown),
                message=(
                    "The database records migrations that no longer exist in the project, "
                    "so the schema and the code have diverged."
                ),
            )
        )


# --- publication ---------------------------------------------------------------


def _check_published_pointers(
    checks: dict[str, Any], issues: list[IntegrityIssue]
) -> None:
    """Each publication pointer names a published version of its own college schedule."""
    schedules = Schedule.objects.filter(published_version__isnull=False).select_related(
        "published_version"
    )
    checked = 0
    for schedule in schedules:
        checked += 1
        version = schedule.published_version
        problems: list[str] = []
        if version is None:
            problems.append("the pointer names a version that no longer exists")
        else:
            if version.schedule_id != schedule.pk:
                problems.append(
                    f"version {version.pk} belongs to schedule {version.schedule_id}"
                )
            if version.status != ScheduleStatus.PUBLISHED:
                problems.append(
                    f"version {version.pk} has status {version.status}, not PUBLISHED"
                )
        if schedule.scope != ScheduleScope.COLLEGE:
            problems.append(
                f"schedule {schedule.pk} has scope {schedule.scope}, and only a college "
                "schedule may publish an official timetable"
            )
        if problems:
            issues.append(
                IntegrityIssue(
                    code=INVALID_PUBLISHED_POINTER,
                    object_type="Schedule",
                    object_id=schedule.pk,
                    message="; ".join(problems) + ".",
                )
            )
    checks["published_pointers_checked"] = checked


# --- version history -----------------------------------------------------------


def _check_version_history(
    checks: dict[str, Any], issues: list[IntegrityIssue]
) -> None:
    """Version numbers form 1..n once per schedule and lineage is a single chain."""
    rows = list(
        ScheduleVersion.objects.order_by("schedule_id", "version_number").values(
            "id", "schedule_id", "version_number", "parent_version_id", "status"
        )
    )
    per_schedule: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        per_schedule.setdefault(row["schedule_id"], []).append(row)

    checked = 0
    for schedule_id, versions in per_schedule.items():
        checked += len(versions)
        numbers = [version["version_number"] for version in versions]
        expected = list(range(1, len(numbers) + 1))
        if numbers != expected:
            issues.append(
                IntegrityIssue(
                    code=VERSION_NUMBER_SEQUENCE_INVALID,
                    object_type="Schedule",
                    object_id=schedule_id,
                    message=(
                        "Version numbers must start at 1 and stay contiguous; this "
                        f"schedule has {numbers}. Historical PUBLISHED versions are "
                        "allowed, gaps and duplicates are not."
                    ),
                )
            )
            # Lineage cannot be judged on a broken numbering, so report it separately and
            # move on rather than producing derived noise.
            continue

        by_number = {version["version_number"]: version for version in versions}
        for version in versions:
            number = version["version_number"]
            parent_id = version["parent_version_id"]
            if number == 1:
                if parent_id is not None:
                    issues.append(
                        IntegrityIssue(
                            code=VERSION_PARENT_LINEAGE_INVALID,
                            object_type="ScheduleVersion",
                            object_id=version["id"],
                            message=(
                                "The first version of a schedule must have no parent, but "
                                f"it names version {parent_id}."
                            ),
                        )
                    )
                continue
            previous = by_number[number - 1]
            if parent_id != previous["id"]:
                issues.append(
                    IntegrityIssue(
                        code=VERSION_PARENT_LINEAGE_INVALID,
                        object_type="ScheduleVersion",
                        object_id=version["id"],
                        message=(
                            f"Version {number} must have version {number - 1} "
                            f"(id {previous['id']}) as its parent, but it names "
                            f"{parent_id}."
                        ),
                    )
                )
    checks["versions_checked"] = checked


# --- entries -------------------------------------------------------------------


def _check_entries(checks: dict[str, Any], issues: list[IntegrityIssue]) -> None:
    """Every stored entry is complete, ordered and uniquely identified."""
    entries = (
        ScheduleEntry.objects.annotate(
            slot_rows=Count("time_slots", distinct=True),
            instructor_rows=Count("instructors", distinct=True),
            group_rows=Count("student_groups", distinct=True),
        )
        .values(
            "id",
            "schedule_version_id",
            "session_id",
            "start_time",
            "end_time",
            "slot_rows",
            "instructor_rows",
            "group_rows",
        )
        .order_by("id")
    )

    checked = 0
    for entry in entries:
        checked += 1
        if entry["slot_rows"] == 0:
            issues.append(
                IntegrityIssue(
                    code=ENTRY_WITHOUT_TIME_SLOTS,
                    object_type="ScheduleEntry",
                    object_id=entry["id"],
                    message="This stored session occupies no teaching period.",
                )
            )
        if entry["instructor_rows"] == 0:
            issues.append(
                IntegrityIssue(
                    code=ENTRY_WITHOUT_INSTRUCTORS,
                    object_type="ScheduleEntry",
                    object_id=entry["id"],
                    message="This stored session has no instructor.",
                )
            )
        if entry["group_rows"] == 0:
            issues.append(
                IntegrityIssue(
                    code=ENTRY_WITHOUT_STUDENT_GROUPS,
                    object_type="ScheduleEntry",
                    object_id=entry["id"],
                    message="This stored session has no student group.",
                )
            )
        if entry["start_time"] is not None and entry["end_time"] is not None:
            if entry["start_time"] >= entry["end_time"]:
                issues.append(
                    IntegrityIssue(
                        code=ENTRY_TIME_RANGE_INVALID,
                        object_type="ScheduleEntry",
                        object_id=entry["id"],
                        message=(
                            f"The stored span {entry['start_time']}-{entry['end_time']} "
                            "does not end after it starts."
                        ),
                    )
                )
    checks["entries_checked"] = checked

    _check_entry_slot_positions(checks, issues)
    _check_duplicate_sessions(checks, issues)


def _check_entry_slot_positions(
    checks: dict[str, Any], issues: list[IntegrityIssue]
) -> None:
    """One entry's periods are numbered 1..n, without gaps or repeats."""
    rows = (
        ScheduleEntryTimeSlot.objects.values("schedule_entry_id")
        .annotate(
            rows=Count("id"),
            distinct_positions=Count("position", distinct=True),
            lowest=Min("position"),
            highest=Max("position"),
        )
        .order_by("schedule_entry_id")
    )
    checked = 0
    for row in rows:
        checked += 1
        if (
            row["lowest"] != 1
            or row["highest"] != row["rows"]
            or row["distinct_positions"] != row["rows"]
        ):
            issues.append(
                IntegrityIssue(
                    code=ENTRY_SLOT_POSITION_INVALID,
                    object_type="ScheduleEntry",
                    object_id=row["schedule_entry_id"],
                    message=(
                        "Period positions must be 1..n with no duplicates; this entry has "
                        f"{row['rows']} row(s) spanning {row['lowest']}..{row['highest']} "
                        f"with {row['distinct_positions']} distinct position(s)."
                    ),
                )
            )
    checks["entry_slot_groups_checked"] = checked


def _check_duplicate_sessions(
    checks: dict[str, Any], issues: list[IntegrityIssue]
) -> None:
    """No version repeats a session id or a component/session ordinal.

    The database constraints should already prevent both; this check exists precisely for
    the case they were bypassed outside the application.
    """
    duplicate_ids = (
        ScheduleEntry.objects.values("schedule_version_id", "session_id")
        .annotate(rows=Count("id"))
        .filter(rows__gt=1)
        .order_by("schedule_version_id", "session_id")
    )
    duplicates = 0
    for row in duplicate_ids:
        duplicates += 1
        issues.append(
            IntegrityIssue(
                code=DUPLICATE_SESSION_ID,
                object_type="ScheduleVersion",
                object_id=row["schedule_version_id"],
                message=(
                    f"Session id '{row['session_id']}' appears {row['rows']} times in this "
                    "version."
                ),
            )
        )
    checks["duplicate_session_ids"] = duplicates

    duplicate_ordinals = (
        ScheduleEntry.objects.values(
            "schedule_version_id", "teaching_component_id", "session_ordinal"
        )
        .annotate(rows=Count("id"))
        .filter(rows__gt=1)
        .order_by("schedule_version_id", "teaching_component_id", "session_ordinal")
    )
    ordinals = 0
    for row in duplicate_ordinals:
        ordinals += 1
        issues.append(
            IntegrityIssue(
                code=DUPLICATE_SESSION_ORDINAL,
                object_type="ScheduleVersion",
                object_id=row["schedule_version_id"],
                message=(
                    "Teaching component "
                    f"{row['teaching_component_id']} session ordinal "
                    f"{row['session_ordinal']} appears {row['rows']} times in this version."
                ),
            )
        )
    checks["duplicate_session_ordinals"] = ordinals


__all__ = [
    "DATABASE_CONNECTIVITY_FAILED",
    "DUPLICATE_SESSION_ID",
    "DUPLICATE_SESSION_ORDINAL",
    "ENTRY_SLOT_POSITION_INVALID",
    "ENTRY_TIME_RANGE_INVALID",
    "ENTRY_WITHOUT_INSTRUCTORS",
    "ENTRY_WITHOUT_STUDENT_GROUPS",
    "ENTRY_WITHOUT_TIME_SLOTS",
    "INVALID_PUBLISHED_POINTER",
    "MIGRATION_GRAPH_INCONSISTENT",
    "UNAPPLIED_MIGRATIONS",
    "VERSION_NUMBER_SEQUENCE_INVALID",
    "VERSION_PARENT_LINEAGE_INVALID",
    "IntegrityIssue",
    "IntegrityReport",
    "run_integrity_checks",
]
