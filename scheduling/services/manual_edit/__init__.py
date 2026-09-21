"""Validated manual editing of persisted draft versions (Phase 12).

* ``domain`` - value objects: the requested change, the proposed timetable, the
  issues, and the results of validating or applying an edit.
* ``issues`` - the frozen inventory of manual-edit codes and refusal reasons.
* ``validator`` - builds the complete proposed version and checks it: placement
  validity of what moved, and collisions across the finished timetable.
* ``cloning`` - copy-on-write creation of the new version, with historical snapshot
  values copied and only the placement replaced.
* ``service`` - the pipeline the API calls: latest-DRAFT-only rule, validate-only,
  and the locked transaction that appends the new version.

The solver is never involved: a manual edit relocates what the user asked to relocate
and reports conflicts, and it never re-optimises anything else.
"""

from scheduling.services.manual_edit.cloning import clone_version
from scheduling.services.manual_edit.domain import (
    EntryPlacement,
    ManualEditChange,
    ManualEditIssue,
    ManualEditResult,
    ManualEditValidation,
    ProposedEntry,
    ProposedVersion,
)
from scheduling.services.manual_edit.issues import (
    MANUAL_EDIT_ISSUE_CODES,
    REASON_BASE_VERSION_NOT_DRAFT,
    REASON_MANUAL_EDIT_VALIDATION_FAILED,
    REASON_STALE_BASE_VERSION,
    ManualEditIssueCode,
)
from scheduling.services.manual_edit.service import (
    BASE_STATE_CODES,
    ManualEditService,
    base_state_issue,
)
from scheduling.services.manual_edit.validator import ManualEditValidator

__all__ = [
    "BASE_STATE_CODES",
    "MANUAL_EDIT_ISSUE_CODES",
    "REASON_BASE_VERSION_NOT_DRAFT",
    "REASON_MANUAL_EDIT_VALIDATION_FAILED",
    "REASON_STALE_BASE_VERSION",
    "EntryPlacement",
    "ManualEditChange",
    "ManualEditIssue",
    "ManualEditIssueCode",
    "ManualEditResult",
    "ManualEditService",
    "ManualEditValidation",
    "ManualEditValidator",
    "ProposedEntry",
    "ProposedVersion",
    "base_state_issue",
    "clone_version",
]
