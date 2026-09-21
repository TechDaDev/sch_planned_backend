"""Tabular projections of a Phase 14 report, shared by the Excel and PDF renderers.

Every value here is copied from :class:`~scheduling.services.analytics.domain.VersionAnalytics`
or from the export document's metadata. Nothing is recomputed, and nothing is fetched:
a projection is a pure reshape of an in-memory report, which is what keeps the
workbook, the PDF and the analytics endpoint from ever disagreeing.

Cells are primitives - ``str``, ``int``, ``float`` or ``None`` for a genuinely absent
value such as a room denominator that current configuration cannot supply. Each
renderer decides how to display them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scheduling.services.analytics import VersionAnalytics

from scheduling.services.exports.domain import ExportDocument


@dataclass(frozen=True)
class Table:
    """Headers plus rows of primitive cells."""

    headers: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def metadata_table(document: ExportDocument) -> Table:
    """Document metadata as a two-column block."""
    return Table(("Field", "Value"), document.metadata.as_rows())


def summary_table(report: VersionAnalytics) -> Table:
    """Headline counts of the analysed entry set, straight from Phase 14."""
    summary = report.summary
    rows: tuple[tuple[Any, ...], ...] = (
        ("Sessions", summary.session_count),
        ("Entries", summary.entry_count),
        ("Scheduled minutes", summary.scheduled_minutes),
        ("Scheduled hours", summary.scheduled_hours),
        ("Courses", summary.unique_courses),
        ("Teaching components", summary.unique_teaching_components),
        ("Departments", summary.unique_departments),
        ("Instructors", summary.unique_instructors),
        ("Rooms", summary.unique_rooms),
        ("Student groups", summary.unique_student_groups),
        ("Days used", summary.days_used),
    )
    return Table(("Metric", "Value"), rows)


def department_scope_table(report: VersionAnalytics) -> Table:
    """Managed versus participating sessions of a department-scoped report."""
    scope = report.department_scope
    rows: tuple[tuple[Any, ...], ...] = ()
    if scope is not None:
        rows = (
            ("Department", _label(scope.department.code, scope.department.name)),
            ("Managed sessions", scope.managed_session_count),
            ("Managed minutes", scope.managed_minutes),
            ("Managed hours", scope.managed_hours),
            ("Participating sessions", scope.participating_session_count),
            ("Participating minutes", scope.participating_minutes),
            ("Participating hours", scope.participating_hours),
            ("Visible sessions", scope.total_visible_session_count),
        )
    return Table(("Metric", "Value"), rows)


def department_load_table(report: VersionAnalytics) -> Table:
    """Scheduled load per managing department."""
    headers = (
        "Department",
        "Components",
        "Sessions",
        "Scheduled Minutes",
        "Scheduled Hours",
        "Courses",
        "Instructors",
        "Rooms",
        "Student Groups",
        "Joint Sessions",
    )
    rows = tuple(
        (
            _label(row.department.code, row.department.name),
            row.component_count,
            row.session_count,
            row.scheduled_minutes,
            row.scheduled_hours,
            row.unique_courses,
            row.unique_instructors,
            row.unique_rooms,
            row.unique_student_groups,
            row.joint_session_count,
        )
        for row in report.department_load
    )
    return Table(headers, rows)


def instructor_workload_table(report: VersionAnalytics) -> Table:
    """Scheduled load per instructor, merged across departments."""
    headers = (
        "Instructor",
        "Sessions",
        "Primary",
        "Assistant",
        "Scheduled Minutes",
        "Scheduled Hours",
        "Active Days",
        "Max Daily Minutes",
        "Max Daily Hours",
        "Departments",
        "Total Gap Minutes",
        "Max Gap Minutes",
        "Avg Gap Per Active Day",
    )
    rows = tuple(
        (
            row.instructor.name,
            row.session_count,
            row.primary_session_count,
            row.assistant_session_count,
            row.scheduled_minutes,
            row.scheduled_hours,
            row.days_used,
            row.max_daily_scheduled_minutes,
            row.max_daily_scheduled_hours,
            ", ".join(row.department_codes),
            row.total_gap_minutes,
            row.max_gap_minutes,
            row.average_gap_minutes_per_active_day,
        )
        for row in report.instructor_workload
    )
    return Table(headers, rows)


def room_utilization_table(report: VersionAnalytics) -> Table:
    """Room usage, with the current-configuration denominator named per row."""
    headers = (
        "Room",
        "Sessions",
        "Occupied Minutes",
        "Occupied Hours",
        "Occupied Periods",
        "Active Days",
        "Utilization Basis",
        "Available Minutes",
        "Available Hours",
        "Utilization Percent",
        "Configuration Mismatch",
    )
    rows = tuple(
        (
            _label(row.room.code, row.room.name),
            row.session_count,
            row.occupied_minutes,
            row.occupied_hours,
            row.occupied_slot_count,
            row.days_used,
            row.utilization_basis,
            row.available_minutes,
            row.available_hours,
            row.utilization_percent,
            "Yes" if row.configuration_mismatch else "No",
        )
        for row in report.room_utilization
    )
    return Table(headers, rows)


def student_group_load_table(report: VersionAnalytics) -> Table:
    """Scheduled load per persisted student group."""
    headers = (
        "Student Group",
        "Department",
        "Sessions",
        "Scheduled Minutes",
        "Scheduled Hours",
        "Active Days",
        "Managing Departments",
        "Total Gap Minutes",
        "Max Gap Minutes",
        "Avg Gap Per Active Day",
    )
    rows = tuple(
        (
            _label(row.group.code, row.group.name),
            _label(row.department.code, row.department.name),
            row.session_count,
            row.scheduled_minutes,
            row.scheduled_hours,
            row.days_used,
            row.managing_department_count,
            row.total_gap_minutes,
            row.max_gap_minutes,
            row.average_gap_minutes_per_active_day,
        )
        for row in report.student_group_load
    )
    return Table(headers, rows)


def quality_table(report: VersionAnalytics) -> Table:
    """Quality figures, as raw quantities with no composite score."""
    quality = report.quality
    rows: list[tuple[Any, ...]] = [
        ("Total preference penalty", quality.total_preference_penalty),
        (
            "Average penalty per session",
            quality.average_preference_penalty_per_session,
        ),
        ("Total instructor gap minutes", quality.total_instructor_gap_minutes),
        ("Average instructor gap minutes", quality.average_instructor_gap_minutes),
        ("Total student group gap minutes", quality.total_student_group_gap_minutes),
        (
            "Average student group gap minutes",
            quality.average_student_group_gap_minutes,
        ),
        ("Instructors counted", quality.instructor_count),
        ("Student groups counted", quality.group_count),
        (
            "Max sessions for one instructor day",
            quality.max_sessions_for_one_instructor_day,
        ),
        ("Max sessions for one group day", quality.max_sessions_for_one_group_day),
    ]
    for weekday, count in quality.sessions_by_weekday.items():
        rows.append((f"Sessions on {weekday}", count))
    for start, count in quality.sessions_by_start_hour.items():
        rows.append((f"Sessions starting {start}", count))
    return Table(("Metric", "Value"), tuple(rows))


def _label(code: str, name: str) -> str:
    """One readable label out of an optional code and a name."""
    code = (code or "").strip()
    name = (name or "").strip()
    if code and name:
        return f"{code} — {name}"
    return code or name


__all__ = [
    "Table",
    "department_load_table",
    "department_scope_table",
    "instructor_workload_table",
    "metadata_table",
    "quality_table",
    "room_utilization_table",
    "student_group_load_table",
    "summary_table",
]
