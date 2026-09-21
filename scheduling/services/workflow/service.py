"""Schedule workflow transitions.

The stages are fixed and forward-only: ``DRAFT`` → ``SUBMITTED`` → ``REVIEWED`` →
``APPROVED`` → ``PUBLISHED``. There is no generic status update, no skipping and no
backwards move, and every transition writes workflow metadata only — the timetable
snapshot itself is never touched.

Three rules shape the implementation:

* **the latest version only** — an action on an older version is stale, because
  approving an obsolete timetable is worse than refusing the request;
* **validate before moving** — a stored snapshot that has decayed since it was
  created (revoked sharing, inactive room, changed weekly hours, re-cut time grid)
  must not advance through workflow;
* **one linear chain** — inside the write transaction the schedule row is locked, the
  version is re-read, and both the freshness and the expected current status are
  re-checked, so concurrent transitions cannot skip a stage.

Publication is special: only a college schedule may publish, only an ``APPROVED``
latest version may be published, and publishing sets the schedule's authoritative
``published_version`` pointer in the same transaction. Older published versions keep
their ``PUBLISHED`` status; the pointer, not the status, says which one is current.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from scheduling.models import (
    Schedule,
    ScheduleScope,
    ScheduleStatus,
    ScheduleVersion,
)
from scheduling.services.workflow.issues import (
    REASON_SCHEDULE_VALIDATION_FAILED,
    WorkflowIssueCode,
)
from scheduling.services.workflow.validation import (
    WorkflowIssue,
    WorkflowValidation,
    WorkflowVersionValidator,
)

ACTION_SUBMIT = "SUBMIT"
ACTION_REVIEW = "REVIEW"
ACTION_APPROVE = "APPROVE"
ACTION_PUBLISH = "PUBLISH"


@dataclass(frozen=True)
class Transition:
    """One allowed move along the workflow chain."""

    action: str
    expected: str
    target: str

    #: Version fields the stage stamps. A stage never rewrites an earlier stage's pair.
    user_field: str
    time_field: str


TRANSITIONS: dict[str, Transition] = {
    ACTION_SUBMIT: Transition(
        ACTION_SUBMIT,
        ScheduleStatus.DRAFT,
        ScheduleStatus.SUBMITTED,
        "submitted_by",
        "submitted_at",
    ),
    ACTION_REVIEW: Transition(
        ACTION_REVIEW,
        ScheduleStatus.SUBMITTED,
        ScheduleStatus.REVIEWED,
        "reviewed_by",
        "reviewed_at",
    ),
    ACTION_APPROVE: Transition(
        ACTION_APPROVE,
        ScheduleStatus.REVIEWED,
        ScheduleStatus.APPROVED,
        "approved_by",
        "approved_at",
    ),
    ACTION_PUBLISH: Transition(
        ACTION_PUBLISH,
        ScheduleStatus.APPROVED,
        ScheduleStatus.PUBLISHED,
        "published_by",
        "published_at",
    ),
}


@dataclass(frozen=True)
class WorkflowResult:
    """What one transition attempt produced.

    ``applied`` is the only success flag. A refused attempt explains itself with a
    stable reason and leaves the status, the metadata and every entry untouched.
    """

    applied: bool
    action: str
    reason: str | None = None
    message: str = ""
    version: ScheduleVersion | None = None
    schedule: Schedule | None = None
    from_status: str | None = None
    to_status: str | None = None
    validation: WorkflowValidation | None = None

    @property
    def status(self) -> str | None:
        """Status after the attempt: the target when applied, the current one otherwise.

        A refusal leaves the version exactly as it was, so reporting its status is the
        honest answer for both cases.
        """
        if self.to_status is not None:
            return self.to_status
        if self.version is not None:
            return self.version.status
        return None


class ScheduleWorkflowService:
    """Moves one stored version along the workflow chain."""

    def __init__(self, *, version, action: str, user) -> None:
        self.version = version
        self.action = action
        self.user = user
        #: The stage this action performs. Named ``stage`` so it cannot shadow the
        #: :meth:`transition` method below.
        self.stage = TRANSITIONS[action]

    # --- public entry points ----------------------------------------------

    def validate(self) -> WorkflowValidation:
        """Full-version validation for the read-only validation endpoint.

        The publication completeness rule is not applied here, because the endpoint is
        generic: it reports whether the stored timetable is still valid, whatever stage
        it is in.
        """
        return self._validate(self.version, require_entries=False)

    def transition(self) -> WorkflowResult:
        """Authorize, validate and apply the transition."""
        schedule = self.version.schedule

        if self.action == ACTION_PUBLISH and schedule.scope != ScheduleScope.COLLEGE:
            # A department schedule is approved inside the college but never becomes
            # the authoritative timetable, so this refusal is a rule, not a permission.
            return self._refused(
                WorkflowIssueCode.DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE,
                "A department schedule can be approved but never published. Only the "
                "college-wide schedule becomes the official timetable.",
            )

        self.authorize()

        validation = self._validate(
            self.version, require_entries=self.action == ACTION_PUBLISH
        )
        if not validation.valid:
            return self._refused(
                self._validation_reason(validation),
                "The stored timetable is no longer valid, so the workflow status was "
                "not changed.",
                validation=validation,
            )

        with transaction.atomic():
            locked_schedule = Schedule.objects.select_for_update().get(pk=schedule.pk)
            locked_version = ScheduleVersion.objects.get(pk=self.version.pk)

            latest = (
                locked_schedule.versions.order_by("-version_number")
                .values_list("pk", flat=True)
                .first()
            )
            if latest != locked_version.pk:
                return self._refused(
                    WorkflowIssueCode.STALE_VERSION,
                    "This version is no longer the newest version of its schedule, so "
                    "the workflow cannot be advanced for it.",
                )
            if locked_version.status != self.stage.expected:
                return self._refused(
                    WorkflowIssueCode.INVALID_TRANSITION,
                    f"{self.stage.action} requires a "
                    f"{self.stage.expected.lower()} version, but this version is "
                    f"{locked_version.status.lower()}.",
                )

            revalidation = self._validate(
                locked_version, require_entries=self.action == ACTION_PUBLISH
            )
            if not revalidation.valid:
                return self._refused(
                    self._validation_reason(revalidation),
                    "The stored timetable is no longer valid, so the workflow status "
                    "was not changed.",
                    validation=revalidation,
                )

            from_status = locked_version.status
            self._stamp(locked_version)
            if self.action == ACTION_PUBLISH:
                locked_schedule.published_version = locked_version
                locked_schedule.updated_at = timezone.now()
                locked_schedule.save(
                    update_fields=["published_version", "updated_at"]
                )

        return WorkflowResult(
            applied=True,
            action=self.action,
            version=locked_version,
            schedule=locked_schedule,
            from_status=from_status,
            to_status=locked_version.status,
            validation=revalidation,
        )

    # --- authorization -----------------------------------------------------

    def authorize(self) -> None:
        """Raise ``PermissionDenied`` when this caller may not perform this action.

        Reachability is already decided by the read-scoped queryset the view used, so
        this method only answers the finer question: given a version the caller can
        see, may the caller's role advance *this* stage? A department administrator
        may submit their own department's draft but may not review or approve it,
        because reviewing your own timetable is not a review.
        """
        user = self.user
        schedule = self.version.schedule
        college_authority = user.has_cross_department_access

        if schedule.scope == ScheduleScope.COLLEGE:
            if not college_authority:
                raise PermissionDenied(
                    "Only college administrators may move a college-wide schedule "
                    "through the workflow."
                )
            return

        owns_department = (
            user.department_id is not None
            and user.department_id == schedule.department_id
        )
        if self.action == ACTION_SUBMIT:
            if college_authority:
                return
            if owns_department and (user.is_department_admin or user.is_scheduler):
                return
            raise PermissionDenied(
                "Only a college administrator, or the department administrator or "
                "scheduler of this schedule's department, may submit it."
            )

        if not college_authority:
            raise PermissionDenied(
                "Only a college administrator may review or approve a department "
                "schedule."
            )

    # --- internals ---------------------------------------------------------

    @staticmethod
    def _validate(version, *, require_entries: bool) -> WorkflowValidation:
        return WorkflowVersionValidator(version=version).validate(
            require_entries=require_entries
        )

    @staticmethod
    def _validation_reason(validation: WorkflowValidation) -> str:
        """Reason code of a refused transition.

        An empty timetable is named for what it is, because "publish an empty
        schedule" is a specific mistake rather than generic drift.
        """
        for issue in validation.issues:
            if issue.code == WorkflowIssueCode.EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED:
                return WorkflowIssueCode.EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED
        return REASON_SCHEDULE_VALIDATION_FAILED

    def _stamp(self, version: ScheduleVersion) -> None:
        """Move the status and record who did it, writing nothing else.

        Only the status column and this stage's own pair are written, so an earlier
        stage's metadata survives every later transition.
        """
        version.status = self.stage.target
        setattr(version, self.stage.user_field, self.user)
        setattr(version, self.stage.time_field, timezone.now())
        version.save(
            update_fields=[
                "status",
                self.stage.user_field,
                self.stage.time_field,
            ]
        )

    def _refused(
        self,
        reason: str,
        message: str,
        *,
        validation: WorkflowValidation | None = None,
    ) -> WorkflowResult:
        """A refusal that changed nothing."""
        return WorkflowResult(
            applied=False,
            action=self.action,
            reason=reason,
            message=message,
            version=self.version,
            schedule=self.version.schedule,
            from_status=self.version.status,
            validation=validation,
        )


def workflow_issue(code: str, message: str) -> WorkflowIssue:
    """Build a plain workflow issue, used by callers that report their own refusal."""
    return WorkflowIssue(code=code, message=message)


__all__ = [
    "ACTION_APPROVE",
    "ACTION_PUBLISH",
    "ACTION_REVIEW",
    "ACTION_SUBMIT",
    "TRANSITIONS",
    "ScheduleWorkflowService",
    "Transition",
    "WorkflowResult",
    "workflow_issue",
]
