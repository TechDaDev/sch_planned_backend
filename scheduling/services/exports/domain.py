"""Value objects of the Phase 15 exports.

An export is a *representation* of a report that already exists: the timetable rows
come from the same scoped entry facts the Phase 14 analytics service loads, and every
analytics figure comes from the Phase 14 report unchanged. Nothing here recomputes a
metric, and nothing here writes.

Two kinds of value are kept apart on purpose:

* **snapshot values** are the display strings the persisted version stored, so a
  historical export never changes when a live course, room, department, instructor or
  group is renamed;
* **export metadata** (the generated timestamp) varies per request and is never an
  input to a metric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from academics.models import Weekday
from scheduling.services.analytics import EntryFacts, VersionAnalytics

#: How the timetable rows of one export are ordered.
TIMETABLE_SORT_KEY = "chronological"

#: Weekday display order of the college week.
_WEEKDAY_LABELS = {int(day): day.label for day in Weekday}


class ExportError(Exception):
    """Base class of controlled export failures."""

    code = "EXPORT_FAILED"
    default_message = "The export could not be generated."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message


class ExportFontUnavailable(ExportError):
    """No Unicode-capable font could be resolved for PDF generation.

    The service refuses to render a document it cannot draw correctly rather than
    emitting blank boxes or a corrupt-looking PDF.
    """

    code = "PDF_FONT_UNAVAILABLE"
    default_message = (
        "No Unicode-capable PDF font is available on this host, so the document was "
        "not generated. Configure the font path in the deployment settings."
    )


@dataclass(frozen=True)
class ExportMetadata:
    """Document metadata written into the workbook and the PDF.

    ``generated_at`` is the only field that differs between two exports of the same
    version; it never feeds a metric.
    """

    title: str
    scope: str
    semester_label: str
    schedule_id: int
    version_number: int
    status: str
    source: str
    version_created_at: datetime | None = None
    published_at: datetime | None = None
    published_by: str | None = None
    department_label: str | None = None
    generated_at: datetime | None = None

    def as_rows(self) -> tuple[tuple[str, str], ...]:
        """Labelled key/value pairs, in a stable order."""
        rows: list[tuple[str, str]] = [
            ("Document", self.title),
            ("Scope", self.scope),
            ("Semester", self.semester_label),
            ("Schedule", str(self.schedule_id)),
            ("Version", str(self.version_number)),
            ("Status", self.status),
            ("Source", self.source),
            ("Version created", _format_datetime(self.version_created_at)),
            ("Published", _format_datetime(self.published_at)),
            ("Published by", self.published_by or ""),
            ("Department", self.department_label or ""),
            ("Generated", _format_datetime(self.generated_at)),
        ]
        return tuple(rows)


def _format_datetime(value: datetime | None) -> str:
    """Local ISO-like rendering, or an empty cell when the value is absent."""
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class TimetableRow:
    """One persisted entry as the timetable sheet and the PDF table show it."""

    managing_department: str
    course_code: str
    course_name: str
    offering: str
    component_type: str
    component_label: str
    session: str
    weekday: str
    start: str
    end: str
    periods: str
    room_code: str
    room_name: str
    instructors: str
    student_groups: str
    penalty: int

    @classmethod
    def from_facts(cls, facts: EntryFacts) -> "TimetableRow":
        """Reshape one entry's facts into one timetable row."""
        return cls(
            managing_department=_label(facts.department.code, facts.department.name),
            course_code=facts.course.code,
            course_name=facts.course.name,
            offering=facts.offering_code,
            component_type=facts.component_type,
            component_label=facts.component_label,
            session=facts.session_id,
            weekday=_WEEKDAY_LABELS.get(facts.day_of_week, str(facts.day_of_week)),
            start=_clock(facts.start_minute),
            end=_clock(facts.end_minute),
            periods=", ".join(facts.periods),
            room_code="" if facts.room is None else facts.room.code,
            room_name="" if facts.room is None else facts.room.name,
            instructors=", ".join(
                member.full_name for member in facts.instructors
            ),
            student_groups=", ".join(
                _label(group.code, group.name) for group in facts.groups
            ),
            penalty=facts.penalty,
        )

    def as_values(self) -> tuple[Any, ...]:
        """The row as a plain tuple, in the documented column order."""
        return (
            self.managing_department,
            self.course_code,
            self.course_name,
            self.offering,
            self.component_type,
            self.component_label,
            self.session,
            self.weekday,
            self.start,
            self.end,
            self.periods,
            self.room_code,
            self.room_name,
            self.instructors,
            self.student_groups,
            self.penalty,
        )


#: Column headers of the timetable sheet, in order.
TIMETABLE_COLUMNS = (
    "Managing Department",
    "Course Code",
    "Course Name",
    "Offering",
    "Component Type",
    "Component Label",
    "Session",
    "Weekday",
    "Start",
    "End",
    "Periods",
    "Room Code",
    "Room Name",
    "Instructors",
    "Student Groups",
    "Penalty",
)


def _label(code: str, name: str) -> str:
    """One readable label out of an optional code and a name."""
    code = (code or "").strip()
    name = (name or "").strip()
    if code and name:
        return f"{code} — {name}"
    return code or name


def _clock(minutes: int) -> str:
    """``HH:MM`` rendering of a minute offset from midnight."""
    hours, remainder = divmod(int(minutes), 60)
    return f"{hours:02d}:{remainder:02d}"


@dataclass(frozen=True)
class ExportDocument:
    """Everything both renderers need, computed once by the export service."""

    metadata: ExportMetadata
    report: VersionAnalytics
    timetable: tuple[TimetableRow, ...] = field(default_factory=tuple)
    analytics_rows: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    department_scope_rows: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        """True when the scoped entry set holds no session."""
        return not self.timetable


def timetable_rows(facts: tuple[EntryFacts, ...]) -> tuple[TimetableRow, ...]:
    """Chronological timetable rows for one scoped entry set.

    Ordering is total - weekday, start, end, managing department, course code,
    component label, session - so two exports of unchanged data are byte-identical
    apart from the generated timestamp. One entry is one row: the occupied periods are
    joined into a single cell rather than expanded into extra rows.
    """
    rows = [TimetableRow.from_facts(fact) for fact in facts]
    rows.sort(
        key=lambda row: (
            row.weekday,
            row.start,
            row.end,
            row.managing_department,
            row.course_code,
            row.component_label,
            row.session,
        )
    )
    return tuple(rows)


__all__ = [
    "TIMETABLE_COLUMNS",
    "TIMETABLE_SORT_KEY",
    "ExportDocument",
    "ExportError",
    "ExportFontUnavailable",
    "ExportMetadata",
    "TimetableRow",
    "timetable_rows",
]
