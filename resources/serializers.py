"""API serializers for instructor resources.

Foreign keys are written as primary keys and read back as compact summaries, in
line with Phase 2/3. Representations stay shallow: an assignment exposes its
offering and course one level up instead of nesting component → offering →
course → semester.

Payload authorization reuses ``DepartmentScopeWriteMixin`` (foreign-key ids can
never place a record outside the writer's department), and the cross-field rules
(workload limits, account linkage, window overlap, assignment eligibility) run
through ``ModelCleanValidationMixin`` so predictable violations answer 400.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from academics.models import Department, Semester, TeachingComponent
from academics.serializers import (
    CourseOfferingSummarySerializer,
    DepartmentScopeWriteMixin,
    DepartmentSummarySerializer,
    ModelCleanValidationMixin,
    SemesterSummarySerializer,
    TeachingComponentSummarySerializer,
)
from accounts.models import User
from resources.models import (
    InstructorAvailability,
    InstructorDepartmentAccess,
    InstructorPreference,
    InstructorProfile,
    TeachingAssignment,
)


class InstructorAccountSerializer(serializers.ModelSerializer):
    """Minimal linked-account representation: identity only, no credentials."""

    class Meta:
        model = User
        fields = ("id", "username")
        read_only_fields = fields


class InstructorSummarySerializer(serializers.ModelSerializer):
    """Compact instructor representation used in nested payloads."""

    class Meta:
        model = InstructorProfile
        fields = ("id", "full_name", "staff_code")
        read_only_fields = fields


class InstructorProfileSerializer(serializers.ModelSerializer):
    """Read representation of an instructor profile."""

    primary_department = DepartmentSummarySerializer(read_only=True)
    user = InstructorAccountSerializer(read_only=True)

    class Meta:
        model = InstructorProfile
        fields = (
            "id",
            "full_name",
            "staff_code",
            "academic_title",
            "primary_department",
            "sharing_scope",
            "max_weekly_hours",
            "max_daily_hours",
            "user",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class InstructorProfileWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of an instructor profile.

    Linking an account never mutates the account: the user must already hold the
    ``INSTRUCTOR`` role and belong to the profile's primary department, and the
    model ``clean()`` rejects anything else.
    """

    primary_department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all()
    )
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )

    department_scope_fields = {"primary_department": "pk"}

    class Meta:
        model = InstructorProfile
        fields = (
            "full_name",
            "staff_code",
            "academic_title",
            "primary_department",
            "sharing_scope",
            "max_weekly_hours",
            "max_daily_hours",
            "user",
            "is_active",
        )


class InstructorDepartmentAccessSerializer(serializers.ModelSerializer):
    """Read representation of an instructor sharing grant."""

    instructor = InstructorSummarySerializer(read_only=True)
    department = DepartmentSummarySerializer(read_only=True)

    class Meta:
        model = InstructorDepartmentAccess
        fields = (
            "id",
            "instructor",
            "department",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class InstructorDepartmentAccessWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of an instructor sharing grant.

    Only the department that owns the instructor may grant or revoke access to
    it; the target department cannot grant itself access.
    """

    instructor = serializers.PrimaryKeyRelatedField(
        queryset=InstructorProfile.objects.all()
    )
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())

    department_scope_fields = {"instructor": "primary_department"}

    class Meta:
        model = InstructorDepartmentAccess
        fields = ("instructor", "department", "is_active")


class InstructorAvailabilitySerializer(serializers.ModelSerializer):
    """Read representation of an availability window."""

    instructor = InstructorSummarySerializer(read_only=True)
    semester = SemesterSummarySerializer(read_only=True)
    day_of_week_display = serializers.CharField(
        source="get_day_of_week_display",
        read_only=True,
    )

    class Meta:
        model = InstructorAvailability
        fields = (
            "id",
            "instructor",
            "semester",
            "day_of_week",
            "day_of_week_display",
            "start_time",
            "end_time",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class InstructorAvailabilityWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of an availability window."""

    instructor = serializers.PrimaryKeyRelatedField(
        queryset=InstructorProfile.objects.all()
    )
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())

    department_scope_fields = {"instructor": "primary_department"}

    class Meta:
        model = InstructorAvailability
        fields = (
            "instructor",
            "semester",
            "day_of_week",
            "start_time",
            "end_time",
            "is_active",
        )


class InstructorPreferenceSerializer(serializers.ModelSerializer):
    """Read representation of a soft scheduling preference."""

    instructor = InstructorSummarySerializer(read_only=True)
    semester = SemesterSummarySerializer(read_only=True)
    day_of_week_display = serializers.CharField(
        source="get_day_of_week_display",
        read_only=True,
    )
    preference_type_display = serializers.CharField(
        source="get_preference_type_display",
        read_only=True,
    )

    class Meta:
        model = InstructorPreference
        fields = (
            "id",
            "instructor",
            "semester",
            "day_of_week",
            "day_of_week_display",
            "start_time",
            "end_time",
            "preference_type",
            "preference_type_display",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class InstructorPreferenceWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a soft scheduling preference."""

    instructor = serializers.PrimaryKeyRelatedField(
        queryset=InstructorProfile.objects.all()
    )
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())

    department_scope_fields = {"instructor": "primary_department"}

    class Meta:
        model = InstructorPreference
        fields = (
            "instructor",
            "semester",
            "day_of_week",
            "start_time",
            "end_time",
            "preference_type",
            "is_active",
        )


class TeachingAssignmentSerializer(serializers.ModelSerializer):
    """Read representation of a teaching assignment.

    The offering (and its course) is lifted one level up so the payload carries
    course/offering context without deep nesting.
    """

    instructor = InstructorSummarySerializer(read_only=True)
    teaching_component = TeachingComponentSummarySerializer(read_only=True)
    offering = serializers.SerializerMethodField()

    class Meta:
        model = TeachingAssignment
        fields = (
            "id",
            "assignment_role",
            "instructor",
            "teaching_component",
            "offering",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    @extend_schema_field(CourseOfferingSummarySerializer)
    def get_offering(self, obj):
        return CourseOfferingSummarySerializer(
            obj.teaching_component.offering, context=self.context
        ).data


class TeachingAssignmentWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a teaching assignment.

    The component must be managed by the writer's department; instructor
    eligibility (own or appropriately shared instructors) is enforced by the
    model ``clean()`` for every writer, including college administrators.
    """

    teaching_component = serializers.PrimaryKeyRelatedField(
        queryset=TeachingComponent.objects.all()
    )
    instructor = serializers.PrimaryKeyRelatedField(
        queryset=InstructorProfile.objects.all()
    )

    department_scope_fields = {"teaching_component": "offering__managing_department"}

    class Meta:
        model = TeachingAssignment
        fields = ("teaching_component", "instructor", "assignment_role", "is_active")
