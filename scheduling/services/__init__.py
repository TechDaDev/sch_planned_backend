"""Service layer for the scheduling app.

Services hold the domain logic that API views must not contain: a view validates
its input, authorizes the caller, calls a service and serializes the result.

Phase 7 adds the pre-scheduling validator, which inspects stored data and reports
whether timetable generation is ready to begin. It never writes.
"""

from scheduling.services.validation import (
    IssueCode,
    PreSchedulingValidator,
    Severity,
    TimeGrid,
    ValidationIssue,
    ValidationResult,
    ValidationScope,
    ValidationSummary,
    hours_to_minutes,
    max_contiguous_minutes,
)

__all__ = [
    "IssueCode",
    "PreSchedulingValidator",
    "Severity",
    "TimeGrid",
    "ValidationIssue",
    "ValidationResult",
    "ValidationScope",
    "ValidationSummary",
    "hours_to_minutes",
    "max_contiguous_minutes",
]
