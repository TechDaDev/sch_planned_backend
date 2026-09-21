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
from scheduling.services.solver import DEFAULT_MAX_TIME_SECONDS, SolverStatus
from scheduling.services.validation import Severity, ValidationScope

#: Bounds the API accepts for the solver time limit.
MIN_GENERATION_TIME_SECONDS = 1
MAX_GENERATION_TIME_SECONDS = 120

#: College-wide problems are naturally larger, so their default and ceiling differ.
DEFAULT_COLLEGE_GENERATION_TIME_SECONDS = 60
MIN_COLLEGE_GENERATION_TIME_SECONDS = 1
MAX_COLLEGE_GENERATION_TIME_SECONDS = 300


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


class CollegeScheduleGenerationInputSerializer(serializers.Serializer):
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

    def to_internal_value(self, data):
        """Reject any field this endpoint does not define.

        ``department`` and ``scope`` matter most: both would imply a scope the
        endpoint does not have. Solver controls do not exist either, because the
        engine options are fixed for reproducibility.
        """
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
