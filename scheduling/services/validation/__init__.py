"""Pre-scheduling validation: the public surface of the Phase 7 service.

``PreSchedulingValidator`` is the entry point. It reads stored data, computes the
time grid in memory and returns a :class:`ValidationResult`; nothing is written.
"""

from scheduling.services.validation.issues import (
    ALL_ISSUE_CODES,
    WARNING_ONLY_CODES,
    EntityType,
    IssueCode,
    IssueCollector,
    Severity,
    ValidationIssue,
)
from scheduling.services.validation.resources import ResourceFacts
from scheduling.services.validation.time_grid import (
    TimeGrid,
    UsableGrid,
    group_windows,
    hours_to_minutes,
    max_contiguous_minutes,
    merge_intervals,
    time_to_minutes,
    total_minutes,
)
from scheduling.services.validation.validator import (
    PreSchedulingValidator,
    ValidationResult,
    ValidationScope,
    ValidationSummary,
)

__all__ = [
    "ALL_ISSUE_CODES",
    "WARNING_ONLY_CODES",
    "EntityType",
    "IssueCode",
    "IssueCollector",
    "PreSchedulingValidator",
    "ResourceFacts",
    "Severity",
    "TimeGrid",
    "UsableGrid",
    "ValidationIssue",
    "ValidationResult",
    "ValidationScope",
    "ValidationSummary",
    "group_windows",
    "hours_to_minutes",
    "max_contiguous_minutes",
    "merge_intervals",
    "time_to_minutes",
    "total_minutes",
]
