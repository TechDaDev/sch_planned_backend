"""API serializers for the calendar and time configuration.

Foreign keys are written as primary keys and read back as compact summaries, in
line with earlier phases. Nesting stays shallow: a slot or break shows its
working day (with the semester as an id), and a calendar exception shows a single
``target`` summary chosen by its scope instead of every possible target.

The cross-field rules (grid boundaries, overlap, exception scope and semester
range) live on the models and run through ``ModelCleanValidationMixin``, so
predictable violations answer ``400``. Grid writes are restricted to college
administrators by the views.

Generation request/response bodies keep the two scopes explicit: the department
endpoint has no ``scope`` field, and the college-wide endpoint has no
``department`` field, so neither can be silently turned into the other.
"""

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from typing import Any

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
    Schedule,
    ScheduleEntry,
    ScheduleScope,
    ScheduleStatus,
    ScheduleVersion,
    ScheduleVersionSource,
    TimeSlot,
    WorkingDay,
)
from scheduling.services.solver import DEFAULT_MAX_TIME_SECONDS, SolverStatus
from scheduling.services.validation import Severity, ValidationScope

#: Bounds the API accepts for the solver time limit.
MIN_GENERATION_TIME_SECONDS = 1
MAX_GENERATION_TIME_SECONDS = 120

#: College-wide problems are naturally larger, so their default and ceiling differ.
DEFAULT_COLLEGE_GENERATION_TIME_SECONDS = 60
MIN_COLLEGE_GENERATION_TIME_SECONDS = 1
MAX_COLLEGE_GENERATION_TIME_SECONDS = 300

#: Longest note a caller may attach to a persisted schedule version.
SCHEDULE_NOTES_MAX_LENGTH = 2000


class StrictFieldValidationMixin:
    """Reject request fields the serializer does not define.

    The API elsewhere ignores unknown fields, following the DRF default. The
    endpoints that create state deliberately do not: a silently ignored field looks
    like it was honoured, and for schedule endpoints that could mean a scope or a
    solver control the caller believes in but the server never applied.
    """

    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unknown = sorted(set(data.keys()) - set(self.fields))
            if unknown:
                raise serializers.ValidationError(
                    {
                        field: "This endpoint does not accept this field."
                        for field in unknown
                    }
                )
        return super().to_internal_value(data)


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


# --- Phase 7: pre-scheduling validation ------------------------------------


class PreSchedulingValidationInputSerializer(serializers.Serializer):
    """Request body of ``POST /api/scheduling/validate/``.

    ``COLLEGE`` and ``DEPARTMENT`` are the only scopes, and the two shapes never
    overlap: a college-wide run must omit ``department``, a department run must
    supply exactly one. Ambiguous input is rejected before the validator runs.

    Named for its *input* role on purpose: the project enables
    ``COMPONENT_SPLIT_REQUEST``, so the generated component is
    ``PreSchedulingValidationInputRequest`` and a class already ending in
    ``Request`` would produce a doubled name.
    """

    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())
    scope = serializers.ChoiceField(choices=ValidationScope.choices)
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(),
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        scope = attrs.get("scope")
        department = attrs.get("department")
        if scope == ValidationScope.COLLEGE and department is not None:
            raise serializers.ValidationError(
                {"department": "Omit department when scope is COLLEGE."}
            )
        if scope == ValidationScope.DEPARTMENT and department is None:
            raise serializers.ValidationError(
                {"department": "This field is required when scope is DEPARTMENT."}
            )
        return attrs


class ValidationSemesterSerializer(serializers.Serializer):
    """Semester identification block of a validation response.

    ``academic_year`` is the human-readable label (``"2026-2027"``) that
    administrators recognise, while ``academic_year_id`` keeps the primary key for
    clients that need to link back to the record.
    """

    id = serializers.IntegerField()
    number = serializers.IntegerField()
    academic_year = serializers.SerializerMethodField()
    academic_year_id = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField())
    def get_academic_year(self, obj):
        """Display label of the academic year, for example ``2026-2027``."""
        return str(obj.academic_year)

    @extend_schema_field(serializers.IntegerField())
    def get_academic_year_id(self, obj):
        """Primary key of the semester's academic year."""
        return obj.academic_year_id


class ValidationSummarySerializer(serializers.Serializer):
    """Counts block of a validation response."""

    components_checked = serializers.IntegerField()
    errors = serializers.IntegerField()
    warnings = serializers.IntegerField()


class ValidationIssueSerializer(serializers.Serializer):
    """One validation issue.

    ``code`` values are stable and finite; ``details`` carries scalars that
    describe the finding for that specific code. Messages are written for humans
    and never echo a Python exception.
    """

    code = serializers.CharField(
        help_text="Stable issue code; the full list is documented in the README."
    )
    severity = serializers.ChoiceField(choices=Severity.choices)
    message = serializers.CharField()
    entity_type = serializers.CharField(
        help_text="Model name of the row the issue is reported against."
    )
    entity_id = serializers.IntegerField(allow_null=True, required=False)
    details = serializers.DictField(required=False)


class PreSchedulingValidationResponseSerializer(serializers.Serializer):
    """Response body of ``POST /api/scheduling/validate/``.

    ``ready`` is true only when no issue has ``severity = "ERROR"``; warnings
    never block timetable generation. ``department`` is ``null`` for a
    college-wide run.
    """

    ready = serializers.BooleanField()
    scope = serializers.ChoiceField(choices=ValidationScope.choices)
    semester = ValidationSemesterSerializer()
    department = DepartmentSummarySerializer(allow_null=True, required=False)
    summary = ValidationSummarySerializer()
    issues = ValidationIssueSerializer(many=True)


# --- Phase 9: department schedule generation -------------------------------


class ScheduleGenerationInputSerializer(serializers.Serializer):
    """Request body of ``POST /api/scheduling/generate/``.

    Only the department scope exists in this phase, so there is no ``scope``
    field. The caller controls the time limit and nothing else: the search seed,
    the single worker and the quiet solver log are fixed server-side so the same
    request keeps producing the same preview.
    """

    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())
    max_time_seconds = serializers.IntegerField(
        required=False,
        default=DEFAULT_MAX_TIME_SECONDS,
        min_value=MIN_GENERATION_TIME_SECONDS,
        max_value=MAX_GENERATION_TIME_SECONDS,
        help_text=(
            "Solver time limit in seconds. Defaults to the engine default; the "
            "difference between the limit and the actual run time is normal."
        ),
    )


class GenerationSolverSerializer(serializers.Serializer):
    """What the CP-SAT engine reported.

    ``status`` is one of ``OPTIMAL``, ``FEASIBLE``, ``INFEASIBLE``,
    ``MODEL_INVALID`` or ``UNKNOWN``. A ``FEASIBLE`` status means a valid timetable
    was found without proving it optimal; it is never reported as ``OPTIMAL``.
    """

    status = serializers.ChoiceField(choices=[status.value for status in SolverStatus])
    objective_value = serializers.IntegerField(allow_null=True, required=False)
    wall_time_seconds = serializers.FloatField()
    num_conflicts = serializers.IntegerField()
    num_branches = serializers.IntegerField()
    message = serializers.CharField(allow_blank=True, required=False)


class GenerationSummarySerializer(serializers.Serializer):
    """Counts of what was built and placed."""

    components = serializers.IntegerField()
    sessions = serializers.IntegerField()
    candidates = serializers.IntegerField()
    placements = serializers.IntegerField()


class GenerationCourseSerializer(serializers.Serializer):
    """Shallow course summary inside a placement."""

    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class GenerationOfferingSerializer(serializers.Serializer):
    """Shallow offering summary inside a placement."""

    id = serializers.IntegerField()
    offering_code = serializers.CharField()


class GenerationComponentSerializer(serializers.Serializer):
    """Shallow teaching-component summary inside a placement."""

    id = serializers.IntegerField()
    component_type = serializers.CharField()
    label = serializers.CharField(allow_blank=True, required=False)


class GenerationSlotSerializer(serializers.Serializer):
    """One occupied teaching period."""

    id = serializers.IntegerField()
    sequence = serializers.IntegerField()
    label = serializers.CharField(allow_blank=True, required=False)
    start_time = serializers.CharField()
    end_time = serializers.CharField()


class GenerationRoomSerializer(serializers.Serializer):
    """Shallow room summary inside a placement."""

    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class GenerationInstructorSerializer(serializers.Serializer):
    """Instructor used by a placement, with the role held on the component.

    The preview row carries the instructor together with its assignment role, so
    the id and name are read through that wrapper.
    """

    id = serializers.IntegerField(source="instructor.id")
    full_name = serializers.CharField(source="instructor.full_name")
    assignment_role = serializers.CharField(allow_null=True, required=False)


class GenerationGroupSerializer(serializers.Serializer):
    """Shallow student-group summary inside a placement."""

    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class GenerationPlacementSerializer(serializers.Serializer):
    """One scheduled session in the preview.

    All groups attached to the component are listed, including groups belonging to
    other departments when the component is shared, because those students attend
    the session.
    """

    session_id = serializers.CharField()
    course = GenerationCourseSerializer()
    offering = GenerationOfferingSerializer()
    teaching_component = GenerationComponentSerializer()
    day_of_week = serializers.IntegerField()
    day_display = serializers.CharField()
    slots = GenerationSlotSerializer(many=True)
    start_time = serializers.CharField()
    end_time = serializers.CharField()
    room = GenerationRoomSerializer(allow_null=True, required=False)
    instructors = GenerationInstructorSerializer(many=True)
    student_groups = GenerationGroupSerializer(many=True)
    penalty = serializers.IntegerField()


class GenerationSessionCandidateCountSerializer(serializers.Serializer):
    """Candidate count of one session, used by diagnostics."""

    session_id = serializers.CharField()
    component_id = serializers.IntegerField()
    candidate_count = serializers.IntegerField()


class GenerationDiagnosticsSerializer(serializers.Serializer):
    """Counts gathered while building.

    These are diagnostics, not a root cause: the solver proves that no timetable
    exists, not why.
    """

    components = serializers.IntegerField()
    sessions = serializers.IntegerField()
    candidates = serializers.IntegerField()
    min_candidates_per_session = serializers.IntegerField()
    max_candidates_per_session = serializers.IntegerField()
    sessions_with_fewest_candidates = GenerationSessionCandidateCountSerializer(
        many=True
    )
    sessions_without_candidates = serializers.ListField(
        child=serializers.CharField(), required=False
    )


class DepartmentGenerationResponseSerializer(serializers.Serializer):
    """Response body of a completed generation request.

    ``generated`` is true only when the solver returned placements. ``persisted``
    is always false in this phase: nothing is written to the database, and no
    schedule model exists yet.
    """

    generated = serializers.BooleanField()
    persisted = serializers.BooleanField()
    message = serializers.CharField(allow_blank=True, required=False)
    semester = ValidationSemesterSerializer()
    department = DepartmentSummarySerializer(allow_null=True, required=False)
    validation = PreSchedulingValidationResponseSerializer(required=False)
    solver = GenerationSolverSerializer(allow_null=True, required=False)
    summary = GenerationSummarySerializer(allow_null=True, required=False)
    placements = GenerationPlacementSerializer(many=True, required=False)
    generation_issues = ValidationIssueSerializer(many=True, required=False)
    diagnostics = GenerationDiagnosticsSerializer(allow_null=True, required=False)


class GenerationRejectedSerializer(serializers.Serializer):
    """Response body of a request that could not be generated.

    ``reason`` is either ``PRE_SCHEDULING_VALIDATION_FAILED`` or
    ``CANDIDATE_BUILD_FAILED``. The first carries the Phase 7 validation result;
    the second carries adapter issues such as ``NO_PLACEMENT_CANDIDATES``.
    """

    generated = serializers.BooleanField()
    persisted = serializers.BooleanField()
    reason = serializers.CharField()
    message = serializers.CharField(allow_blank=True, required=False)
    semester = ValidationSemesterSerializer()
    department = DepartmentSummarySerializer(allow_null=True, required=False)
    validation = PreSchedulingValidationResponseSerializer(allow_null=True, required=False)
    generation_issues = ValidationIssueSerializer(many=True, required=False)
    diagnostics = GenerationDiagnosticsSerializer(allow_null=True, required=False)


# --- Phase 10: college-wide schedule generation ----------------------------


class CollegeScheduleGenerationInputSerializer(
    StrictFieldValidationMixin, serializers.Serializer
):
    """Request body of ``POST /api/scheduling/generate-college/``.

    The scope is the endpoint itself, so there is no ``scope`` or ``department``
    field: a caller cannot ask this endpoint for less than the whole college. The
    caller controls the time limit and nothing else - the search seed, the single
    worker and the quiet solver log stay fixed server-side so the same request keeps
    producing the same preview.

    A college-wide problem contains every department's sessions at once, so the
    accepted time limit is wider than the department endpoint's.

    Unlike the rest of the API, this body rejects unknown fields instead of
    ignoring them: a silently ignored ``scope`` or ``department`` would let a caller
    believe a hidden scope was honoured, and a silently ignored ``random_seed``,
    ``num_search_workers``, ``log_search_progress`` or ``reservations`` would look
    like a supported solver control. Rejection makes the contract explicit.
    """

    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())
    max_time_seconds = serializers.IntegerField(
        required=False,
        default=DEFAULT_COLLEGE_GENERATION_TIME_SECONDS,
        min_value=MIN_COLLEGE_GENERATION_TIME_SECONDS,
        max_value=MAX_COLLEGE_GENERATION_TIME_SECONDS,
        help_text=(
            "Solver time limit in seconds. Defaults to 60 for a college-wide "
            "problem; the difference between the limit and the actual run time is "
            "normal."
        ),
    )


class GenerationDepartmentBuildCountSerializer(serializers.Serializer):
    """How much one managing department contributed to the built problem."""

    department = DepartmentSummarySerializer()
    components = serializers.IntegerField()
    sessions = serializers.IntegerField()
    candidates = serializers.IntegerField()


class GenerationDepartmentSummarySerializer(serializers.Serializer):
    """One managing department's share of a finished college-wide run.

    ``placements`` counts components managed by that department, so a joint
    component serving foreign student groups is counted once, for its managing
    department, and never for the departments that merely attend it.
    """

    department = DepartmentSummarySerializer()
    components = serializers.IntegerField()
    sessions = serializers.IntegerField()
    candidates = serializers.IntegerField()
    placements = serializers.IntegerField()


class CollegeGenerationSummarySerializer(serializers.Serializer):
    """Counts of what a college-wide build covered and placed."""

    departments = serializers.IntegerField()
    components = serializers.IntegerField()
    sessions = serializers.IntegerField()
    candidates = serializers.IntegerField()
    placements = serializers.IntegerField()


class CollegeGenerationDiagnosticsSerializer(GenerationDiagnosticsSerializer):
    """Department-scoped diagnostics plus the per-department build counts.

    These are still diagnostics, not a root cause: the solver proves that no
    timetable exists, not why.
    """

    departments = serializers.IntegerField()
    department_breakdown = GenerationDepartmentBuildCountSerializer(many=True)


class CollegeGenerationPlacementSerializer(GenerationPlacementSerializer):
    """One college-wide placement, additionally naming its managing department.

    The department endpoint's placement body is deliberately left unchanged; this
    subclass adds the one field a college-wide preview cannot infer, and adds it
    after the inherited fields.
    """

    managing_department = DepartmentSummarySerializer(allow_null=True, required=False)


class CollegeGenerationResponseSerializer(serializers.Serializer):
    """Response body of a completed college-wide generation request.

    ``generated`` is true only when the solver returned placements; an infeasible or
    timed-out solve is still a ``200`` with ``generated: false``.
    ``persisted`` is always false in this phase: nothing is written and no schedule
    model exists yet.

    ``department_summaries`` is ordered by department code, then department id.
    """

    generated = serializers.BooleanField()
    persisted = serializers.BooleanField()
    scope = serializers.ChoiceField(choices=ValidationScope.choices)
    message = serializers.CharField(allow_blank=True, required=False)
    semester = ValidationSemesterSerializer()
    validation = PreSchedulingValidationResponseSerializer(required=False)
    solver = GenerationSolverSerializer(allow_null=True, required=False)
    summary = CollegeGenerationSummarySerializer(allow_null=True, required=False)
    department_summaries = GenerationDepartmentSummarySerializer(
        many=True, required=False
    )
    placements = CollegeGenerationPlacementSerializer(many=True, required=False)
    generation_issues = ValidationIssueSerializer(many=True, required=False)
    diagnostics = CollegeGenerationDiagnosticsSerializer(
        allow_null=True, required=False
    )


class CollegeGenerationRejectedSerializer(serializers.Serializer):
    """Response body of a college-wide request that could not be generated.

    ``reason`` is either ``PRE_SCHEDULING_VALIDATION_FAILED``, which carries the
    Phase 7 college-wide validation result, or ``CANDIDATE_BUILD_FAILED``, which
    carries adapter issues such as ``NO_PLACEMENT_CANDIDATES``. Neither outcome ran
    OR-Tools.
    """

    generated = serializers.BooleanField()
    persisted = serializers.BooleanField()
    scope = serializers.ChoiceField(choices=ValidationScope.choices)
    reason = serializers.CharField()
    message = serializers.CharField(allow_blank=True, required=False)
    semester = ValidationSemesterSerializer()
    validation = PreSchedulingValidationResponseSerializer(allow_null=True, required=False)
    generation_issues = ValidationIssueSerializer(many=True, required=False)
    diagnostics = CollegeGenerationDiagnosticsSerializer(
        allow_null=True, required=False
    )


# --- Phase 11: persisted schedules, versions and entries --------------------


class ScheduleDraftDepartmentInputSerializer(
    StrictFieldValidationMixin, serializers.Serializer
):
    """Request body of ``POST /api/schedules/generate-department-draft/``.

    The server generates the timetable itself with the Phase 9 pipeline and stores
    that result. A caller supplies what to schedule and a note, never placements:
    accepting client placements would let a request bypass instructor, room, group,
    availability, sharing and CP-SAT constraints. Unsupported fields are rejected
    rather than ignored, so ``placements``, ``status`` or ``version_number`` cannot
    look like they were applied.
    """

    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())
    max_time_seconds = serializers.IntegerField(
        required=False,
        default=DEFAULT_MAX_TIME_SECONDS,
        min_value=MIN_GENERATION_TIME_SECONDS,
        max_value=MAX_GENERATION_TIME_SECONDS,
        help_text="Solver time limit in seconds for the generation that is stored.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=SCHEDULE_NOTES_MAX_LENGTH,
        help_text="Free-text note stored on the created draft version.",
    )


class ScheduleDraftCollegeInputSerializer(
    StrictFieldValidationMixin, serializers.Serializer
):
    """Request body of ``POST /api/schedules/generate-college-draft/``.

    College scope is the endpoint, so ``department`` and ``scope`` are unsupported
    fields and are rejected; so are ``placements``, ``reservations``, ``status`` and
    ``version_number``.
    """

    semester = serializers.PrimaryKeyRelatedField(queryset=Semester.objects.all())
    max_time_seconds = serializers.IntegerField(
        required=False,
        default=DEFAULT_COLLEGE_GENERATION_TIME_SECONDS,
        min_value=MIN_COLLEGE_GENERATION_TIME_SECONDS,
        max_value=MAX_COLLEGE_GENERATION_TIME_SECONDS,
        help_text="Solver time limit in seconds for the generation that is stored.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=SCHEDULE_NOTES_MAX_LENGTH,
        help_text="Free-text note stored on the created draft version.",
    )


class ScheduleUserSummarySerializer(serializers.Serializer):
    """Shallow account summary of whoever created a schedule or a version."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    role = serializers.CharField()


class ScheduleIdentitySerializer(serializers.Serializer):
    """What a schedule is: its semester and its scope."""

    id = serializers.IntegerField()
    scope = serializers.ChoiceField(choices=ScheduleScope.choices)
    semester = SemesterSummarySerializer()
    department = DepartmentSummarySerializer(allow_null=True, required=False)


class ScheduleVersionSummarySerializer(serializers.Serializer):
    """One version row as lists and details show it.

    ``entry_count`` comes from an annotation on the queryset so a version list does
    not query per row; the detail path and the draft response annotate it too.
    """

    id = serializers.IntegerField()
    version_number = serializers.IntegerField()
    status = serializers.ChoiceField(choices=ScheduleStatus.choices)
    source = serializers.ChoiceField(choices=ScheduleVersionSource.choices)
    parent_version = serializers.IntegerField(
        source="parent_version_id", allow_null=True, required=False
    )
    created_by = ScheduleUserSummarySerializer(allow_null=True, required=False)
    notes = serializers.CharField(allow_blank=True, required=False)
    solver_status = serializers.CharField(
        allow_null=True, allow_blank=True, required=False
    )
    objective_value = serializers.IntegerField(allow_null=True, required=False)
    entry_count = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()

    def get_entry_count(self, obj) -> int:
        annotated = getattr(obj, "entry_count", None)
        if annotated is not None:
            return annotated
        return obj.entries.count()


class ScheduleSummarySerializer(ScheduleIdentitySerializer):
    """One logical schedule as the collection shows it.

    ``version_count`` and the latest version fields are annotations, so a list of
    schedules costs one query regardless of how much history each one has.
    """

    version_count = serializers.SerializerMethodField()
    latest_version_number = serializers.SerializerMethodField()
    latest_version_status = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_version_count(self, obj) -> int:
        annotated = getattr(obj, "version_count", None)
        if annotated is not None:
            return annotated
        return obj.versions.count()

    def get_latest_version_number(self, obj) -> int | None:
        return getattr(obj, "latest_version_number", None)

    def get_latest_version_status(self, obj) -> str | None:
        return getattr(obj, "latest_version_status", None)


class ScheduleDetailSerializer(ScheduleSummarySerializer):
    """One logical schedule with a summary of its newest version.

    The full history is served by ``/api/schedules/{id}/versions/`` and the entries
    of a version by ``/api/schedule-versions/{id}/entries/``, so this response stays
    a timetable *identity*, not a timetable.

    ``published_version`` is the authoritative pointer of a college schedule. It is
    the only thing that says which version is current: several versions may carry the
    ``PUBLISHED`` status over time, and only this one is official.
    """

    latest_version = serializers.SerializerMethodField()
    published_version = serializers.SerializerMethodField()
    published_version_number = serializers.SerializerMethodField()
    published_at = serializers.SerializerMethodField()

    def get_latest_version(self, obj) -> dict | None:
        version = getattr(obj, "latest_version_obj", None)
        if version is None:
            return None
        return ScheduleVersionSummarySerializer(version).data

    def get_published_version(self, obj) -> int | None:
        return obj.published_version_id

    def get_published_version_number(self, obj) -> int | None:
        if obj.published_version_id is None:
            return None
        return obj.published_version.version_number

    def get_published_at(self, obj) -> Any | None:
        if obj.published_version_id is None:
            return None
        return obj.published_version.published_at


class ScheduleVersionDetailSerializer(ScheduleVersionSummarySerializer):
    """One version with its full generation provenance and workflow metadata.

    Workflow metadata is exposed here rather than on the summary shape, so the list
    contract stays as it was while a detail response can show who submitted, reviewed,
    approved and published this version, and when.

    Entries are not nested: they are served by the version's ``entries`` action.
    """

    schedule = ScheduleIdentitySerializer()
    solver_wall_time_seconds = serializers.FloatField(allow_null=True, required=False)
    solver_num_conflicts = serializers.IntegerField(allow_null=True, required=False)
    solver_num_branches = serializers.IntegerField(allow_null=True, required=False)
    validation_summary = serializers.DictField(required=False)
    generation_summary = serializers.DictField(required=False)
    submitted_by = ScheduleUserSummarySerializer(allow_null=True, required=False)
    submitted_at = serializers.DateTimeField(allow_null=True, required=False)
    reviewed_by = ScheduleUserSummarySerializer(allow_null=True, required=False)
    reviewed_at = serializers.DateTimeField(allow_null=True, required=False)
    approved_by = ScheduleUserSummarySerializer(allow_null=True, required=False)
    approved_at = serializers.DateTimeField(allow_null=True, required=False)
    published_by = ScheduleUserSummarySerializer(allow_null=True, required=False)
    published_at = serializers.DateTimeField(allow_null=True, required=False)
    is_published_current = serializers.SerializerMethodField()

    def get_is_published_current(self, obj) -> bool:
        """True when this version is the schedule's authoritative publication."""
        return obj.schedule.published_version_id == obj.pk


class ScheduleEntryTimeSlotSerializer(serializers.Serializer):
    """One occupied period of an entry, rendered from its snapshot columns."""

    id = serializers.IntegerField(source="time_slot_id")
    position = serializers.IntegerField()
    sequence = serializers.IntegerField(source="sequence_snapshot")
    label = serializers.CharField(
        source="label_snapshot", allow_blank=True, required=False
    )
    start_time = serializers.TimeField(source="start_time_snapshot", format="%H:%M")
    end_time = serializers.TimeField(source="end_time_snapshot", format="%H:%M")


class ScheduleEntryInstructorSerializer(serializers.Serializer):
    """One instructor of an entry, rendered from its snapshot columns."""

    id = serializers.IntegerField(source="instructor_id")
    full_name = serializers.CharField(source="full_name_snapshot")
    assignment_role = serializers.CharField(
        source="assignment_role_snapshot", allow_blank=True, required=False
    )


class ScheduleEntryStudentGroupSerializer(serializers.Serializer):
    """One student group of an entry, including its own department snapshot."""

    id = serializers.IntegerField(source="student_group_id")
    code = serializers.CharField(source="code_snapshot")
    name = serializers.CharField(source="name_snapshot")
    department = serializers.SerializerMethodField()

    def get_department(self, obj) -> dict | None:
        if obj.department_id_snapshot is None:
            return None
        return {
            "id": obj.department_id_snapshot,
            "code": obj.department_code_snapshot,
            "name": obj.department_name_snapshot,
        }


class ScheduleEntrySerializer(serializers.Serializer):
    """One persisted weekly session, rendered from its snapshot columns.

    Every display value comes from the row itself, not from the live course, room,
    department, instructor or group, so renaming any of them later cannot rewrite
    what a stored version shows.
    """

    id = serializers.IntegerField()
    session_id = serializers.CharField()
    candidate_id = serializers.CharField()
    session_ordinal = serializers.IntegerField()
    course = serializers.SerializerMethodField()
    offering = serializers.SerializerMethodField()
    teaching_component = serializers.SerializerMethodField()
    managing_department = serializers.SerializerMethodField()
    day_of_week = serializers.IntegerField()
    day_display = serializers.SerializerMethodField()
    start_time = serializers.TimeField(format="%H:%M")
    end_time = serializers.TimeField(format="%H:%M")
    time_slots = ScheduleEntryTimeSlotSerializer(many=True)
    room = serializers.SerializerMethodField()
    instructors = ScheduleEntryInstructorSerializer(many=True)
    student_groups = ScheduleEntryStudentGroupSerializer(many=True)
    penalty = serializers.IntegerField()

    def get_course(self, obj) -> dict:
        return {
            "id": obj.course_id_snapshot,
            "code": obj.course_code_snapshot,
            "name": obj.course_name_snapshot,
        }

    def get_offering(self, obj) -> dict:
        return {
            "id": obj.offering_id_snapshot,
            "offering_code": obj.offering_code_snapshot,
        }

    def get_teaching_component(self, obj) -> dict:
        return {
            "id": obj.teaching_component_id,
            "component_type": obj.component_type_snapshot,
            "label": obj.component_label_snapshot,
        }

    def get_managing_department(self, obj) -> dict:
        return {
            "id": obj.managing_department_id,
            "code": obj.managing_department_code_snapshot,
            "name": obj.managing_department_name_snapshot,
        }

    def get_day_display(self, obj) -> str:
        try:
            return Weekday(obj.day_of_week).label
        except ValueError:
            return str(obj.day_of_week)

    def get_room(self, obj) -> dict | None:
        if obj.room_id is None:
            return None
        return {
            "id": obj.room_id,
            "code": obj.room_code_snapshot,
            "name": obj.room_name_snapshot,
        }


class ScheduleDraftResponseSerializer(serializers.Serializer):
    """Response body of a department draft request.

    ``persisted`` is true only when a complete generation was stored as a new
    version. A run that completed without a timetable answers ``200`` with
    ``generated: false`` and ``persisted: false``, and a rejected run answers ``409``
    with nothing written.
    """

    generated = serializers.BooleanField()
    persisted = serializers.BooleanField()
    scope = serializers.ChoiceField(choices=ScheduleScope.choices)
    message = serializers.CharField(allow_blank=True, required=False)
    semester = ValidationSemesterSerializer()
    department = DepartmentSummarySerializer(allow_null=True, required=False)
    validation = PreSchedulingValidationResponseSerializer(required=False)
    solver = GenerationSolverSerializer(allow_null=True, required=False)
    summary = GenerationSummarySerializer(allow_null=True, required=False)
    schedule = ScheduleSummarySerializer(allow_null=True, required=False)
    version = ScheduleVersionSummarySerializer(allow_null=True, required=False)
    placements = GenerationPlacementSerializer(many=True, required=False)
    generation_issues = ValidationIssueSerializer(many=True, required=False)
    diagnostics = GenerationDiagnosticsSerializer(allow_null=True, required=False)


class CollegeScheduleDraftResponseSerializer(ScheduleDraftResponseSerializer):
    """Response body of a college draft request.

    College placements additionally name their managing department, and the summary
    counts departments, matching the college preview.
    """

    summary = CollegeGenerationSummarySerializer(allow_null=True, required=False)
    placements = CollegeGenerationPlacementSerializer(many=True, required=False)
    diagnostics = CollegeGenerationDiagnosticsSerializer(
        allow_null=True, required=False
    )


class ScheduleDraftRejectedSerializer(serializers.Serializer):
    """Response body of a draft request that stored nothing.

    ``reason`` is one of ``PRE_SCHEDULING_VALIDATION_FAILED``,
    ``CANDIDATE_BUILD_FAILED`` or ``GENERATION_RESULT_INCOMPLETE``. In every case
    zero versions and zero entries exist afterwards.
    """

    generated = serializers.BooleanField()
    persisted = serializers.BooleanField()
    scope = serializers.ChoiceField(choices=ScheduleScope.choices)
    reason = serializers.CharField()
    message = serializers.CharField(allow_blank=True, required=False)
    semester = ValidationSemesterSerializer()
    department = DepartmentSummarySerializer(allow_null=True, required=False)
    validation = PreSchedulingValidationResponseSerializer(allow_null=True, required=False)
    generation_issues = ValidationIssueSerializer(many=True, required=False)
    diagnostics = GenerationDiagnosticsSerializer(allow_null=True, required=False)


# --- Phase 12: validated manual editing ------------------------------------


class ManualEditChangeSerializer(StrictFieldValidationMixin, serializers.Serializer):
    """One requested relocation of one existing entry.

    Only the placement may move. Instructors, student groups, the teaching component,
    the course and every snapshot value stay as the base version stored them, so
    fields such as ``instructor_ids``, ``session_id``, ``penalty`` or ``status`` are
    unsupported and are rejected rather than ignored.
    """

    entry_id = serializers.IntegerField(
        min_value=1, help_text="Entry to relocate, from this schedule version."
    )
    time_slot_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
        help_text=(
            "Teaching periods to occupy, in any order. Omit to keep the entry's "
            "current periods."
        ),
    )
    room_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
        help_text="Target room. Omit to keep the entry's current room.",
    )

    def validate(self, attrs):
        """Require a placement change, and refuse a repeated period."""
        if not attrs.get("time_slot_ids") and attrs.get("room_id") is None:
            raise serializers.ValidationError(
                "Supply time_slot_ids, room_id, or both."
            )
        slot_ids = attrs.get("time_slot_ids") or []
        if len(set(slot_ids)) != len(slot_ids):
            raise serializers.ValidationError(
                {"time_slot_ids": "A period may not be listed twice."}
            )
        return attrs


class ManualEditRequestSerializer(StrictFieldValidationMixin, serializers.Serializer):
    """Request body of both manual-edit endpoints.

    ``changes`` must not be empty: an edit that changes nothing is a mistake, not a
    no-op version. The services treat the whole list as one simultaneous state, so a
    swap is expressed as two changes in one request.
    """

    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=SCHEDULE_NOTES_MAX_LENGTH,
        help_text="Free-text note stored on the created version.",
    )
    changes = ManualEditChangeSerializer(
        many=True, allow_empty=False, help_text="Placement changes to apply together."
    )


class ManualEditIssueSerializer(serializers.Serializer):
    """One reason a proposed timetable was refused."""

    code = serializers.CharField(
        help_text="Stable issue code; the full list is documented in the README."
    )
    message = serializers.CharField()
    entry_id = serializers.IntegerField(allow_null=True, required=False)
    conflicting_entry_id = serializers.IntegerField(allow_null=True, required=False)
    details = serializers.DictField(required=False)


class ManualEditValidationResponseSerializer(serializers.Serializer):
    """Result of validating a proposal without storing it.

    ``valid`` is true only when no issue was reported. An invalid but well-formed
    proposal is a normal ``200``; only a malformed request is a ``400``.
    """

    valid = serializers.SerializerMethodField()
    base_version = serializers.IntegerField(source="base_version_id")
    summary = serializers.SerializerMethodField()
    issues = ManualEditIssueSerializer(many=True)

    def get_valid(self, obj) -> bool:
        return obj.valid

    def get_summary(self, obj) -> dict:
        return obj.as_summary()


class ManualEditVersionSerializer(serializers.Serializer):
    """Identity of the version a manual edit produced."""

    id = serializers.IntegerField()
    version_number = serializers.IntegerField()
    status = serializers.ChoiceField(choices=ScheduleStatus.choices)
    source = serializers.ChoiceField(choices=ScheduleVersionSource.choices)
    parent_version = serializers.IntegerField(
        source="parent_version_id", allow_null=True, required=False
    )


class ManualEditApplyResponseSerializer(serializers.Serializer):
    """Response body of a stored manual edit.

    ``generated`` is deliberately absent: no solver produced this version, and saying
    otherwise would misdescribe it. Solver metadata on the version is null for the same
    reason.
    """

    persisted = serializers.BooleanField()
    schedule = serializers.IntegerField(source="schedule.id")
    base_version = serializers.IntegerField(source="base_version_id")
    version = ManualEditVersionSerializer()
    summary = serializers.SerializerMethodField()

    def get_summary(self, obj) -> dict:
        return {"entries": obj.entry_count, "changed_entries": obj.changed_entries}


class ManualEditRejectedSerializer(serializers.Serializer):
    """Response body of a manual edit that stored nothing.

    ``reason`` is one of ``MANUAL_EDIT_VALIDATION_FAILED``,
    ``BASE_VERSION_NOT_DRAFT`` or ``STALE_BASE_VERSION``. In every case zero versions
    and zero entries were created.
    """

    persisted = serializers.BooleanField()
    reason = serializers.CharField()
    message = serializers.CharField(allow_blank=True, required=False)
    base_version = serializers.IntegerField(
        source="base_version_id", allow_null=True, required=False
    )
    validation = ManualEditValidationResponseSerializer(
        allow_null=True, required=False
    )


# --- Phase 13: workflow and publication ------------------------------------


class ScheduleWorkflowActionSerializer(StrictFieldValidationMixin, serializers.Serializer):
    """Request body of every workflow action, which is empty on purpose.

    A transition is an explicit server-side operation with no client-controlled
    parameters: the stage comes from the URL, the actor from the session, and the
    timestamp from the server. Fields such as ``status``, ``published_version`` or a
    workflow actor are therefore unsupported and rejected rather than ignored.
    """


class WorkflowIssueSerializer(serializers.Serializer):
    """One blocking reason a stored version cannot advance."""

    code = serializers.CharField(
        help_text="Stable issue code; the full list is documented in the README."
    )
    severity = serializers.CharField(help_text="Always ERROR: workflow issues block.")
    message = serializers.CharField()
    entry_id = serializers.IntegerField(allow_null=True, required=False)
    conflicting_entry_id = serializers.IntegerField(allow_null=True, required=False)
    details = serializers.DictField(required=False)


class WorkflowValidationResponseSerializer(serializers.Serializer):
    """Report of one full-version validation run.

    ``valid`` is true only when nothing blocks progression. The stored timetable is
    measured against today's configuration, so a version that was valid when created
    can be reported stale here.
    """

    valid = serializers.SerializerMethodField()
    version = serializers.IntegerField(source="version_id")
    status = serializers.ChoiceField(choices=ScheduleStatus.choices)
    summary = serializers.SerializerMethodField()
    issues = WorkflowIssueSerializer(many=True)

    def get_valid(self, obj) -> bool:
        return obj.valid

    def get_summary(self, obj) -> dict:
        return obj.as_summary()


class WorkflowTransitionResponseSerializer(serializers.Serializer):
    """Response body of an applied workflow action.

    ``version`` is the full version detail, so the new status and all workflow
    metadata are visible in one response. ``applied`` is always true here; a refused
    action answers ``409`` with the rejected shape instead.
    """

    applied = serializers.BooleanField()
    action = serializers.CharField()
    status = serializers.ChoiceField(choices=ScheduleStatus.choices)
    from_status = serializers.ChoiceField(
        choices=ScheduleStatus.choices, allow_null=True, required=False
    )
    version = ScheduleVersionDetailSerializer()
    validation = WorkflowValidationResponseSerializer(
        allow_null=True, required=False
    )


class WorkflowRejectedSerializer(serializers.Serializer):
    """Response body of a refused workflow action.

    ``reason`` is one of ``INVALID_TRANSITION``, ``STALE_VERSION``,
    ``DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE``, ``EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED``
    or ``SCHEDULE_VALIDATION_FAILED``. Nothing was changed: the status, the workflow
    metadata and every entry stay exactly as they were.
    """

    applied = serializers.BooleanField()
    action = serializers.CharField()
    reason = serializers.CharField()
    message = serializers.CharField(allow_blank=True, required=False)
    status = serializers.ChoiceField(
        choices=ScheduleStatus.choices, allow_null=True, required=False
    )
    version = serializers.IntegerField(
        source="version.id", allow_null=True, required=False
    )
    validation = WorkflowValidationResponseSerializer(
        allow_null=True, required=False
    )


class PublishedVersionIdentitySerializer(serializers.Serializer):
    """Identity of the authoritative published version."""

    id = serializers.IntegerField()
    version_number = serializers.IntegerField()
    status = serializers.ChoiceField(choices=ScheduleStatus.choices)
    published_at = serializers.DateTimeField(allow_null=True, required=False)
    published_by = ScheduleUserSummarySerializer(allow_null=True, required=False)


class PublishedScheduleResponseSerializer(serializers.Serializer):
    """Response body of ``GET /api/published-schedules/current/``.

    Entries are rendered from the version's own snapshot columns, so the official
    timetable keeps the names and times that were approved even after the live course,
    room, department, instructor or group records are renamed.
    """

    semester = SemesterSummarySerializer()
    schedule = ScheduleIdentitySerializer()
    version = PublishedVersionIdentitySerializer()
    entries = ScheduleEntrySerializer(many=True)
