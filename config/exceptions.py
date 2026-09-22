"""API exception handling for the release candidate.

Two jobs, and nothing else:

* every documented DRF error (``400``/``401``/``403``/``404``/``405``/``409``/``415``/
  ``429``) keeps exactly the response it had in Phases 0-16, because those handlers
  already answer with a controlled body and the acceptance tests depend on it;
* an **unhandled** server exception never leaks implementation detail to a client. The
  response is generic JSON, and the traceback is logged server-side with enough context to
  find it (request id, method, path, authenticated user id) and nothing sensitive.

The request id comes from the Phase 16 middleware. It is a correlation value, never an
authorization credential, and it is omitted only when the request genuinely has none.
"""

from __future__ import annotations

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("sch_planner.api")

#: Code returned for an unhandled server error.
INTERNAL_ERROR_CODE = "INTERNAL_SERVER_ERROR"

#: Message returned for an unhandled server error. Deliberately generic.
INTERNAL_ERROR_DETAIL = "Internal server error."


def api_exception_handler(exc, context):
    """DRF's handler, plus a generic answer for anything it does not handle.

    Returns ``None`` only when no response could be produced *and* the exception is one
    Django itself should process further (a 404 from URL resolution, for example). Server
    errors are always answered here, so a client sees JSON rather than an HTML error page,
    a stack trace or the exception text.
    """
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    request = context.get("request")
    _log_unhandled(exc, request)
    return Response(
        _error_body(request),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _error_body(request) -> dict[str, str]:
    body = {"detail": INTERNAL_ERROR_DETAIL, "code": INTERNAL_ERROR_CODE}
    request_id = getattr(request, "request_id", None) or _request_id_from_context(request)
    if request_id:
        body["request_id"] = str(request_id)
    return body


def _request_id_from_context(request) -> str | None:
    """The request id recorded by the audit context, when the middleware ran."""
    if request is None:
        return None
    try:
        from scheduling.services.audit.context import current_request_id

        return current_request_id()
    except Exception:  # pragma: no cover - the context is not critical to the response
        return None


def _log_unhandled(exc, request) -> None:
    """Log an unhandled exception with correlation context and no request payload."""
    if request is None:
        logger.exception("Unhandled API error: %s", type(exc).__name__)
        return

    user = getattr(request, "user", None)
    user_id = getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
    logger.exception(
        "Unhandled API error on %s %s (request_id=%s user_id=%s, debug=%s)",
        getattr(request, "method", "?"),
        getattr(request, "path", "?"),
        _error_body(request).get("request_id", "-"),
        user_id if user_id is not None else "-",
        settings.DEBUG,
    )


__all__ = [
    "INTERNAL_ERROR_CODE",
    "INTERNAL_ERROR_DETAIL",
    "api_exception_handler",
]
