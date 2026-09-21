"""Schedule workflow and publication (Phase 13).

* ``issues`` - the frozen inventory of workflow action and validation codes.
* ``validation`` - ``WorkflowVersionValidator``: measures a *stored* version against
  today's configuration (academic activity, session structure, assignments, groups,
  rooms, the time grid and internal collisions) and blocks anything that no longer
  holds.
* ``service`` - ``ScheduleWorkflowService``: the forward-only transition chain, the
  role matrix, the latest-version rule and the locked transaction that stamps one
  stage.
* ``publication`` - visibility and loading of the officially published timetable,
  including the instructor view used later by the instructor app.

Nothing in this package writes timetable data. A transition writes workflow metadata
on the version and, when publishing, the authoritative pointer on the schedule.
"""

from scheduling.services.workflow.issues import (
    REASON_SCHEDULE_VALIDATION_FAILED,
    WORKFLOW_ISSUE_CODES,
    WorkflowIssueCode,
)
from scheduling.services.workflow.publication import (
    PUBLISHED_DEPARTMENT_ROLES,
    current_published_college_schedule,
    published_entries,
    published_entry_filter,
)
from scheduling.services.workflow.service import (
    ACTION_APPROVE,
    ACTION_PUBLISH,
    ACTION_REVIEW,
    ACTION_SUBMIT,
    TRANSITIONS,
    ScheduleWorkflowService,
    Transition,
    WorkflowResult,
)
from scheduling.services.workflow.validation import (
    WorkflowIssue,
    WorkflowValidation,
    WorkflowVersionValidator,
)

__all__ = [
    "ACTION_APPROVE",
    "ACTION_PUBLISH",
    "ACTION_REVIEW",
    "ACTION_SUBMIT",
    "PUBLISHED_DEPARTMENT_ROLES",
    "REASON_SCHEDULE_VALIDATION_FAILED",
    "TRANSITIONS",
    "WORKFLOW_ISSUE_CODES",
    "ScheduleWorkflowService",
    "Transition",
    "WorkflowIssue",
    "WorkflowIssueCode",
    "WorkflowResult",
    "WorkflowValidation",
    "WorkflowVersionValidator",
    "current_published_college_schedule",
    "published_entries",
    "published_entry_filter",
]
