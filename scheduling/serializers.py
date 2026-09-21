"""API serializers for the calendar and time configuration.

Foreign keys are written as primary keys and read back as compact summaries, in
line with earlier phases. Nesting stays shallow: a slot or break shows its
working day (with the semester as an id), and a calendar exception shows a single
``target`` summary chosen by its scope instead of every possible target.

The cross-field rules (grid boundaries, overlap, exception scope and semester
range) live on the models and run through ``ModelCleanValidationMixin``, so
predictable violations answer ``400``. Grid writes are restricted to college
administrators by the views.
"""

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from academics.models import Department, Semester, StudentGroup, Weekday
from academics.permissions import user_can_manage_department
from academics.serializers import (
    DepartmentSummarySerializer,
    ModelCleanValidationMixin,
    SemesterSummarySerializer,
    StudentGroupSummarySerializer,
)
from resources.models import InstructorProfile, Room
from resources.serializers import (
    InstructorSummarySerializer,
    RoomSummarySerializer,
)
from scheduling.models import (
    BreakPeriod,
    CalendarException,
    ExceptionScope,
    TimeSlot,
    WorkingDay,
)


class WorkingDaySummarySerializer(serializers.ModelSerializer):
    """Compact working day representation used in nested payloads."""

    semester = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = WorkingDay
        fields = ("id", "semester", "day_of_week", "start_time", "end_time")
        read_only_fields = fields


class WorkingDaySerializer(serializers.ModelSerializer):
    """Read representation of a working day."""

    semester = SemesterSummarySerializer(read_only=True)
    day_of_week_code = serializers.SerializerMethodField()
    day_of_week_display = serializers.CharField(
        source="get_day_of_week_display",
        read_only=True,
    )

    class Meta:
        model = WorkingDay
        fields = (
            "id",
            "semester",
            "day_of_week",
            "day_of_week_code",
            "day_of_week_display",
            "start_time",
            "end_time",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    @extend_schema_field(serializers.CharField())
    def get_day_of_week_code(self, obj):
        """Enum name of the weekday, for example ``SUNDAY``.

        ``day_of_week`` carries the shared ``academics.Weekday`` integer value
        (Sunday = 0); this field gives the stable name for clients that prefer it.
        """
        if obj.day_of_week is None:
            return None
        return Weekday(obj.day_of_week).name


class WorkingDayWriteSerializer(
    ModelCleanValidationMixin, serializers.ModelSerializer
):
    """Write representation of a working day."""

    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())

    class Meta:
        model = WorkingDay
        fields = ("semester", "day_of_week", "start_time", "end_time", "is_active")


class TimeSlotSerializer(serializers.ModelSerializer):
    """Read representation of a teaching period."""

    working_day = WorkingDaySummarySerializer(read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = TimeSlot
        fields = (
            "id",
            "working_day",
            "sequence",
            "label",
            "start_time",
            "end_time",
            "duration_minutes",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class TimeSlotWriteSerializer(ModelCleanValidationMixin, serializers.ModelSerializer):
    """Write representation of a teaching period (``duration_minutes`` is derived)."""

    working_day = serializers.PrimaryKeyRelatedField(queryset=WorkingDay.objects.all())
    sequence = serializers.IntegerField(min_value=1)

    class Meta:
        model = TimeSlot
        fields = ("working_day", "sequence", "label", "start_time", "end_time", "is_active")


class BreakPeriodSerializer(serializers.ModelSerializer):
    """Read representation of a break."""

    working_day = WorkingDaySummarySerializer(read_only=True)

    class Meta:
        model = BreakPeriod
        fields = (
            "id",
            "working_day",
            "name",
            "start_time",
            "end_time",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class BreakPeriodWriteSerializer(
    ModelCleanValidationMixin, serializers.ModelSerializer
):
    """Write representation of a break."""

    working_day = serializers.PrimaryKeyRelatedField(queryset=WorkingDay.objects.all())

    class Meta:
        model = BreakPeriod
        fields = ("working_day", "name", "start_time", "end_time", "is_active")


class CalendarExceptionSerializer(serializers.ModelSerializer):
    """Read representation of a calendar exception.

    ``target`` is the single resource the scope points at (``null`` for
    college-wide exceptions) so unrelated target objects are never returned.
    """

    semester = SemesterSummarySerializer(read_only=True)
    exception_type_display = serializers.CharField(
        source="get_exception_type_display",
        read_only=True,
    )
    scope_type_display = serializers.CharField(
        source="get_scope_type_display",
        read_only=True,
    )
    target = serializers.SerializerMethodField()
    is_full_day = serializers.BooleanField(read_only=True)

    class Meta:
        model = CalendarException
        fields = (
            "id",
            "semester",
            "date",
            "exception_type",
            "exception_type_display",
            "scope_type",
            "scope_type_display",
            "target",
            "title",
            "description",
            "start_time",
            "end_time",
            "is_full_day",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    @extend_schema_field(
        PolymorphicProxySerializer(
            component_name="CalendarExceptionTarget",
            serializers=[
                DepartmentSummarySerializer,
                InstructorSummarySerializer,
                RoomSummarySerializer,
                StudentGroupSummarySerializer,
            ],
            resource_type_field_name=None,
        )
    )
    def get_target(self, obj):
        """Summary of the scope target, or None for a college-wide exception."""
        summary = None
        target = None
        if obj.scope_type == ExceptionScope.DEPARTMENT:
            target, summary = obj.department, DepartmentSummarySerializer
        elif obj.scope_type == ExceptionScope.INSTRUCTOR:
            target, summary = obj.instructor, InstructorSummarySerializer
        elif obj.scope_type == ExceptionScope.ROOM:
            target, summary = obj.room, RoomSummarySerializer
        elif obj.scope_type == ExceptionScope.STUDENT_GROUP:
            target, summary = obj.student_group, StudentGroupSummarySerializer
        if target is None or summary is None:
            return None
        return summary(target, context=self.context).data


class CalendarExceptionWriteSerializer(
    ModelCleanValidationMixin, serializers.ModelSerializer
):
    """Write representation of a calendar exception.

    The model validates the time shape, the scope/target pairing, the type/scope
    pairing and the semester range. On top of that, a department administrator may
    only target resources owned by their own department (college-wide exceptions
    stay with college administrators), so a client cannot widen its scope by
    sending different target ids.
    """

    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )
    instructor = serializers.PrimaryKeyRelatedField(
        queryset=InstructorProfile.objects.all(), required=False, allow_null=True
    )
    room = serializers.PrimaryKeyRelatedField(
        queryset=Room.objects.all(), required=False, allow_null=True
    )
    student_group = serializers.PrimaryKeyRelatedField(
        queryset=StudentGroup.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = CalendarException
        fields = (
            "semester",
            "date",
            "exception_type",
            "scope_type",
            "department",
            "instructor",
            "room",
            "student_group",
            "title",
            "description",
            "start_time",
            "end_time",
            "is_active",
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)

        user = getattr(self.context.get("request"), "user", None)
        if user is None or not user.is_authenticated or user.has_cross_department_access:
            return attrs

        instance = self.instance if self.instance is not None else CalendarException()
        for field_name, value in attrs.items():
            setattr(instance, field_name, value)

        if instance.scope_type == ExceptionScope.COLLEGE:
            raise serializers.ValidationError(
                {
                    "scope_type": (
                        "Only college administrators may manage college-wide exceptions."
                    )
                }
            )

        owning_department_id = instance.owning_department_id
        if not user_can_manage_department(user, owning_department_id):
            field_name = instance.scope_target_field or "scope_type"
            raise serializers.ValidationError(
                {field_name: "You may only manage exceptions for your own department."}
            )

        return attrs
