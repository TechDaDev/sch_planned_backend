"""Stable codes for department generation issues.

The codes are frozen like the Phase 7 validation codes, so API clients can switch
on them. ``VALIDATION_FAILED`` and ``CANDIDATE_BUILD_FAILED`` are the two reasons
the endpoint answers ``409``; the solver codes describe a normal, completed run
that simply produced no timetable, which is a ``200``.
"""

from __future__ import annotations

from scheduling.services.validation.issues import ValidationIssue  # noqa: F401  (re-exported)


class GenerationIssueCode:
    """Every code the department scheduler may report."""

    #: The Phase 7 gate said the semester/department is not ready.
    VALIDATION_FAILED = "VALIDATION_FAILED"

    #: Sessions exist that no candidate could be built for, so the engine was not called.
    NO_PLACEMENT_CANDIDATES = "NO_PLACEMENT_CANDIDATES"

    #: An adapter assumption was violated between validation and candidate building.
    ADAPTER_PRECONDITION_FAILED = "ADAPTER_PRECONDITION_FAILED"

    #: The adapter produced the same physical placement twice (an adapter defect).
    ADAPTER_DUPLICATE_CANDIDATE = "ADAPTER_DUPLICATE_CANDIDATE"

    #: The engine proved that no globally conflict-free timetable exists.
    SOLVER_INFEASIBLE = "SOLVER_INFEASIBLE"

    #: The engine stopped without a proven answer, typically at the time limit.
    SOLVER_UNKNOWN = "SOLVER_UNKNOWN"

    #: The engine rejected the constructed model, which points at an engine defect.
    SOLVER_MODEL_INVALID = "SOLVER_MODEL_INVALID"


#: Codes that stop generation before the engine runs.
PRE_SOLVE_CODES: tuple[str, ...] = (
    GenerationIssueCode.VALIDATION_FAILED,
    GenerationIssueCode.NO_PLACEMENT_CANDIDATES,
    GenerationIssueCode.ADAPTER_PRECONDITION_FAILED,
    GenerationIssueCode.ADAPTER_DUPLICATE_CANDIDATE,
)

#: Reason strings reported by a rejected (HTTP 409) response.
REASON_VALIDATION_FAILED = "PRE_SCHEDULING_VALIDATION_FAILED"
REASON_CANDIDATE_BUILD_FAILED = "CANDIDATE_BUILD_FAILED"


__all__ = [
    "PRE_SOLVE_CODES",
    "REASON_CANDIDATE_BUILD_FAILED",
    "REASON_VALIDATION_FAILED",
    "GenerationIssueCode",
    "ValidationIssue",
]
