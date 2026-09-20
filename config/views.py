"""Project-level API views that do not belong to a domain app."""

from drf_spectacular.utils import inline_serializer, extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


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
