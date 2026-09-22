"""Project-level API views that do not belong to a domain app.

Three public health probes, deliberately minimal:

``/api/health/``
    the original Phase 0 liveness probe, kept unchanged for compatibility;
``/api/health/live/``
    liveness. Answers without touching the database, because a process that cannot reach
    its database is still alive and should not be restarted by an orchestrator;
``/api/health/ready/``
    readiness. Runs a single ``SELECT 1`` and answers ``503`` when the database is
    unavailable, so traffic is only sent to a process that can actually serve it.

None of them reports a path, host, vendor, version, environment value or exception text,
and none of them mutates anything.
"""

from django.db import DatabaseError, connections
from drf_spectacular.utils import inline_serializer, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers


class HealthView(APIView):
    """Unauthenticated liveness probe for the API."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["system"],
        summary="Service health",
        description="Returns the current status of the backend service.",
        responses={
            200: inline_serializer(
                name="HealthResponse",
                fields={
                    "status": serializers.CharField(),
                    "service": serializers.CharField(),
                },
            )
        },
    )
    def get(self, request):
        return Response({"status": "ok", "service": "sch_planner_backend"})


class HealthLiveView(APIView):
    """Process liveness. Performs no database query at all."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["system"],
        summary="Liveness probe",
        description=(
            "Answers ``200`` while the process serves requests. It never queries the "
            "database, so it does not fail when the database is unavailable."
        ),
        responses={
            200: inline_serializer(
                name="HealthLiveResponse",
                fields={"status": serializers.CharField()},
            )
        },
    )
    def get(self, request):
        return Response({"status": "ok"})


class HealthReadyView(APIView):
    """Readiness. One lightweight database round trip, nothing else."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["system"],
        summary="Readiness probe",
        description=(
            "Runs a single ``SELECT 1`` through the configured database connection and "
            "answers ``200`` when it succeeds or ``503`` when it does not. The response "
            "never names the database, its vendor or the underlying error."
        ),
        responses={
            200: inline_serializer(
                name="HealthReadyResponse",
                fields={"status": serializers.CharField()},
            ),
            503: inline_serializer(
                name="HealthUnavailableResponse",
                fields={"status": serializers.CharField()},
            ),
        },
    )
    def get(self, request):
        if _database_available():
            return Response({"status": "ok"})
        return Response(
            {"status": "unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


def _database_available() -> bool:
    """True when a trivial query succeeds. Any failure means "not ready"."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return False
    except Exception:  # pragma: no cover - a driver-level failure is still "not ready"
        return False
    return True
