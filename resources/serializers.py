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
    Room,
    RoomAvailability,
    RoomCapability,
    RoomCapabilityAssignment,
    RoomDepartmentAccess,
    RoomType,
    TeachingAssignment,
    TeachingComponentCapabilityRequirement,
    TeachingComponentRoomRequirement,
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


# --- Phase 5: rooms, laboratories, capabilities and requirements -------------


class RoomTypeSummarySerializer(serializers.ModelSerializer):
    """Compact room type representation used in nested payloads."""

    class Meta:
        model = RoomType
        fields = ("id", "name", "code")
        read_only_fields = fields


class RoomCapabilitySummarySerializer(serializers.ModelSerializer):
    """Compact room capability representation used in nested payloads."""

    class Meta:
        model = RoomCapability
        fields = ("id", "name", "code")
        read_only_fields = fields


class RoomSummarySerializer(serializers.ModelSerializer):
    """Compact room representation used in nested payloads."""

    class Meta:
        model = Room
        fields = ("id", "name", "code")
        read_only_fields = fields


class RoomTypeSerializer(serializers.ModelSerializer):
    """College-wide room type lookup.

    Reads are open to authenticated users; writes are restricted to college
    administrators by the view, so the college-wide vocabulary cannot be
    redefined by a department.
    """

    class Meta:
        model = RoomType
        fields = ("id", "name", "code", "description", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class RoomCapabilitySerializer(serializers.ModelSerializer):
    """College-wide room capability lookup (same permission model as room types)."""

    class Meta:
        model = RoomCapability
        fields = ("id", "name", "code", "description", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class RoomSerializer(serializers.ModelSerializer):
    """Read representation of a room."""

    owner_department = DepartmentSummarySerializer(read_only=True)
    room_type = RoomTypeSummarySerializer(read_only=True)

    class Meta:
        model = Room
        fields = (
            "id",
            "name",
            "code",
            "owner_department",
            "room_type",
            "capacity",
            "sharing_scope",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class RoomWriteSerializer(DepartmentScopeWriteMixin, serializers.ModelSerializer):
    """Write representation of a room (``owner_department`` as a primary key).

    ``capacity`` is declared explicitly with ``min_value=1`` so a zero capacity
    answers ``400`` rather than reaching the database check constraint.
    """

    owner_department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all()
    )
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.all())
    capacity = serializers.IntegerField(min_value=1)

    department_scope_fields = {"owner_department": "pk"}

    class Meta:
        model = Room
        fields = (
            "name",
            "code",
            "owner_department",
            "room_type",
            "capacity",
            "sharing_scope",
            "is_active",
        )


class RoomDepartmentAccessSerializer(serializers.ModelSerializer):
    """Read representation of a room sharing grant."""

    room = RoomSummarySerializer(read_only=True)
    department = DepartmentSummarySerializer(read_only=True)

    class Meta:
        model = RoomDepartmentAccess
        fields = ("id", "room", "department", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class RoomDepartmentAccessWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a room sharing grant.

    Only the owning department may grant or revoke access to its room; a
    consuming department cannot grant itself access.
    """

    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all())
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())

    department_scope_fields = {"room": "owner_department"}

    class Meta:
        model = RoomDepartmentAccess
        fields = ("room", "department", "is_active")


class RoomCapabilityAssignmentSerializer(serializers.ModelSerializer):
    """Read representation of a room capability assignment."""

    room = RoomSummarySerializer(read_only=True)
    capability = RoomCapabilitySummarySerializer(read_only=True)

    class Meta:
        model = RoomCapabilityAssignment
        fields = ("id", "room", "capability", "created_at")
        read_only_fields = fields


class RoomCapabilityAssignmentWriteSerializer(
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a room capability assignment."""

    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all())
    capability = serializers.PrimaryKeyRelatedField(queryset=RoomCapability.objects.all())

    department_scope_fields = {"room": "owner_department"}

    class Meta:
        model = RoomCapabilityAssignment
        fields = ("room", "capability")


class RoomAvailabilitySerializer(serializers.ModelSerializer):
    """Read representation of a room availability window."""

    room = RoomSummarySerializer(read_only=True)
    semester = SemesterSummarySerializer(read_only=True)
    day_of_week_display = serializers.CharField(
        source="get_day_of_week_display",
        read_only=True,
    )

    class Meta:
        model = RoomAvailability
        fields = (
            "id",
            "room",
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


class RoomAvailabilityWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a room availability window."""

    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all())
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())

    department_scope_fields = {"room": "owner_department"}

    class Meta:
        model = RoomAvailability
        fields = ("room", "semester", "day_of_week", "start_time", "end_time", "is_active")


class TeachingComponentRoomRequirementSerializer(serializers.ModelSerializer):
    """Read representation of a teaching component's room requirement.

    Derived values (``expected_student_count``, ``effective_minimum_capacity``
    and the capability summaries) are read-only.
    """

    teaching_component = TeachingComponentSummarySerializer(read_only=True)
    required_room_type = RoomTypeSummarySerializer(read_only=True)
    expected_student_count = serializers.IntegerField(read_only=True)
    effective_minimum_capacity = serializers.IntegerField(read_only=True)
    required_capabilities = serializers.SerializerMethodField()

    class Meta:
        model = TeachingComponentRoomRequirement
        fields = (
            "id",
            "teaching_component",
            "required_room_type",
            "minimum_capacity",
            "expected_student_count",
            "effective_minimum_capacity",
            "required_capabilities",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    @extend_schema_field(RoomCapabilitySummarySerializer(many=True))
    def get_required_capabilities(self, obj):
        capabilities = [
            link.capability for link in obj.capability_requirements.all()
        ]
        return RoomCapabilitySummarySerializer(capabilities, many=True).data


class TeachingComponentRoomRequirementWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a room requirement.

    Only the department managing the component's offering may write it; derived
    capacity values are never accepted from the client.
    """

    teaching_component = serializers.PrimaryKeyRelatedField(
        queryset=TeachingComponent.objects.all()
    )
    required_room_type = serializers.PrimaryKeyRelatedField(
        queryset=RoomType.objects.all(),
        required=False,
        allow_null=True,
    )
    minimum_capacity = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )

    department_scope_fields = {"teaching_component": "offering__managing_department"}

    class Meta:
        model = TeachingComponentRoomRequirement
        fields = (
            "teaching_component",
            "required_room_type",
            "minimum_capacity",
            "is_active",
        )


class TeachingComponentRoomRequirementSummarySerializer(serializers.ModelSerializer):
    """Compact room requirement representation used in nested payloads."""

    teaching_component = TeachingComponentSummarySerializer(read_only=True)

    class Meta:
        model = TeachingComponentRoomRequirement
        fields = ("id", "teaching_component", "minimum_capacity")
        read_only_fields = fields


class TeachingComponentCapabilityRequirementSerializer(serializers.ModelSerializer):
    """Read representation of a required capability."""

    room_requirement = TeachingComponentRoomRequirementSummarySerializer(read_only=True)
    capability = RoomCapabilitySummarySerializer(read_only=True)

    class Meta:
        model = TeachingComponentCapabilityRequirement
        fields = ("id", "room_requirement", "capability", "created_at")
        read_only_fields = fields


class TeachingComponentCapabilityRequirementWriteSerializer(
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a required capability."""

    room_requirement = serializers.PrimaryKeyRelatedField(
        queryset=TeachingComponentRoomRequirement.objects.all()
    )
    capability = serializers.PrimaryKeyRelatedField(
        queryset=RoomCapability.objects.all()
    )

    department_scope_fields = {
        "room_requirement": "teaching_component__offering__managing_department"
    }

    class Meta:
        model = TeachingComponentCapabilityRequirement
        fields = ("room_requirement", "capability")
