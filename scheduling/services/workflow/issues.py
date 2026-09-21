"""Stable codes for schedule workflow actions and workflow validation.

Two families again, and both are frozen: clients switch on them.

* **action** codes describe why a transition was refused
  (``STALE_VERSION``, ``INVALID_TRANSITION``, ``DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE``);
* **validation** codes describe what is wrong with a stored timetable when it is
  measured against today's configuration (drift, availability, conflicts). They are
  all blocking ``ERROR``s: a snapshot that was valid when generated may stop being
  valid later, and workflow must not launder that.

``WORKFLOW_ISSUE_CODES`` is the frozen inventory used by the README and the tests.
"""

from __future__ import annotations


class WorkflowIssueCode:
    """Every workflow issue this phase may report."""

    # --- workflow action --------------------------------------------------
    STALE_VERSION = "STALE_VERSION"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE = "DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE"
    EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED = "EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED"

    # --- academic activity ------------------------------------------------
    INACTIVE_ACADEMIC_DEPENDENCY = "INACTIVE_ACADEMIC_DEPENDENCY"

    # --- drift against current configuration ------------------------------
    SESSION_COUNT_MISMATCH = "SESSION_COUNT_MISMATCH"
    SESSION_DURATION_MISMATCH = "SESSION_DURATION_MISMATCH"
    TEACHING_ASSIGNMENT_CHANGED = "TEACHING_ASSIGNMENT_CHANGED"
    STUDENT_GROUP_CONFIGURATION_CHANGED = "STUDENT_GROUP_CONFIGURATION_CHANGED"
    STUDENT_GROUP_INACTIVE = "STUDENT_GROUP_INACTIVE"
    TIME_SLOT_CONFIGURATION_CHANGED = "TIME_SLOT_CONFIGURATION_CHANGED"

    # --- current resource validity ----------------------------------------
    TIME_SLOT_INACTIVE = "TIME_SLOT_INACTIVE"
    TIME_SLOT_WRONG_SEMESTER = "TIME_SLOT_WRONG_SEMESTER"
    INSTRUCTOR_INACTIVE = "INSTRUCTOR_INACTIVE"
    INSTRUCTOR_NOT_ELIGIBLE = "INSTRUCTOR_NOT_ELIGIBLE"
    INSTRUCTOR_UNAVAILABLE = "INSTRUCTOR_UNAVAILABLE"
    ROOM_INACTIVE = "ROOM_INACTIVE"
    ROOM_NOT_ELIGIBLE = "ROOM_NOT_ELIGIBLE"
    ROOM_REQUIREMENT_UNSATISFIED = "ROOM_REQUIREMENT_UNSATISFIED"
    ROOM_UNAVAILABLE = "ROOM_UNAVAILABLE"

    # --- collisions inside the stored version -----------------------------
    INSTRUCTOR_CONFLICT = "INSTRUCTOR_CONFLICT"
    STUDENT_GROUP_CONFLICT = "STUDENT_GROUP_CONFLICT"
    ROOM_CONFLICT = "ROOM_CONFLICT"
    COMPONENT_CONFLICT = "COMPONENT_CONFLICT"


#: Every code above, frozen for documentation and regression checks.
WORKFLOW_ISSUE_CODES: tuple[str, ...] = (
    WorkflowIssueCode.STALE_VERSION,
    WorkflowIssueCode.INVALID_TRANSITION,
    WorkflowIssueCode.DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE,
    WorkflowIssueCode.EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED,
    WorkflowIssueCode.INACTIVE_ACADEMIC_DEPENDENCY,
    WorkflowIssueCode.SESSION_COUNT_MISMATCH,
    WorkflowIssueCode.SESSION_DURATION_MISMATCH,
    WorkflowIssueCode.TEACHING_ASSIGNMENT_CHANGED,
    WorkflowIssueCode.STUDENT_GROUP_CONFIGURATION_CHANGED,
    WorkflowIssueCode.STUDENT_GROUP_INACTIVE,
    WorkflowIssueCode.TIME_SLOT_CONFIGURATION_CHANGED,
    WorkflowIssueCode.TIME_SLOT_INACTIVE,
    WorkflowIssueCode.TIME_SLOT_WRONG_SEMESTER,
    WorkflowIssueCode.INSTRUCTOR_INACTIVE,
    WorkflowIssueCode.INSTRUCTOR_NOT_ELIGIBLE,
    WorkflowIssueCode.INSTRUCTOR_UNAVAILABLE,
    WorkflowIssueCode.ROOM_INACTIVE,
    WorkflowIssueCode.ROOM_NOT_ELIGIBLE,
    WorkflowIssueCode.ROOM_REQUIREMENT_UNSATISFIED,
    WorkflowIssueCode.ROOM_UNAVAILABLE,
    WorkflowIssueCode.INSTRUCTOR_CONFLICT,
    WorkflowIssueCode.STUDENT_GROUP_CONFLICT,
    WorkflowIssueCode.ROOM_CONFLICT,
    WorkflowIssueCode.COMPONENT_CONFLICT,
)

#: Reason string of a forward transition refused because the snapshot is not valid.
REASON_SCHEDULE_VALIDATION_FAILED = "SCHEDULE_VALIDATION_FAILED"


__all__ = [
    "REASON_SCHEDULE_VALIDATION_FAILED",
    "WORKFLOW_ISSUE_CODES",
    "WorkflowIssueCode",
]
