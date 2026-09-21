"""Stable codes for validated manual schedule editing.

Like the Phase 7 validation codes, these strings are part of the API contract:
clients switch on them, so they are constants rather than formatted at runtime, and
the set only grows. ``MANUAL_EDIT_ISSUE_CODES`` is the frozen inventory used by the
tests and the README.

Two families live here:

* **structural** codes describing the request or the base version itself
  (``BASE_VERSION_NOT_DRAFT``, ``STALE_BASE_VERSION``, ``ENTRY_NOT_IN_VERSION``,
  ``DUPLICATE_ENTRY_CHANGE``);
* **placement** codes describing what is wrong with the proposed timetable, either
  the target itself (slot/room/instructor validity) or a collision it creates
  (instructor, room, student group, component).
"""

from __future__ import annotations


class ManualEditIssueCode:
    """Every issue a manual edit may report, none of them built dynamically."""

    # --- base version and request shape ---------------------------------
    BASE_VERSION_NOT_DRAFT = "BASE_VERSION_NOT_DRAFT"
    STALE_BASE_VERSION = "STALE_BASE_VERSION"
    ENTRY_NOT_IN_VERSION = "ENTRY_NOT_IN_VERSION"
    DUPLICATE_ENTRY_CHANGE = "DUPLICATE_ENTRY_CHANGE"

    # --- proposed time slots ---------------------------------------------
    TIME_SLOT_NOT_FOUND = "TIME_SLOT_NOT_FOUND"
    TIME_SLOT_INACTIVE = "TIME_SLOT_INACTIVE"
    TIME_SLOT_WRONG_SEMESTER = "TIME_SLOT_WRONG_SEMESTER"
    TIME_SLOTS_DIFFERENT_DAY = "TIME_SLOTS_DIFFERENT_DAY"
    TIME_SLOTS_NOT_CONTIGUOUS = "TIME_SLOTS_NOT_CONTIGUOUS"
    SESSION_DURATION_MISMATCH = "SESSION_DURATION_MISMATCH"

    # --- instructors of the entry ----------------------------------------
    INSTRUCTOR_INACTIVE = "INSTRUCTOR_INACTIVE"
    INSTRUCTOR_NOT_ELIGIBLE = "INSTRUCTOR_NOT_ELIGIBLE"
    INSTRUCTOR_UNAVAILABLE = "INSTRUCTOR_UNAVAILABLE"

    # --- target room ------------------------------------------------------
    ROOM_NOT_FOUND = "ROOM_NOT_FOUND"
    ROOM_INACTIVE = "ROOM_INACTIVE"
    ROOM_NOT_ELIGIBLE = "ROOM_NOT_ELIGIBLE"
    ROOM_REQUIREMENT_UNSATISFIED = "ROOM_REQUIREMENT_UNSATISFIED"
    ROOM_UNAVAILABLE = "ROOM_UNAVAILABLE"

    # --- collisions inside the proposed version --------------------------
    INSTRUCTOR_CONFLICT = "INSTRUCTOR_CONFLICT"
    STUDENT_GROUP_CONFLICT = "STUDENT_GROUP_CONFLICT"
    ROOM_CONFLICT = "ROOM_CONFLICT"
    COMPONENT_CONFLICT = "COMPONENT_CONFLICT"


#: Every code above, frozen for documentation and regression checks.
MANUAL_EDIT_ISSUE_CODES: tuple[str, ...] = (
    ManualEditIssueCode.BASE_VERSION_NOT_DRAFT,
    ManualEditIssueCode.STALE_BASE_VERSION,
    ManualEditIssueCode.ENTRY_NOT_IN_VERSION,
    ManualEditIssueCode.DUPLICATE_ENTRY_CHANGE,
    ManualEditIssueCode.TIME_SLOT_NOT_FOUND,
    ManualEditIssueCode.TIME_SLOT_INACTIVE,
    ManualEditIssueCode.TIME_SLOT_WRONG_SEMESTER,
    ManualEditIssueCode.TIME_SLOTS_DIFFERENT_DAY,
    ManualEditIssueCode.TIME_SLOTS_NOT_CONTIGUOUS,
    ManualEditIssueCode.SESSION_DURATION_MISMATCH,
    ManualEditIssueCode.INSTRUCTOR_INACTIVE,
    ManualEditIssueCode.INSTRUCTOR_NOT_ELIGIBLE,
    ManualEditIssueCode.INSTRUCTOR_UNAVAILABLE,
    ManualEditIssueCode.ROOM_NOT_FOUND,
    ManualEditIssueCode.ROOM_INACTIVE,
    ManualEditIssueCode.ROOM_NOT_ELIGIBLE,
    ManualEditIssueCode.ROOM_REQUIREMENT_UNSATISFIED,
    ManualEditIssueCode.ROOM_UNAVAILABLE,
    ManualEditIssueCode.INSTRUCTOR_CONFLICT,
    ManualEditIssueCode.STUDENT_GROUP_CONFLICT,
    ManualEditIssueCode.ROOM_CONFLICT,
    ManualEditIssueCode.COMPONENT_CONFLICT,
)

#: Reason strings of a refused manual edit (HTTP 409).
REASON_BASE_VERSION_NOT_DRAFT = ManualEditIssueCode.BASE_VERSION_NOT_DRAFT
REASON_STALE_BASE_VERSION = ManualEditIssueCode.STALE_BASE_VERSION
REASON_MANUAL_EDIT_VALIDATION_FAILED = "MANUAL_EDIT_VALIDATION_FAILED"


__all__ = [
    "MANUAL_EDIT_ISSUE_CODES",
    "REASON_BASE_VERSION_NOT_DRAFT",
    "REASON_MANUAL_EDIT_VALIDATION_FAILED",
    "REASON_STALE_BASE_VERSION",
    "ManualEditIssueCode",
]
