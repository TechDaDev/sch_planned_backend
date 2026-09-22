"""The audit writer.

:class:`AuditService` is the only code that creates an :class:`~scheduling.models.AuditEvent`.
It is deliberately small: build the row, sanitize the metadata, save it inside whatever
transaction the caller already opened.

Two rules keep the trail trustworthy:

* **the caller's transaction wins.** No ``transaction.atomic()`` is opened here, so an
  event commits with the mutation it describes and disappears when that mutation rolls
  back. Audit writes therefore need no retry logic and no outbox.
* **no exceptions are swallowed.** If the row cannot be written, the exception reaches
  the caller and fails the operation. A critical timetable change must not commit
  unaudited.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from scheduling.models import AuditEvent
from scheduling.services.audit.context import current_request_id

#: Metadata keys that are never stored, whatever a caller passes. Matching is
#: case-insensitive and substring-based, so ``password_hash``, ``access_token`` and
#: ``authorization_header`` are all refused.
FORBIDDEN_METADATA_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "jwt",
    "authorization",
    "auth_header",
    "cookie",
    "session_key",
    "credential",
    "private_key",
    "api_key",
    "hash",
    "salt",
    "dsn",
    "database_url",
    "environment",
    "environ",
)

#: Longest string kept in metadata. Longer values are truncated, so a stray payload
#: cannot bloat the trail.
MAX_METADATA_STRING = 300

#: Most keys kept in one metadata object, so nothing can turn a row into a document dump.
MAX_METADATA_KEYS = 25

_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return only safe, structured, primitive metadata.

    Nested mappings and lists are kept one level deep when their contents are primitives;
    anything else - model instances, bytes, file handles, callables - is dropped rather
    than stringified, because a stringified object is exactly how a payload or a secret
    leaks into an audit table.
    """
    if not metadata:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if len(cleaned) >= MAX_METADATA_KEYS:
            break
        safe_key = _safe_key(str(key))
        if not safe_key or _is_forbidden(safe_key):
            continue
        safe_value = _safe_value(value)
        if safe_value is None and value is not None:
            continue
        cleaned[safe_key] = safe_value
    return cleaned


def _safe_key(key: str) -> str:
    return _SAFE_KEY.sub("_", key).strip("_")[:64]


def _is_forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in FORBIDDEN_METADATA_KEY_PARTS)


def _safe_value(value: Any) -> Any:
    """One primitive, a short list of primitives, or a one-level mapping of them."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_METADATA_STRING]
    if isinstance(value, (list, tuple, set)):
        items = [_safe_value(item) for item in value]
        return [item for item in items if item is not None][:50]
    if isinstance(value, Mapping):
        nested = {
            _safe_key(str(key)): _safe_value(item)
            for key, item in list(value.items())[:MAX_METADATA_KEYS]
        }
        return {
            key: item
            for key, item in nested.items()
            if key and not _is_forbidden(key) and item is not None
        }
    # Model instances, bytes, datetimes and anything else are not metadata.
    return None


class AuditService:
    """Writes audit events. The only writer in the project."""

    @staticmethod
    def record(
        *,
        action: str,
        actor=None,
        department=None,
        semester=None,
        schedule=None,
        schedule_version=None,
        object_type: str = "",
        object_id: Any = "",
        metadata: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AuditEvent:
        """Persist one audit event and return it.

        ``actor`` is a user object or ``None``. The event stores the live foreign key
        *and* a username/role snapshot, so the row still reads correctly after the
        account is renamed or deleted. ``request_id`` defaults to the id of the request
        being served, when there is one.
        """
        return AuditEvent.objects.create(
            action=action,
            actor=actor if getattr(actor, "is_authenticated", True) else None,
            actor_username_snapshot=_actor_username(actor),
            actor_role_snapshot=_actor_role(actor),
            department=department,
            semester=semester,
            schedule=schedule,
            schedule_version=schedule_version,
            object_type=(object_type or "")[:64],
            object_id=_object_id(object_id),
            request_id=(request_id if request_id is not None else current_request_id())[
                :64
            ],
            metadata=sanitize_metadata(metadata),
        )


def _actor_username(actor) -> str:
    if actor is None:
        return ""
    getter = getattr(actor, "get_username", None)
    if callable(getter):
        try:
            return str(getter())[:150]
        except Exception:  # pragma: no cover - a broken user object must not block audit
            return ""
    return str(getattr(actor, "username", ""))[:150]


def _actor_role(actor) -> str:
    if actor is None:
        return ""
    return str(getattr(actor, "role", "") or "")[:32]


def _object_id(value: Any) -> str:
    """Text form of a semantic object id, truncated to the column length."""
    if value is None or value == "":
        return ""
    return str(value)[:128]


__all__ = [
    "FORBIDDEN_METADATA_KEY_PARTS",
    "MAX_METADATA_KEYS",
    "MAX_METADATA_STRING",
    "AuditService",
    "sanitize_metadata",
]
