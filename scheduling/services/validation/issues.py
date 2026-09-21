"""Stable vocabulary for pre-scheduling validation issues.

Three things are deliberately frozen here so that API clients can rely on them:

* the set of issue ``code`` values (never built dynamically from data or from a
  Python exception, so a client switch statement cannot silently break);
* the two severities, where only ``ERROR`` can make a validation run un-ready;
* the ``entity_type`` strings, which are the model class names of the row the
  issue is reported against.

Issues are collected through :class:`IssueCollector`, which removes exact
duplicates and always yields the same order for the same data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from django.db import models


class Severity(models.TextChoices):
    """How much an issue matters.

    ``ERROR`` means timetable generation cannot start; ``WARNING`` is
    informational and never makes a run ``ready = false``.
    """

    ERROR = "ERROR", "Error"
    WARNING = "WARNING", "Warning"


#: Sort order for severities: errors first, then warnings.
SEVERITY_RANK: dict[str, int] = {Severity.ERROR: 0, Severity.WARNING: 1}


class EntityType:
    """``entity_type`` values, matching the model class names of this project."""

    SEMESTER = "Semester"
    WORKING_DAY = "WorkingDay"
    TEACHING_COMPONENT = "TeachingComponent"
    STUDENT_GROUP = "StudentGroup"
    INSTRUCTOR = "InstructorProfile"
    ROOM_TYPE = "RoomType"
    ROOM_CAPABILITY = "RoomCapability"
    COURSE = "Course"
    COURSE_OFFERING = "CourseOffering"
    DEPARTMENT = "Department"
    STUDY_PROGRAM = "StudyProgram"
    STUDY_STAGE = "StudyStage"


class IssueCode:
    """The complete, frozen set of codes the validator may emit.

    Grouped the way the checks run. See ``README.md`` for the meaning, the
    severity and the shape of ``details`` for every code.
    """

    # --- time grid ---------------------------------------------------------
    NO_ACTIVE_WORKING_DAYS = "NO_ACTIVE_WORKING_DAYS"
    WORKING_DAY_NO_ACTIVE_SLOTS = "WORKING_DAY_NO_ACTIVE_SLOTS"

    # --- academic dependencies --------------------------------------------
    INACTIVE_ACADEMIC_DEPENDENCY = "INACTIVE_ACADEMIC_DEPENDENCY"

    # --- component demand --------------------------------------------------
    COMPONENT_NO_STUDENT_GROUPS = "COMPONENT_NO_STUDENT_GROUPS"
    STUDENT_GROUP_INACTIVE = "STUDENT_GROUP_INACTIVE"
    STUDENT_COUNT_ZERO = "STUDENT_COUNT_ZERO"
    SESSION_DURATION_NOT_SUPPORTED_BY_GRID = "SESSION_DURATION_NOT_SUPPORTED_BY_GRID"
    COMPONENT_WEEKLY_HOURS_EXCEED_GRID = "COMPONENT_WEEKLY_HOURS_EXCEED_GRID"

    # --- instructors -------------------------------------------------------
    PRIMARY_INSTRUCTOR_MISSING = "PRIMARY_INSTRUCTOR_MISSING"
    MULTIPLE_PRIMARY_INSTRUCTORS = "MULTIPLE_PRIMARY_INSTRUCTORS"
    INSTRUCTOR_INACTIVE = "INSTRUCTOR_INACTIVE"
    INSTRUCTOR_NOT_ELIGIBLE = "INSTRUCTOR_NOT_ELIGIBLE"
    INSTRUCTOR_AVAILABILITY_MISSING = "INSTRUCTOR_AVAILABILITY_MISSING"
    INSTRUCTOR_SESSION_DURATION_UNSUPPORTED = "INSTRUCTOR_SESSION_DURATION_UNSUPPORTED"
    INSTRUCTOR_AVAILABLE_TIME_INSUFFICIENT = "INSTRUCTOR_AVAILABLE_TIME_INSUFFICIENT"
    INSTRUCTOR_MAX_WEEKLY_HOURS_EXCEEDED = "INSTRUCTOR_MAX_WEEKLY_HOURS_EXCEEDED"
    INSTRUCTOR_MAX_DAILY_HOURS_IMPOSSIBLE = "INSTRUCTOR_MAX_DAILY_HOURS_IMPOSSIBLE"
    INSTRUCTOR_MAX_WEEKLY_HOURS_NOT_CONFIGURED = (
        "INSTRUCTOR_MAX_WEEKLY_HOURS_NOT_CONFIGURED"
    )
    INSTRUCTOR_MAX_DAILY_HOURS_NOT_CONFIGURED = (
        "INSTRUCTOR_MAX_DAILY_HOURS_NOT_CONFIGURED"
    )

    # --- rooms -------------------------------------------------------------
    ROOM_REQUIREMENT_MISSING = "ROOM_REQUIREMENT_MISSING"
    ROOM_REQUIREMENT_INACTIVE = "ROOM_REQUIREMENT_INACTIVE"
    ROOM_TYPE_INACTIVE = "ROOM_TYPE_INACTIVE"
    ROOM_CAPABILITY_INACTIVE = "ROOM_CAPABILITY_INACTIVE"
    NO_SUITABLE_ROOM = "NO_SUITABLE_ROOM"
    NO_SUITABLE_ROOM_WITH_AVAILABILITY = "NO_SUITABLE_ROOM_WITH_AVAILABILITY"


#: Every code the validator can emit, in documentation order.
ALL_ISSUE_CODES: tuple[str, ...] = (
    IssueCode.NO_ACTIVE_WORKING_DAYS,
    IssueCode.WORKING_DAY_NO_ACTIVE_SLOTS,
    IssueCode.INACTIVE_ACADEMIC_DEPENDENCY,
    IssueCode.COMPONENT_NO_STUDENT_GROUPS,
    IssueCode.STUDENT_GROUP_INACTIVE,
    IssueCode.STUDENT_COUNT_ZERO,
    IssueCode.SESSION_DURATION_NOT_SUPPORTED_BY_GRID,
    IssueCode.COMPONENT_WEEKLY_HOURS_EXCEED_GRID,
    IssueCode.PRIMARY_INSTRUCTOR_MISSING,
    IssueCode.MULTIPLE_PRIMARY_INSTRUCTORS,
    IssueCode.INSTRUCTOR_INACTIVE,
    IssueCode.INSTRUCTOR_NOT_ELIGIBLE,
    IssueCode.INSTRUCTOR_AVAILABILITY_MISSING,
    IssueCode.INSTRUCTOR_SESSION_DURATION_UNSUPPORTED,
    IssueCode.INSTRUCTOR_AVAILABLE_TIME_INSUFFICIENT,
    IssueCode.INSTRUCTOR_MAX_WEEKLY_HOURS_EXCEEDED,
    IssueCode.INSTRUCTOR_MAX_DAILY_HOURS_IMPOSSIBLE,
    IssueCode.ROOM_REQUIREMENT_MISSING,
    IssueCode.ROOM_REQUIREMENT_INACTIVE,
    IssueCode.ROOM_TYPE_INACTIVE,
    IssueCode.ROOM_CAPABILITY_INACTIVE,
    IssueCode.NO_SUITABLE_ROOM,
    IssueCode.NO_SUITABLE_ROOM_WITH_AVAILABILITY,
)

#: Codes that only ever appear as warnings.
WARNING_ONLY_CODES: tuple[str, ...] = (
    IssueCode.INSTRUCTOR_MAX_WEEKLY_HOURS_NOT_CONFIGURED,
    IssueCode.INSTRUCTOR_MAX_DAILY_HOURS_NOT_CONFIGURED,
)


def canonical_details(details: Mapping[str, Any]) -> str:
    """Deterministic JSON rendering of ``details``, used as a tie-breaker.

    Also used as part of the deduplication key, so two issues with the same code
    and entity but different facts stay distinct.
    """
    return json.dumps(dict(details), sort_keys=True, default=str)


@dataclass(frozen=True)
class ValidationIssue:
    """One reported problem, in the response contract's exact shape."""

    code: str
    severity: str
    message: str
    entity_type: str
    entity_id: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def sort_key(self) -> tuple:
        """Stable ordering key: severity, code, entity type, entity id, facts."""
        return (
            SEVERITY_RANK.get(self.severity, len(SEVERITY_RANK)),
            self.code,
            self.entity_type,
            -1 if self.entity_id is None else self.entity_id,
            canonical_details(self.details),
        )

    def as_dict(self) -> dict[str, Any]:
        """Plain dictionary form (used by the API serializer and by tests)."""
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "details": dict(self.details),
        }


class IssueCollector:
    """Accumulates issues, drops exact duplicates and sorts deterministically.

    Deduplication keys on the code, severity, entity and the full ``details``
    mapping. Resource-scoped checks therefore report one issue per resource no
    matter how many components reference it, while component-scoped checks stay
    per component. Callers achieve that by keeping component identifiers out of
    the ``details`` of resource-scoped issues.
    """

    def __init__(self) -> None:
        self._issues: dict[tuple, ValidationIssue] = {}

    @staticmethod
    def _key(
        code: str,
        severity: str,
        entity_type: str,
        entity_id: int | None,
        details: Mapping[str, Any],
    ) -> tuple:
        return (
            code,
            severity,
            entity_type,
            entity_id,
            canonical_details(details),
        )

    def add(
        self,
        code: str,
        severity: str,
        message: str,
        entity_type: str,
        entity_id: int | None = None,
        **details: Any,
    ) -> None:
        """Record one issue; an exact duplicate is ignored."""
        key = self._key(code, severity, entity_type, entity_id, details)
        if key in self._issues:
            return
        self._issues[key] = ValidationIssue(
            code=code,
            severity=severity,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            details=dict(details),
        )

    def extend(self, issues: Iterable[ValidationIssue]) -> None:
        """Record already-built issues (used by tests and adapters)."""
        for issue in issues:
            self.add(
                issue.code,
                issue.severity,
                issue.message,
                issue.entity_type,
                issue.entity_id,
                **dict(issue.details),
            )

    def issues(self) -> list[ValidationIssue]:
        """All issues, deterministically ordered."""
        return sorted(self._issues.values(), key=lambda issue: issue.sort_key)

    def count(self, severity: str) -> int:
        """Number of collected issues with ``severity``."""
        return sum(1 for issue in self._issues.values() if issue.severity == severity)

    @property
    def error_count(self) -> int:
        return self.count(Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return self.count(Severity.WARNING)
