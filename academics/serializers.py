"""API serializers for the academic structure.

Representation strategy: foreign keys are written as primary keys and read back
as compact nested summaries, so list, detail and write responses stay
consistent. Nesting goes one level deep (the direct parent) to avoid large
payloads and recursive structures.

The cross-field academic invariants live on the models (``clean()``); the
``ModelCleanValidationMixin`` makes API writes enforce exactly the same rules so
predictable invalid input yields HTTP 400 instead of a database error.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from academics.models import (
    AcademicYear,
    College,
    Course,
    CourseOffering,
    Department,
    Semester,
    StudentGroup,
    StudyProgram,
    StudyStage,
    TeachingComponent,
    TeachingComponentGroup,
)
from academics.permissions import resolve_department_id, user_can_manage_department


class CollegeSummarySerializer(serializers.ModelSerializer):
    """Compact college representation used in nested payloads."""

    class Meta:
        model = College
        fields = ("id", "name", "code")
        read_only_fields = fields


class DepartmentSummarySerializer(serializers.ModelSerializer):
    """Compact department representation used in nested payloads."""

    class Meta:
        model = Department
        fields = ("id", "name", "code")
        read_only_fields = fields


class AcademicYearSummarySerializer(serializers.ModelSerializer):
    """Compact academic year representation used in nested payloads."""

    class Meta:
        model = AcademicYear
        fields = ("id", "start_year", "end_year")
        read_only_fields = fields


class StudyProgramSummarySerializer(serializers.ModelSerializer):
    """Compact study program representation used in nested payloads."""

    class Meta:
        model = StudyProgram
        fields = ("id", "name", "code", "study_type")
        read_only_fields = fields


class StudyStageSummarySerializer(serializers.ModelSerializer):
    """Compact study stage representation used in nested payloads."""

    class Meta:
        model = StudyStage
        fields = ("id", "number", "name")
        read_only_fields = fields


class StudentGroupSummarySerializer(serializers.ModelSerializer):
    """Compact student group representation used in nested payloads.

    Deliberately shallow so subgroup trees never serialise recursively.
    """

    class Meta:
        model = StudentGroup
        fields = ("id", "name", "code")
        read_only_fields = fields


def _as_drf_errors(exc: DjangoValidationError) -> dict:
    """Convert a Django ``ValidationError`` into DRF error detail."""
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"non_field_errors": exc.messages}


class ModelCleanValidationMixin:
    """Run the model's ``clean()`` during serializer validation."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance if self.instance is not None else self.Meta.model()
        for field_name, value in attrs.items():
            setattr(instance, field_name, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(_as_drf_errors(exc)) from exc
        return attrs


class DepartmentScopeWriteMixin:
    """Keep writes inside the writer's department.

    ``department_scope_fields`` maps each writable relationship field to the
    path from that value to its owning department (``"pk"`` when the value *is*
    the department). College administrators and superusers are unrestricted, so
    a client cannot escape its department by sending a foreign key id.
    """

    department_scope_fields: dict[str, str] = {}

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = getattr(self.context.get("request"), "user", None)
        if user is None or not user.is_authenticated or user.has_cross_department_access:
            return attrs
        for field_name, path in self.department_scope_fields.items():
            if field_name not in attrs:
                continue
            department_id = resolve_department_id(attrs[field_name], path)
            if not user_can_manage_department(user, department_id):
                raise serializers.ValidationError(
                    {field_name: "You may only manage records in your own department."}
                )
        return attrs


class CollegeSerializer(serializers.ModelSerializer):
    """Colleges. Writes are restricted to college administrators by permissions."""

    class Meta:
        model = College
        fields = ("id", "name", "code", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class AcademicYearSerializer(ModelCleanValidationMixin, serializers.ModelSerializer):
    """Academic years (for example 2026-2027)."""

    class Meta:
        model = AcademicYear
        fields = (
            "id",
            "start_year",
            "end_year",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class SemesterSerializer(serializers.ModelSerializer):
    """Read representation of a semester."""

    academic_year = AcademicYearSummarySerializer(read_only=True)

    class Meta:
        model = Semester
        fields = (
            "id",
            "number",
            "start_date",
            "end_date",
            "academic_year",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class SemesterWriteSerializer(ModelCleanValidationMixin, serializers.ModelSerializer):
    """Write representation of a semester (``academic_year`` as a primary key)."""

    academic_year = serializers.PrimaryKeyRelatedField(
        queryset=AcademicYear.objects.all()
    )

    class Meta:
        model = Semester
        fields = ("number", "start_date", "end_date", "academic_year", "is_active")


class DepartmentSerializer(serializers.ModelSerializer):
    """Read representation of a department."""

    college = CollegeSummarySerializer(read_only=True)

    class Meta:
        model = Department
        fields = (
            "id",
            "name",
            "code",
            "college",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class DepartmentWriteSerializer(serializers.ModelSerializer):
    """Write representation of a department.

    The model field stays nullable for rows created before Phase 2, but the API
    requires a college when creating departments.
    """

    college = serializers.PrimaryKeyRelatedField(
        queryset=College.objects.all(),
        required=True,
    )

    class Meta:
        model = Department
        fields = ("name", "code", "college", "is_active")


class StudyProgramSerializer(serializers.ModelSerializer):
    """Read representation of a study program."""

    department = DepartmentSummarySerializer(read_only=True)

    class Meta:
        model = StudyProgram
        fields = (
            "id",
            "name",
            "code",
            "study_type",
            "department",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class StudyProgramWriteSerializer(DepartmentScopeWriteMixin, serializers.ModelSerializer):
    """Write representation of a study program."""

    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())

    department_scope_fields = {"department": "pk"}

    class Meta:
        model = StudyProgram
        fields = ("name", "code", "study_type", "department", "is_active")


class StudyStageSerializer(serializers.ModelSerializer):
    """Read representation of a study stage."""

    program = StudyProgramSummarySerializer(read_only=True)

    class Meta:
        model = StudyStage
        fields = (
            "id",
            "number",
            "name",
            "program",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class StudyStageWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a study stage."""

    program = serializers.PrimaryKeyRelatedField(queryset=StudyProgram.objects.all())

    department_scope_fields = {"program": "department"}

    class Meta:
        model = StudyStage
        fields = ("number", "name", "program", "is_active")


class StudentGroupSerializer(serializers.ModelSerializer):
    """Read representation of a student group (subgroups stay one level deep)."""

    stage = StudyStageSummarySerializer(read_only=True)
    parent_group = StudentGroupSummarySerializer(read_only=True)

    class Meta:
        model = StudentGroup
        fields = (
            "id",
            "name",
            "code",
            "student_count",
            "stage",
            "parent_group",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class StudentGroupWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a student group."""

    stage = serializers.PrimaryKeyRelatedField(queryset=StudyStage.objects.all())
    parent_group = serializers.PrimaryKeyRelatedField(
        queryset=StudentGroup.objects.all(),
        required=False,
        allow_null=True,
    )

    department_scope_fields = {"stage": "program__department"}

    class Meta:
        model = StudentGroup
        fields = ("name", "code", "student_count", "stage", "parent_group", "is_active")


# --- Phase 3: courses, offerings and teaching components ---------------------


class CourseSummarySerializer(serializers.ModelSerializer):
    """Compact course representation used in nested payloads."""

    class Meta:
        model = Course
        fields = ("id", "name", "code")
        read_only_fields = fields


class SemesterSummarySerializer(serializers.ModelSerializer):
    """Compact semester representation used in nested payloads."""

    academic_year = AcademicYearSummarySerializer(read_only=True)

    class Meta:
        model = Semester
        fields = ("id", "number", "academic_year")
        read_only_fields = fields


class CourseSerializer(serializers.ModelSerializer):
    """Read representation of a course."""

    department = DepartmentSummarySerializer(read_only=True)

    class Meta:
        model = Course
        fields = (
            "id",
            "name",
            "code",
            "description",
            "department",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class CourseWriteSerializer(DepartmentScopeWriteMixin, serializers.ModelSerializer):
    """Write representation of a course (``department`` as a primary key)."""

    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())

    department_scope_fields = {"department": "pk"}

    class Meta:
        model = Course
        fields = ("name", "code", "description", "department", "is_active")


class CourseOfferingSummarySerializer(serializers.ModelSerializer):
    """Compact offering representation used in nested payloads."""

    course = CourseSummarySerializer(read_only=True)

    class Meta:
        model = CourseOffering
        fields = ("id", "offering_code", "course")
        read_only_fields = fields


class CourseOfferingSerializer(serializers.ModelSerializer):
    """Read representation of a course offering."""

    course = CourseSummarySerializer(read_only=True)
    semester = SemesterSummarySerializer(read_only=True)
    managing_department = DepartmentSummarySerializer(read_only=True)
    total_weekly_hours = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = CourseOffering
        fields = (
            "id",
            "offering_code",
            "course",
            "semester",
            "managing_department",
            "total_weekly_hours",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class CourseOfferingWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a course offering.

    ``managing_department`` must be the writer's own department, and the model
    ``clean()`` requires it to be the department that owns the course — so a
    foreign course cannot be hijacked by naming a different manager.
    """

    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all())
    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())
    managing_department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all()
    )

    department_scope_fields = {"managing_department": "pk"}

    class Meta:
        model = CourseOffering
        fields = (
            "course",
            "semester",
            "managing_department",
            "offering_code",
            "is_active",
        )


class TeachingComponentSummarySerializer(serializers.ModelSerializer):
    """Compact teaching component representation used in nested payloads."""

    class Meta:
        model = TeachingComponent
        fields = ("id", "component_type", "label")
        read_only_fields = fields


class TeachingComponentSerializer(serializers.ModelSerializer):
    """Read representation of a teaching component."""

    offering = CourseOfferingSummarySerializer(read_only=True)
    sessions_per_week = serializers.IntegerField(read_only=True)

    class Meta:
        model = TeachingComponent
        fields = (
            "id",
            "component_type",
            "label",
            "weekly_hours",
            "session_duration_hours",
            "sessions_per_week",
            "offering",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class TeachingComponentWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a teaching component.

    Components may only be written for an offering managed by the writer's
    department; participating departments stay read-only.
    """

    offering = serializers.PrimaryKeyRelatedField(queryset=CourseOffering.objects.all())

    department_scope_fields = {"offering": "managing_department"}

    class Meta:
        model = TeachingComponent
        fields = (
            "offering",
            "component_type",
            "label",
            "weekly_hours",
            "session_duration_hours",
            "is_active",
        )


class TeachingComponentGroupSerializer(serializers.ModelSerializer):
    """Read representation of a teaching component / student group relation."""

    teaching_component = TeachingComponentSummarySerializer(read_only=True)
    student_group = StudentGroupSummarySerializer(read_only=True)

    class Meta:
        model = TeachingComponentGroup
        fields = ("id", "teaching_component", "student_group", "created_at")
        read_only_fields = fields


class TeachingComponentGroupWriteSerializer(
    ModelCleanValidationMixin,
    DepartmentScopeWriteMixin,
    serializers.ModelSerializer,
):
    """Write representation of a teaching component / student group relation.

    A department administrator can only link a component of an offering they
    manage and a student group of their own department; enrolling another
    department's students into a joint course is reserved for college
    administrators and superusers.
    """

    teaching_component = serializers.PrimaryKeyRelatedField(
        queryset=TeachingComponent.objects.all()
    )
    student_group = serializers.PrimaryKeyRelatedField(
        queryset=StudentGroup.objects.all()
    )

    department_scope_fields = {
        "teaching_component": "offering__managing_department",
        "student_group": "stage__program__department",
    }

    class Meta:
        model = TeachingComponentGroup
        fields = ("teaching_component", "student_group")
