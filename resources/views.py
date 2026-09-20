"""Instructor resource API views.

Phase 4 reuses the existing building blocks instead of inventing a second
authorization framework: the read/write serializer split, the "no hard delete"
base viewset and the department-scoped visibility mixin all come from
``academics.views``, and write ownership uses ``IsDepartmentScopedManager`` with
per-view ``management_department_lookups`` (every lookup must resolve to the
writer's own department).

Read visibility comes from ``resources.permissions``:

* instructors follow ownership + sharing + joint teaching;
* availability and preferences follow ownership + sharing only;
* assignments follow Phase 3 teaching-component visibility.
"""

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated

from academics.models import Department, Semester, TeachingComponent
from academics.permissions import IsDepartmentScopedManager
from academics.views import AcademicStructureViewSet, DepartmentVisibilityQuerysetMixin
from resources.models import (
    InstructorAvailability,
    InstructorDepartmentAccess,
    InstructorPreference,
    InstructorProfile,
    TeachingAssignment,
)
from resources.permissions import (
    visible_assignments_filter,
    visible_availability_filter,
    visible_instructor_access_filter,
    visible_instructors_filter,
    visible_preferences_filter,
)
from resources.serializers import (
    InstructorAvailabilitySerializer,
    InstructorAvailabilityWriteSerializer,
    InstructorDepartmentAccessSerializer,
    InstructorDepartmentAccessWriteSerializer,
    InstructorPreferenceSerializer,
    InstructorPreferenceWriteSerializer,
    InstructorProfileSerializer,
    InstructorProfileWriteSerializer,
    TeachingAssignmentSerializer,
    TeachingAssignmentWriteSerializer,
)

INSTRUCTOR_TAGS = ["instructors"]

_BOOLEAN_TRUE = {"1", "true", "yes", "on"}
_BOOLEAN_FALSE = {"0", "false", "no", "off"}


class QueryParameterFilterMixin:
    """Allow-listed exact-match query parameter filtering without new dependencies.

    Every field in ``filter_fields`` may be supplied as a query parameter; values
    are parsed through the model field so a bad value answers ``400`` instead of
    raising a database error.
    """

    filter_fields: tuple[str, ...] = ()

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        for field_name in self.filter_fields:
            raw_value = self.request.query_params.get(field_name)
            if raw_value in (None, ""):
                continue
            value = self._parse_filter_value(queryset.model, field_name, raw_value)
            queryset = queryset.filter(**{field_name: value})
        return queryset

    @staticmethod
    def _parse_filter_value(model, field_name: str, raw_value: str):
        try:
            model_field = model._meta.get_field(field_name.split("__")[0])
        except FieldDoesNotExist as exc:  # pragma: no cover - developer error
            raise ImproperlyConfigured(
                f"Unknown filter field '{field_name}' for {model.__name__}."
            ) from exc

        if isinstance(model_field, models.BooleanField):
            lowered = str(raw_value).strip().lower()
            if lowered in _BOOLEAN_TRUE:
                return True
            if lowered in _BOOLEAN_FALSE:
                return False
            raise DRFValidationError(
                {field_name: "Use true or false for this filter."}
            )

        try:
            return model_field.to_python(raw_value)
        except (DjangoValidationError, ValueError, TypeError) as exc:
            raise DRFValidationError(
                {field_name: "Invalid filter value."}
            ) from exc


@extend_schema(tags=INSTRUCTOR_TAGS)
class InstructorProfileViewSet(
    QueryParameterFilterMixin,
    DepartmentVisibilityQuerysetMixin,
    AcademicStructureViewSet,
):
    """Instructor profiles: sharable department-owned teaching resources."""

    queryset = InstructorProfile.objects.select_related(
        "primary_department", "user"
    )
    read_serializer_class = InstructorProfileSerializer
    write_serializer_class = InstructorProfileWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = ("primary_department",)
    filter_fields = ("primary_department", "sharing_scope", "is_active")

    def visibility_filter(self, user):
        return visible_instructors_filter(user)


@extend_schema(tags=INSTRUCTOR_TAGS)
class InstructorDepartmentAccessViewSet(
    QueryParameterFilterMixin,
    DepartmentVisibilityQuerysetMixin,
    AcademicStructureViewSet,
):
    """Explicit sharing grants from an instructor's primary department."""

    queryset = InstructorDepartmentAccess.objects.select_related(
        "instructor", "instructor__primary_department", "department"
    )
    read_serializer_class = InstructorDepartmentAccessSerializer
    write_serializer_class = InstructorDepartmentAccessWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = ("instructor__primary_department",)
    filter_fields = ("instructor", "department", "is_active")

    def visibility_filter(self, user):
        return visible_instructor_access_filter(user)


@extend_schema(tags=INSTRUCTOR_TAGS)
class InstructorAvailabilityViewSet(
    QueryParameterFilterMixin,
    DepartmentVisibilityQuerysetMixin,
    AcademicStructureViewSet,
):
    """Recurring hard weekly availability windows."""

    queryset = InstructorAvailability.objects.select_related(
        "instructor",
        "semester",
        "semester__academic_year",
    )
    read_serializer_class = InstructorAvailabilitySerializer
    write_serializer_class = InstructorAvailabilityWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = ("instructor__primary_department",)
    filter_fields = ("instructor", "semester", "day_of_week", "is_active")

    def visibility_filter(self, user):
        return visible_availability_filter(user)


@extend_schema(tags=INSTRUCTOR_TAGS)
class InstructorPreferenceViewSet(
    QueryParameterFilterMixin,
    DepartmentVisibilityQuerysetMixin,
    AcademicStructureViewSet,
):
    """Soft scheduling preferences (never hard unavailability)."""

    queryset = InstructorPreference.objects.select_related(
        "instructor",
        "semester",
        "semester__academic_year",
    )
    read_serializer_class = InstructorPreferenceSerializer
    write_serializer_class = InstructorPreferenceWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = ("instructor__primary_department",)
    filter_fields = (
        "instructor",
        "semester",
        "day_of_week",
        "preference_type",
        "is_active",
    )

    def visibility_filter(self, user):
        return visible_preferences_filter(user)


@extend_schema(tags=INSTRUCTOR_TAGS)
class TeachingAssignmentViewSet(
    QueryParameterFilterMixin,
    DepartmentVisibilityQuerysetMixin,
    AcademicStructureViewSet,
):
    """Instructor assignments to teaching components.

    Only the department managing the offering may write them, even when another
    department's instructor is the one assigned.
    """

    queryset = TeachingAssignment.objects.select_related(
        "instructor",
        "instructor__primary_department",
        "teaching_component",
        "teaching_component__offering",
        "teaching_component__offering__course",
        "teaching_component__offering__managing_department",
    )
    read_serializer_class = TeachingAssignmentSerializer
    write_serializer_class = TeachingAssignmentWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = ("teaching_component__offering__managing_department",)
    filter_fields = ("instructor", "teaching_component", "assignment_role", "is_active")

    def visibility_filter(self, user):
        return visible_assignments_filter(user)


class MyTeachingAssignmentsView(generics.ListAPIView):
    """Active teaching assignments of the authenticated instructor.

    Returns an empty list when the account has no instructor profile, so the
    future Flutter instructor app gets a stable response instead of an error.
    """

    serializer_class = TeachingAssignmentSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=INSTRUCTOR_TAGS,
        summary="My teaching assignments",
        description=(
            "Active teaching assignments of the instructor linked to the authenticated "
            "account. Empty when the account has no instructor profile."
        ),
        responses={200: TeachingAssignmentSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        profile = getattr(self.request.user, "instructor_profile", None)
        if profile is None:
            return TeachingAssignment.objects.none()
        return (
            TeachingAssignment.objects.filter(instructor=profile, is_active=True)
            .select_related(
                "instructor",
                "instructor__primary_department",
                "teaching_component",
                "teaching_component__offering",
                "teaching_component__offering__course",
            )
            .order_by("teaching_component__offering__course__code", "teaching_component_id")
        )

