"""The row-level issue contract of the semester plan import.

Every problem a workbook can have is reported as an :class:`ImportIssue`: which sheet,
which row, which column (when one column is responsible), a stable machine code, a
severity and a human message. Nothing is reported as an exception, so a malformed
workbook produces a list a spreadsheet author can act on instead of an HTTP 500.

Issue codes are stable identifiers. They are grouped here by area so the vocabulary stays
consistent between the workbook reader, the validator and the template documentation:

*workbook*: ``FILE_TOO_LARGE``, ``UNSUPPORTED_FILE_TYPE``, ``NOT_A_WORKBOOK``,
``MACRO_ENABLED_WORKBOOK``, ``MISSING_SHEET``, ``UNEXPECTED_SHEET``, ``MISSING_HEADER``,
``UNKNOWN_HEADER``, ``DUPLICATE_HEADER``, ``SHEET_ROW_LIMIT_EXCEEDED``,
``TOTAL_ROW_LIMIT_EXCEEDED``, ``SCANNED_ROW_LIMIT_EXCEEDED``, ``FORMULA_NOT_ALLOWED``,
``UNREADABLE_WORKBOOK``.

*references*: ``DUPLICATE_REF``, ``COURSE_REF_NOT_FOUND``, ``OFFERING_REF_NOT_FOUND``,
``COMPONENT_REF_NOT_FOUND``, ``GROUP_REF_NOT_FOUND``,
``ROOM_REQUIREMENT_MISSING``.

*values*: ``MISSING_VALUE``, ``INVALID_INTEGER``, ``INVALID_NUMBER``,
``INVALID_COMPONENT_TYPE``, ``INVALID_ASSIGNMENT_ROLE``, ``INVALID_STUDENT_COUNT``.

*existing data*: ``COURSE_ALREADY_EXISTS``, ``GROUP_ALREADY_EXISTS``,
``OFFERING_ALREADY_EXISTS``, ``DUPLICATE_COURSE_CODE``, ``DUPLICATE_GROUP_CODE``,
``DUPLICATE_OFFERING``, ``DUPLICATE_RELATION``, ``DUPLICATE_ROOM_REQUIREMENT``,
``PROGRAM_NOT_FOUND``, ``PROGRAM_OUTSIDE_DEPARTMENT``, ``STAGE_NOT_FOUND``,
``INSTRUCTOR_NOT_FOUND``, ``INSTRUCTOR_NOT_ELIGIBLE``, ``ROOM_TYPE_NOT_FOUND``,
``ROOM_TYPE_INACTIVE``, ``CAPABILITY_NOT_FOUND``, ``CAPABILITY_INACTIVE``,
``COURSE_NOT_OWNED_BY_DEPARTMENT``, ``MULTIPLE_PRIMARY_INSTRUCTORS``,
``PARENT_GROUP_NOT_IN_WORKBOOK``, ``PARENT_GROUP_DIFFERENT_STAGE``,
``PARENT_GROUP_SELF``, ``PARENT_GROUP_CYCLE``, ``GROUP_HIERARCHY_OVERLAP``,
``CROSS_DEPARTMENT_GROUP_REQUIRES_COLLEGE_ADMIN``,
``CROSS_DEPARTMENT_LINK_REQUIRES_COLLEGE_ADMIN``.

*warnings*: ``NO_PRIMARY_INSTRUCTOR``, ``COMPONENT_WITHOUT_GROUP``.

An issue is an ``ERROR`` by default. Only ``ERROR`` issues block an apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from scheduling.services.imports.domain import FILE_LEVEL_ROW, sheet_index

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"

#: Code of an issue raised for the workbook as a whole rather than one data row.
FILE_LEVEL_CODES = frozenset(
    {
        "FILE_TOO_LARGE",
        "UNSUPPORTED_FILE_TYPE",
        "NOT_A_WORKBOOK",
        "MACRO_ENABLED_WORKBOOK",
        "MISSING_SHEET",
        "UNEXPECTED_SHEET",
        "SHEET_ROW_LIMIT_EXCEEDED",
        "TOTAL_ROW_LIMIT_EXCEEDED",
        "SCANNED_ROW_LIMIT_EXCEEDED",
        "UNREADABLE_WORKBOOK",
    }
)


@dataclass(frozen=True)
class ImportIssue:
    """One reported problem, located as precisely as the workbook allows."""

    sheet: str
    row: int
    code: str
    message: str
    column: str | None = None
    severity: str = SEVERITY_ERROR
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.severity == SEVERITY_ERROR

    def as_dict(self) -> dict[str, Any]:
        """JSON representation. ``column`` is null when the whole row is at fault."""
        return {
            "sheet": self.sheet,
            "row": self.row,
            "column": self.column,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "details": dict(self.details),
        }

    def sort_key(self) -> tuple[int, int, str, str, str]:
        """Deterministic ordering: sheet order, row, column, code, message."""
        return (
            sheet_index(self.sheet),
            int(self.row),
            self.column or "",
            self.code,
            self.message,
        )


class IssueCollector:
    """Collects issues, merges exact duplicates and keeps a stable order."""

    def __init__(self) -> None:
        self._issues: list[ImportIssue] = []
        self._seen: set[tuple] = set()

    def add(
        self,
        sheet: str,
        row: int,
        code: str,
        message: str,
        *,
        column: str | None = None,
        severity: str = SEVERITY_ERROR,
        details: dict[str, Any] | None = None,
    ) -> ImportIssue:
        """Record one issue and return it."""
        issue = ImportIssue(
            sheet=sheet,
            row=int(row),
            code=code,
            message=message,
            column=column,
            severity=severity,
            details=dict(details or {}),
        )
        self.add_issue(issue)
        return issue

    def add_issue(self, issue: ImportIssue) -> None:
        key = (
            issue.sheet,
            issue.row,
            issue.column,
            issue.code,
            issue.severity,
            issue.message,
            tuple(sorted(issue.details.items())),
        )
        if key in self._seen:
            return
        self._seen.add(key)
        self._issues.append(issue)

    def extend(self, issues: Iterable[ImportIssue]) -> None:
        for issue in issues:
            self.add_issue(issue)

    def warn(
        self,
        sheet: str,
        row: int,
        code: str,
        message: str,
        *,
        column: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ImportIssue:
        """Record a non-blocking issue."""
        return self.add(
            sheet,
            row,
            code,
            message,
            column=column,
            severity=SEVERITY_WARNING,
            details=details,
        )

    @property
    def issues(self) -> tuple[ImportIssue, ...]:
        """Every issue, sorted by the documented order, duplicates merged."""
        return tuple(sorted(self._issues, key=ImportIssue.sort_key))

    @property
    def errors(self) -> tuple[ImportIssue, ...]:
        return tuple(issue for issue in self.issues if issue.is_error)

    @property
    def warnings(self) -> tuple[ImportIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.is_error)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def valid(self) -> bool:
        """True when the workbook may be applied: no blocking issue at all."""
        return not self.errors

    def file_level(self, code: str, message: str, *, severity=SEVERITY_ERROR):
        """Convenience for an issue that concerns the workbook rather than a row."""
        return self.add(
            sheet="",
            row=FILE_LEVEL_ROW,
            code=code,
            message=message,
            severity=severity,
        )


__all__ = [
    "FILE_LEVEL_CODES",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "ImportIssue",
    "IssueCollector",
]
