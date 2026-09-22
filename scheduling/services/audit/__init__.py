"""The audit trail.

One package, one job: record that a successful, security- or operations-significant
scheduling operation happened, and let an authorized reader see it later.

``service``
    :class:`AuditService`, the only writer, plus the metadata sanitizer that keeps
    secrets and payloads out of the trail.
``actions``
    one typed recorder per audited operation, so calling code states *what happened*
    instead of assembling generic fields.
``context``
    the per-request correlation id, so an operator can connect an audit row to the
    request that produced it.

The trail is written inside the transaction of the operation it describes, so a
rolled-back mutation leaves no event behind, and a failure to record a critical
operation fails that operation rather than producing an unaudited change.
"""

from scheduling.services.audit.actions import (
    record_college_draft,
    record_department_draft,
    record_manual_edit,
    record_semester_plan_import,
    record_workflow_transition,
)
from scheduling.services.audit.context import current_request_id, request_id_scope
from scheduling.services.audit.service import AuditService, sanitize_metadata

__all__ = [
    "AuditService",
    "current_request_id",
    "record_college_draft",
    "record_department_draft",
    "record_manual_edit",
    "record_semester_plan_import",
    "record_workflow_transition",
    "request_id_scope",
    "sanitize_metadata",
]
