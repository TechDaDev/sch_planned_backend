"""Per-request correlation id for audit events.

An audit row is more useful when it can be matched to the request that produced it, so
every request gets a short id: the incoming ``X-Request-ID`` when a proxy sent one
(sanitized and length-capped), otherwise a generated value. A context variable carries it
from the middleware down to the service, which keeps the id out of every service signature.

The id is operational metadata only. It is never used for authorization, and it never
contains anything derived from a credential.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

#: Header a proxy may use to supply a correlation id.
REQUEST_ID_HEADER = "X-Request-ID"

#: Longest accepted correlation id.
MAX_REQUEST_ID_LENGTH = 64

_SAFE_REQUEST_ID = re.compile(r"[^A-Za-z0-9._:-]+")

_current_request_id: ContextVar[str] = ContextVar("audit_request_id", default="")


def new_request_id() -> str:
    """A fresh correlation id."""
    return uuid.uuid4().hex


def sanitize_request_id(value: str | None) -> str:
    """Keep a client-supplied id short and boring, or return an empty string."""
    if not value:
        return ""
    cleaned = _SAFE_REQUEST_ID.sub("-", str(value)).strip("-")
    return cleaned[:MAX_REQUEST_ID_LENGTH]


def current_request_id() -> str:
    """The correlation id of the request being served, or an empty string."""
    return _current_request_id.get()


@contextmanager
def request_id_scope(value: str | None) -> Iterator[str]:
    """Run a block with ``value`` as the current correlation id.

    Used by the middleware for HTTP requests, and by tests and management commands that
    want a deterministic id.
    """
    token = _current_request_id.set(sanitize_request_id(value) or new_request_id())
    try:
        yield _current_request_id.get()
    finally:
        _current_request_id.reset(token)


__all__ = [
    "MAX_REQUEST_ID_LENGTH",
    "REQUEST_ID_HEADER",
    "current_request_id",
    "new_request_id",
    "request_id_scope",
    "sanitize_request_id",
]
