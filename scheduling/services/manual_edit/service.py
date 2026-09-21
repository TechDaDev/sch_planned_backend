"""Validated manual editing of a persisted draft version.

Two operations share one pipeline:

* ``validate_only`` answers whether a set of placement changes would produce a valid
  timetable, and writes nothing at all. It exists so a user interface can check a
  drag-and-drop move before offering to save it.
* ``apply`` does the same validation and, when it passes, writes the result as a new
  ``DRAFT`` version whose parent is the base version.

Both refuse to run at all unless the base version is the *latest* ``DRAFT`` version of
its schedule, which keeps version history linear: a browser holding stale state cannot
branch the chain, and two simultaneous editors cannot silently overwrite each other.

The solver is never involved. Manual editing relocates sessions the user asked to
relocate and reports conflicts; it does not re-optimise anything else.
"""

from __future__ import annotations

from typing import Iterable

from django.db import IntegrityError, transaction
from scheduling.models import Schedule, ScheduleStatus, ScheduleVersion
from scheduling.services.manual_edit.cloning import clone_version
from scheduling.services.manual_edit.domain import (
    ManualEditChange,
    ManualEditIssue,
    ManualEditResult,
    ManualEditValidation,
)
from scheduling.services.manual_edit.issues import (
    REASON_BASE_VERSION_NOT_DRAFT,
    REASON_MANUAL_EDIT_VALIDATION_FAILED,
    REASON_STALE_BASE_VERSION,
    ManualEditIssueCode,
)
from scheduling.services.manual_edit.validator import ManualEditValidator

#: Issue codes that describe the base version rather than the proposed placement.
BASE_STATE_CODES: tuple[str, ...] = (
    ManualEditIssueCode.BASE_VERSION_NOT_DRAFT,
    ManualEditIssueCode.STALE_BASE_VERSION,
)


def base_state_issue(version) -> ManualEditIssue | None:
    """The reason ``version`` cannot be edited, or None when it can.

    A version is editable when its schedule's newest version is itself and its status
    is still ``DRAFT``. Phase 12 keeps one linear chain, so editing an older version is
    a conflict rather than a new branch.
    """
    if version.status != ScheduleStatus.DRAFT:
        return ManualEditIssue(
            code=ManualEditIssueCode.BASE_VERSION_NOT_DRAFT,
            message=(
                "Only a draft version can be edited manually; this version is "
                f"{version.get_status_display().lower()}."
            ),
            details={"status": version.status},
        )
    latest = (
        ScheduleVersion.objects.filter(schedule_id=version.schedule_id)
        .order_by("-version_number")
        .values_list("pk", flat=True)
        .first()
    )
    if latest != version.pk:
        return ManualEditIssue(
            code=ManualEditIssueCode.STALE_BASE_VERSION,
            message=(
                "This version is no longer the newest version of its schedule, so "
                "editing it would branch the version history."
            ),
            details={"latest_version_id": latest},
        )
    return None


class ManualEditService:
    """Validates and applies placement changes against one draft version."""

    def __init__(
        self,
        *,
        version,
        changes: Iterable[ManualEditChange],
        created_by=None,
        notes: str = "",
    ) -> None:
        self.version = version
        self.changes = tuple(changes)
        self.created_by = created_by
        self.notes = notes or ""

    # --- validate only -----------------------------------------------------

    def validate_only(self) -> ManualEditValidation:
        """Check the proposal without touching the database."""
        blocked = base_state_issue(self.version)
        if blocked is not None:
            return ManualEditValidation(
                base_version_id=self.version.pk,
                change_count=len(self.changes),
                issues=(blocked,),
            )
        return ManualEditValidator(
            version=self.version, changes=self.changes
        ).validate()

    # --- apply -------------------------------------------------------------

    def apply(self) -> ManualEditResult:
        """Validate the proposal and store it as the schedule's next version.

        The cheap validation runs first so an invalid request never opens a
        transaction. Inside the transaction the schedule row is locked, the base
        version's state is checked again, and the proposal is rebuilt from current data
        before anything is written, so a concurrent edit is detected instead of being
        overwritten.
        """
        blocked = base_state_issue(self.version)
        if blocked is not None:
            return self._refused(blocked.code, blocked.message)

        validation = ManualEditValidator(
            version=self.version, changes=self.changes
        ).validate()
        if not validation.valid:
            return self._refused(
                REASON_MANUAL_EDIT_VALIDATION_FAILED,
                "The proposed timetable violates a hard constraint, so no version "
                "was created.",
                validation=validation,
            )

        try:
            with transaction.atomic():
                locked_schedule = Schedule.objects.select_for_update().get(
                    pk=self.version.schedule_id
                )
                locked_version = ScheduleVersion.objects.get(pk=self.version.pk)

                blocked = base_state_issue(locked_version)
                if blocked is not None:
                    return self._refused(blocked.code, blocked.message)

                revalidated = ManualEditValidator(
                    version=locked_version, changes=self.changes
                ).validate()
                if not revalidated.valid:
                    return self._refused(
                        REASON_MANUAL_EDIT_VALIDATION_FAILED,
                        "The proposed timetable violates a hard constraint, so no "
                        "version was created.",
                        validation=revalidated,
                    )

                version = clone_version(
                    proposal=revalidated.proposal,
                    created_by=self.created_by,
                    notes=self.notes,
                )
        except IntegrityError:
            # The rollback removed the whole version, so the caller can simply retry;
            # the API answers a conflict instead of a server error.
            return self._refused(
                REASON_STALE_BASE_VERSION,
                "The version history changed while this edit was being stored, so "
                "nothing was written. Reload the schedule and try again.",
            )

        return ManualEditResult(
            persisted=True,
            version=version,
            schedule=locked_schedule,
            base_version_id=self.version.pk,
            entry_count=revalidated.proposal.entry_count,
            changed_entries=revalidated.proposal.changed_entry_count,
        )

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _refused(
        reason: str | None,
        message: str,
        *,
        validation: ManualEditValidation | None = None,
    ) -> ManualEditResult:
        """A refusal that wrote nothing."""
        return ManualEditResult(
            persisted=False,
            reason=reason or REASON_MANUAL_EDIT_VALIDATION_FAILED,
            message=message,
            validation=validation,
        )


__all__ = [
    "BASE_STATE_CODES",
    "ManualEditService",
    "base_state_issue",
]
