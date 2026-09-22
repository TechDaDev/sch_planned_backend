"""Project middleware for Phase 16.

One job: give every request a correlation id, expose it to the audit service and echo it
back in ``X-Request-ID`` so an operator can connect a response to its audit rows.

The incoming header is sanitized and length-capped before it is trusted for anything, and
it is never used to authorize a request.
"""

from __future__ import annotations

from scheduling.services.audit.context import (
    REQUEST_ID_HEADER,
    request_id_scope,
)


class AuditRequestIdMiddleware:
    """Attach a request id to the audit context for the duration of one request.

    Every request gets one: the sanitized incoming header when a proxy supplied a usable
    value, otherwise a generated id. The id is also set on the request object so the
    exception handler can answer with it, and it is echoed back in the response header.
    It is a correlation value only - it authorizes nothing, and a client cannot choose a
    value that is longer than the cap or contains control characters.
    """

    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request):
        header = request.META.get(f"HTTP_{REQUEST_ID_HEADER.upper().replace('-', '_')}")
        with request_id_scope(header) as request_id:
            request.request_id = request_id
            response = self.get_response(request)
            response[REQUEST_ID_HEADER] = request_id
        return response


__all__ = ["AuditRequestIdMiddleware"]
