"""Calendar, scheduling, persistence and read API views.

The grid resources (working days, time slots, breaks) are college-wide: everyone
authenticated reads them, only college administrators write them. Calendar
exceptions are scope-aware, so they reuse the department-visibility mixin and a
dedicated permission class. Schedule drafts are written only by the persistence
service, and read through scoped, read-only viewsets.
"""

from dataclasses import replace

from django.db.models import Count, OuterRef, Subquery
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from academics.permissions import IsCollegeAdminOrReadOnly
from academics.views import AcademicStructureViewSet, DepartmentVisibilityQuerysetMixin
from academics.models import Department, Semester
from resources.views import QueryParameterFilterMixin
from scheduling.models import (
    BreakPeriod,
    CalendarException,
    Schedule,
    ScheduleEntry,
    ScheduleScope,
    ScheduleVersion,
    TimeSlot,
    WorkingDay,
)
from scheduling.permissions import (
    CanEditScheduleDraft,
    CanManageCalendarExceptions,
    CanReadPublishedAnalytics,
    CanReadScheduleData,
    CanRunCollegeScheduleGeneration,
    CanRunPreSchedulingValidation,
    CanRunScheduleWorkflow,
    resolve_validation_scope,
    visible_calendar_exceptions_filter,
    visible_schedules_filter,
)
from scheduling.serializers import (
    BreakPeriodSerializer,
    BreakPeriodWriteSerializer,
    CalendarExceptionSerializer,
    CalendarExceptionWriteSerializer,
    CollegeGenerationRejectedSerializer,
    CollegeGenerationResponseSerializer,
    CollegeScheduleDraftResponseSerializer,
    CollegeScheduleGenerationInputSerializer,
    DepartmentGenerationResponseSerializer,
    GenerationRejectedSerializer,
    ManualEditApplyResponseSerializer,
    ManualEditRejectedSerializer,
    ManualEditRequestSerializer,
    ManualEditValidationResponseSerializer,
    PreSchedulingValidationInputSerializer,
    PreSchedulingValidationResponseSerializer,
    PublishedScheduleResponseSerializer,
    ScheduleDetailSerializer,
    ScheduleAnalyticsResponseSerializer,
    ScheduleDraftCollegeInputSerializer,
    ScheduleDraftDepartmentInputSerializer,
    ScheduleDraftRejectedSerializer,
    ScheduleDraftResponseSerializer,
    ScheduleEntrySerializer,
    ScheduleGenerationInputSerializer,
    ScheduleSummarySerializer,
    ScheduleVersionDetailSerializer,
    ScheduleVersionSummarySerializer,
    ScheduleWorkflowActionSerializer,
    TimeSlotSerializer,
    TimeSlotWriteSerializer,
    WorkflowRejectedSerializer,
    WorkflowTransitionResponseSerializer,
    WorkflowValidationResponseSerializer,
    WorkingDaySerializer,
    WorkingDayWriteSerializer,
)
from scheduling.services.generation import (
    CollegeScheduleGenerator,
    DepartmentScheduleGenerator,
)
from scheduling.services.analytics import ScheduleAnalyticsService
from scheduling.services.manual_edit import (
    BASE_STATE_CODES,
    ManualEditChange,
    ManualEditResult,
    ManualEditService,
)
from scheduling.services.persistence import SchedulePersistenceService
from scheduling.services.validation import PreSchedulingValidator, ValidationScope
from scheduling.services.workflow import (
    ACTION_APPROVE,
    ACTION_PUBLISH,
    ACTION_REVIEW,
    ACTION_SUBMIT,
    ScheduleWorkflowService,
    WorkflowVersionValidator,
    current_published_college_schedule,
    published_entries,
)

CALENDAR_TAGS = ["calendar"]
SCHEDULING_TAGS = ["scheduling"]


@extend_schema(tags=CALENDAR_TAGS)
class WorkingDayViewSet(
    QueryParameterFilterMixin, AcademicStructureViewSet
):
    """Schedulable weekdays of a semester with their opening hours."""

    queryset = WorkingDay.objects.select_related("semester", "semester__academic_year")
    read_serializer_class = WorkingDaySerializer
    write_serializer_class = WorkingDayWriteSerializer
    permission_classes = [IsAuthenticated, IsCollegeAdminOrReadOnly]
    filter_fields = ("semester", "day_of_week", "is_active")


@extend_schema(tags=CALENDAR_TAGS)
class TimeSlotViewSet(QueryParameterFilterMixin, AcademicStructureViewSet):
    """Teaching periods inside a working day."""

    queryset = TimeSlot.objects.select_related(
        "working_day", "working_day__semester", "working_day__semester__academic_year"
    )
    read_serializer_class = TimeSlotSerializer
    write_serializer_class = TimeSlotWriteSerializer
    permission_classes = [IsAuthenticated, IsCollegeAdminOrReadOnly]
    filter_fields = ("working_day", "is_active")


@extend_schema(tags=CALENDAR_TAGS)
class BreakPeriodViewSet(QueryParameterFilterMixin, AcademicStructureViewSet):
    """Breaks inside a working day."""

    queryset = BreakPeriod.objects.select_related(
        "working_day", "working_day__semester", "working_day__semester__academic_year"
    )
    read_serializer_class = BreakPeriodSerializer
    write_serializer_class = BreakPeriodWriteSerializer
    permission_classes = [IsAuthenticated, IsCollegeAdminOrReadOnly]
    filter_fields = ("working_day", "is_active")


@extend_schema(tags=CALENDAR_TAGS)
class CalendarExceptionViewSet(
    QueryParameterFilterMixin,
    DepartmentVisibilityQuerysetMixin,
    AcademicStructureViewSet,
):
    """Dated exceptions (holidays, exams, closures, absences, ...).

    Reads are scoped by the exception's scope; writes require a college
    administrator or the department that owns the targeted resource.
    College-wide exceptions concern everybody, so a caller without a department
    still reads them (hence ``visibility_requires_department = False``) while the
    scope filter keeps every other scope out of reach.
    """

    queryset = CalendarException.objects.select_related(
        "semester",
        "semester__academic_year",
        "department",
        "instructor",
        "room",
        "student_group",
    )
    read_serializer_class = CalendarExceptionSerializer
    write_serializer_class = CalendarExceptionWriteSerializer
    permission_classes = [IsAuthenticated, CanManageCalendarExceptions]
    visibility_requires_department = False
    filter_fields = (
        "semester",
        "date",
        "exception_type",
        "scope_type",
        "department",
        "instructor",
        "room",
        "student_group",
        "is_active",
    )

    def visibility_filter(self, user):
        return visible_calendar_exceptions_filter(user)


@extend_schema(tags=SCHEDULING_TAGS)
class PreSchedulingValidationView(APIView):
    """Report whether the stored data is ready for timetable generation.

    The view only validates the request body, authorizes the requested scope,
    calls the validation service and serializes the result; all the checking lives
    in ``scheduling.services.validation``. The endpoint is read-only: it computes
    its answer and never changes scheduling or academic data.

    Scope rules: a college administrator (or superuser) may validate the whole
    college or any single department, a department administrator or scheduler only
    its own department and never the whole college, and ``VIEWER``/``INSTRUCTOR``
    may not run validation at all. A department-scoped user without a department
    fails closed.
    """

    permission_classes = [IsAuthenticated, CanRunPreSchedulingValidation]

    @extend_schema(
        summary="Validate scheduling readiness for a semester",
        description=(
            "Runs the deterministic pre-scheduling checks for one semester and "
            "scope and returns the issues that would block timetable generation. "
            "``ready`` is true only when no ERROR was found; WARNING issues never "
            "block generation. Nothing is written.\n\n"
            "The validator is a set of necessary feasibility conditions, not a "
            "solver: it does not place sessions, assign rooms, avoid collisions, "
            "optimise preferences or subtract calendar exceptions from recurring "
            "weekly capacity."
        ),
        request=PreSchedulingValidationInputSerializer,
        responses={
            200: PreSchedulingValidationResponseSerializer,
            400: OpenApiResponse(
                description=(
                    "Malformed body, unknown semester/department id, or a "
                    "department outside the caller's scope."
                )
            ),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description=(
                    "The caller's role may not run validation, or a "
                    "department-scoped caller has no department."
                )
            ),
        },
    )
    def post(self, request):
        serializer = PreSchedulingValidationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        department = resolve_validation_scope(
            request.user,
            scope=data["scope"],
            department=data.get("department"),
        )
        result = PreSchedulingValidator(
            semester=data["semester"],
            scope=data["scope"],
            department=department,
        ).run()
        return Response(
            PreSchedulingValidationResponseSerializer(result).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=SCHEDULING_TAGS)
class DepartmentScheduleGenerationView(APIView):
    """Generate a preview timetable for one department and semester.

    The view validates the request body, authorizes the department scope, calls the
    generation service and serializes the outcome. All the work - the Phase 7 gate,
    candidate building, the CP-SAT solve and the preview mapping - lives in
    ``scheduling.services.generation``.

    Nothing is persisted: no schedule model exists yet, and repeated requests
    against unchanged data return the same preview.

    Two outcomes are answered with ``409``: the Phase 7 gate refused the scope, or
    no candidate could be built for some session. A completed run that simply found
    no timetable is a ``200`` with ``generated: false``.
    """

    permission_classes = [IsAuthenticated, CanRunPreSchedulingValidation]

    @extend_schema(
        summary="Generate a department timetable preview",
        description=(
            "Builds the department's weekly scheduling problem from stored data, "
            "solves it with CP-SAT and returns the resulting preview. "
            "Department scope only; college-wide generation is "
            "``POST /api/scheduling/generate-college/``.\n\n"
            "The endpoint never writes: ``persisted`` is always false. Candidates "
            "come from exact contiguous slot blocks that sum precisely to the "
            "component's session length, from rooms the canonical Phase 5 rules "
            "allow, and from blocks every assigned instructor and the room are "
            "available for. Preference windows only influence the weighted "
            "objective, never feasibility."
        ),
        request=ScheduleGenerationInputSerializer,
        responses={
            200: DepartmentGenerationResponseSerializer,
            400: OpenApiResponse(
                description=(
                    "Malformed body, unknown semester or department id, a "
                    "department outside the caller's scope, or a time limit outside "
                    "the accepted range."
                )
            ),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description=(
                    "The caller's role may not generate schedules, or a "
                    "department-scoped caller has no department."
                )
            ),
            409: GenerationRejectedSerializer,
        },
    )
    def post(self, request):
        serializer = ScheduleGenerationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        department = resolve_validation_scope(
            request.user,
            scope=ValidationScope.DEPARTMENT,
            department=data["department"],
        )
        outcome = DepartmentScheduleGenerator(
            semester=data["semester"],
            department=department,
            max_time_seconds=data["max_time_seconds"],
        ).generate()

        if outcome.rejected:
            return Response(
                GenerationRejectedSerializer(outcome).data,
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            DepartmentGenerationResponseSerializer(outcome).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=SCHEDULING_TAGS)
class CollegeScheduleGenerationView(APIView):
    """Generate a college-wide preview timetable for one semester.

    Every active teaching component of the semester, in every department, is built
    into **one** Phase 8 problem and solved once. That is what makes a shared
    instructor, a shared room or a joint student group impossible to double-book:
    solving each department separately and merging the results cannot see the
    collisions that the college-wide problem constrains globally.

    Access is limited to a college administrator or a Django superuser. Department
    administrators, schedulers, viewers and instructors are denied whatever their
    department is, and the request body has no scope field that could relax this.

    The Phase 7 gate runs with ``COLLEGE`` scope. A gate failure answers ``409`` with
    ``PRE_SCHEDULING_VALIDATION_FAILED``, and a session without a single candidate
    answers ``409`` with ``CANDIDATE_BUILD_FAILED``; neither case calls OR-Tools. A
    completed run that finds no timetable is a ``200`` with ``generated: false``.

    Nothing is persisted: ``persisted`` is always false and no schedule model
    exists yet.
    """

    permission_classes = [IsAuthenticated, CanRunCollegeScheduleGeneration]

    @extend_schema(
        summary="Generate a college-wide timetable preview",
        description=(
            "Builds one scheduling problem across every department of the "
            "semester, solves it once with CP-SAT and returns the resulting "
            "preview. College administrators only: department administrators and "
            "schedulers cannot reach this endpoint.\n\n"
            "Because all departments share one problem, a shared instructor, a "
            "shared room and a joint student group are constrained globally "
            "instead of department by department. The endpoint never writes: "
            "``persisted`` is always false.\n\n"
            "Candidates come from exact contiguous slot blocks that sum precisely "
            "to the component's session length, from rooms the canonical Phase 5 "
            "rules allow the component's managing department to use, and from "
            "blocks every assigned instructor and the room are available for. "
            "Preference windows only influence the weighted objective, never "
            "feasibility, and the penalty weights are identical to the department "
            "endpoint's.\n\n"
            "The body is validated strictly: a field this endpoint does not define "
            "- including ``department``, ``scope`` or a solver control - is "
            "rejected with ``400`` instead of being ignored."
        ),
        request=CollegeScheduleGenerationInputSerializer,
        responses={
            200: CollegeGenerationResponseSerializer,
            400: OpenApiResponse(
                description=(
                    "Malformed body, unknown semester id, a time limit outside the "
                    "accepted range, or a field this endpoint does not define "
                    "(``department``, ``scope`` or a solver control)."
                )
            ),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description=(
                    "The caller is not a college administrator, so the college-wide "
                    "solver is out of reach."
                )
            ),
            409: CollegeGenerationRejectedSerializer,
        },
    )
    def post(self, request):
        serializer = CollegeScheduleGenerationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        outcome = CollegeScheduleGenerator(
            semester=data["semester"],
            max_time_seconds=data["max_time_seconds"],
        ).generate()

        if outcome.rejected:
            return Response(
                CollegeGenerationRejectedSerializer(outcome).data,
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            CollegeGenerationResponseSerializer(outcome).data,
            status=status.HTTP_200_OK,
        )


# --- Phase 11: schedule drafts, history and entries -------------------------

#: Entry filters the entries action accepts on top of its version scope.
ENTRY_FILTER_FIELDS = (
    "managing_department",
    "teaching_component",
    "room",
    "day_of_week",
)


#: Manual-edit endpoints documented refusal body.
_MANUAL_EDIT_RESPONSES = {
    400: OpenApiResponse(
        description=(
            "Malformed body, an empty change list, a change that requests nothing, "
            "or an unsupported field."
        )
    ),
    401: OpenApiResponse(description="Authentication required."),
    403: OpenApiResponse(
        description="This role may not edit schedule drafts."
    ),
    404: OpenApiResponse(
        description="Unknown version, or a version outside the caller's scope."
    ),
    409: ManualEditRejectedSerializer,
}


def _manual_edit_service(request, version, data) -> ManualEditService:
    """Build the service for one request body.

    The view only translates the validated payload into value objects; every rule
    about whether the edit is allowed or valid lives in the service.
    """
    changes = [
        ManualEditChange(
            entry_id=change["entry_id"],
            time_slot_ids=(
                tuple(change["time_slot_ids"])
                if change.get("time_slot_ids") is not None
                else None
            ),
            room_id=change.get("room_id"),
        )
        for change in data["changes"]
    ]
    return ManualEditService(
        version=version,
        changes=changes,
        created_by=request.user,
        notes=data.get("notes", ""),
    )


def _base_state_issue(validation):
    """The base-version issue of a validation run, or None.

    These two codes describe the version rather than the request, so both manual-edit
    endpoints answer them with a conflict even when the caller only wanted validation.
    """
    for issue in validation.issues:
        if issue.code in BASE_STATE_CODES:
            return issue
    return None


#: Workflow actions and the one-line summary each endpoint documents.
WORKFLOW_ACTION_SUMMARIES = {
    ACTION_SUBMIT: "Submit a draft version for review",
    ACTION_REVIEW: "Mark a submitted version as reviewed",
    ACTION_APPROVE: "Approve a reviewed version",
    ACTION_PUBLISH: "Publish an approved college version as the official timetable",
}


def _resolve_semester_query(request):
    """Resolve the ``semester`` query parameter of the published routes.

    Shared by the published timetable and the published analytics endpoints so both
    answer the same way: ``400`` for a missing, non-numeric or unknown semester.
    """
    raw_semester = request.query_params.get("semester")
    if raw_semester in (None, ""):
        raise DRFValidationError({"semester": "This query parameter is required."})
    try:
        semester_id = int(raw_semester)
    except (TypeError, ValueError) as exc:
        raise DRFValidationError({"semester": "Use a numeric semester id."}) from exc
    semester = Semester.objects.filter(pk=semester_id).first()
    if semester is None:
        raise DRFValidationError({"semester": "Unknown semester."})
    return semester


def _version_for_response(version_id: int):
    """Re-read a version with everything its detail response needs, in one query."""
    return (
        ScheduleVersion.objects.select_related(
            "created_by",
            "parent_version",
            "submitted_by",
            "reviewed_by",
            "approved_by",
            "published_by",
            "schedule",
            "schedule__semester",
            "schedule__semester__academic_year",
            "schedule__department",
        )
        .annotate(entry_count=Count("entries"))
        .get(pk=version_id)
    )


def _schedule_annotations(queryset):
    """Add the newest-version summary fields a schedule list needs.

    A subquery per field keeps a list of schedules at one query instead of walking
    each schedule's versions, and a counter keeps ``version_count`` cheap.
    """
    latest = ScheduleVersion.objects.filter(schedule=OuterRef("pk")).order_by(
        "-version_number"
    )
    return queryset.annotate(
        version_count=Count("versions", distinct=True),
        latest_version_number=Subquery(latest.values("version_number")[:1]),
        latest_version_status=Subquery(latest.values("status")[:1]),
    ).order_by("semester_id", "scope", "department_id")


def _visible_versions(user):
    """Versions of the schedules ``user`` may read, with their entry counts.

    The scope filter runs first, so a version of an out-of-reach schedule is not
    merely hidden at render time: it is never in the queryset.
    """
    return (
        ScheduleVersion.objects.filter(
            schedule__in=Schedule.objects.filter(visible_schedules_filter(user))
        )
        .select_related(
            "schedule",
            "schedule__semester",
            "schedule__semester__academic_year",
            "schedule__department",
            "created_by",
            "parent_version",
        )
        .annotate(entry_count=Count("entries"))
        # Aggregation drops the model's default ordering, so the newest-first rule
        # of a version history is stated here instead of being inherited silently.
        .order_by("schedule_id", "-version_number")
    )


def _draft_response(
    *,
    request,
    outcome,
    semester,
    scope,
    department,
    notes,
    response_serializer_class,
    rejected_serializer_class,
):
    """Persist a generation outcome and answer the draft request.

    Order matters: the generation and the solve already finished before this runs,
    so the database write is the only thing inside the transaction. A rejected or
    incomplete result answers ``409`` with nothing written; a completed run without a
    timetable answers ``200`` with ``generated: false``.
    """
    if outcome.rejected:
        return Response(
            rejected_serializer_class(
                replace(outcome, scope=scope, rejected=True)
            ).data,
            status=status.HTTP_409_CONFLICT,
        )

    result = SchedulePersistenceService(
        semester=semester,
        scope=scope,
        department=department,
        created_by=request.user,
        notes=notes,
    ).persist(outcome)

    if result.reason is not None:
        rejection = replace(
            outcome,
            rejected=True,
            reason=result.reason,
            message=result.message,
            scope=scope,
        )
        return Response(
            rejected_serializer_class(rejection).data,
            status=status.HTTP_409_CONFLICT,
        )

    payload = response_serializer_class(outcome).data
    # The department generator deliberately leaves ``scope`` unset, because its own
    # preview response has no such field. A draft response always names it.
    payload["scope"] = scope
    payload["persisted"] = result.persisted
    if result.persisted:
        payload["schedule"] = ScheduleSummarySerializer(
            _schedule_annotations(
                Schedule.objects.select_related(
                    "semester", "semester__academic_year", "department"
                )
            ).get(pk=result.schedule.pk)
        ).data
        version = (
            ScheduleVersion.objects.select_related("created_by")
            .annotate(entry_count=Count("entries"))
            .get(pk=result.version.pk)
        )
        payload["version"] = ScheduleVersionSummarySerializer(version).data
    return Response(payload, status=status.HTTP_200_OK)


@extend_schema(tags=SCHEDULING_TAGS)
class DepartmentScheduleDraftView(APIView):
    """Generate one department's timetable and store it as a new draft version.

    The server runs the Phase 9 pipeline itself and persists its result, so a client
    cannot supply placements and skip instructor, room, group, availability, sharing
    and CP-SAT constraints. Authorization matches the Phase 9 preview endpoint:
    college administrators may draft any department, department administrators and
    schedulers their own, and department-scoped users without a department fail
    closed.

    Nothing is written unless the generation completed: a rejected or incomplete run
    answers ``409`` and leaves zero versions behind.
    """

    permission_classes = [IsAuthenticated, CanRunPreSchedulingValidation]

    @extend_schema(
        summary="Generate and persist a department draft timetable",
        description=(
            "Runs the department generation pipeline for the semester, then stores "
            "the complete result as a new ``DRAFT`` schedule version. Regenerating "
            "the same semester and department appends version 2, then 3, to the same "
            "logical schedule instead of creating a second one.\n\n"
            "The body is validated strictly: a field this endpoint does not define, "
            "including ``placements``, ``status`` or ``version_number``, is rejected "
            "with ``400``.\n\n"
            "``persisted`` is true only when a complete result was stored; the "
            "preview endpoints stay preview-only and never write."
        ),
        request=ScheduleDraftDepartmentInputSerializer,
        responses={
            200: ScheduleDraftResponseSerializer,
            400: OpenApiResponse(
                description=(
                    "Malformed body, unknown semester or department id, a "
                    "department outside the caller's scope, a time limit outside "
                    "the accepted range, or an unsupported field."
                )
            ),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description=(
                    "The caller's role may not generate schedules, or a "
                    "department-scoped caller has no department."
                )
            ),
            409: ScheduleDraftRejectedSerializer,
        },
    )
    def post(self, request):
        serializer = ScheduleDraftDepartmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        department = resolve_validation_scope(
            request.user,
            scope=ValidationScope.DEPARTMENT,
            department=data["department"],
        )
        outcome = DepartmentScheduleGenerator(
            semester=data["semester"],
            department=department,
            max_time_seconds=data["max_time_seconds"],
        ).generate()
        return _draft_response(
            request=request,
            outcome=outcome,
            semester=data["semester"],
            scope=ScheduleScope.DEPARTMENT,
            department=department,
            notes=data["notes"],
            response_serializer_class=ScheduleDraftResponseSerializer,
            rejected_serializer_class=ScheduleDraftRejectedSerializer,
        )


@extend_schema(tags=SCHEDULING_TAGS)
class CollegeScheduleDraftView(APIView):
    """Generate a college-wide timetable and store it as a new draft version.

    Only a college administrator or superuser may call it, matching the Phase 10
    preview endpoint. The whole semester is generated as one problem and stored as
    the semester's single ``COLLEGE`` schedule, which therefore owns a version
    history separate from every department schedule of the same semester.
    """

    permission_classes = [IsAuthenticated, CanRunCollegeScheduleGeneration]

    @extend_schema(
        summary="Generate and persist a college-wide draft timetable",
        description=(
            "Runs the college-wide generation pipeline for the semester, then "
            "stores the complete result as a new ``DRAFT`` version of that "
            "semester's college schedule. Regenerating appends version 2, then 3, to "
            "the same logical schedule.\n\n"
            "The body is validated strictly: ``department``, ``scope``, "
            "``placements``, ``reservations``, ``status`` and ``version_number`` "
            "are rejected with ``400``.\n\n"
            "Departments keep their own separate schedules for the same semester."
        ),
        request=ScheduleDraftCollegeInputSerializer,
        responses={
            200: CollegeScheduleDraftResponseSerializer,
            400: OpenApiResponse(
                description=(
                    "Malformed body, unknown semester id, a time limit outside the "
                    "accepted range, or an unsupported field."
                )
            ),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description=(
                    "The caller is not a college administrator, so the college-wide "
                    "draft is out of reach."
                )
            ),
            409: ScheduleDraftRejectedSerializer,
        },
    )
    def post(self, request):
        serializer = ScheduleDraftCollegeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        outcome = CollegeScheduleGenerator(
            semester=data["semester"],
            max_time_seconds=data["max_time_seconds"],
        ).generate()
        return _draft_response(
            request=request,
            outcome=outcome,
            semester=data["semester"],
            scope=ScheduleScope.COLLEGE,
            department=None,
            notes=data["notes"],
            response_serializer_class=CollegeScheduleDraftResponseSerializer,
            rejected_serializer_class=ScheduleDraftRejectedSerializer,
        )


@extend_schema(tags=SCHEDULING_TAGS)
class ScheduleViewSet(QueryParameterFilterMixin, ReadOnlyModelViewSet):
    """Read persisted schedules: list, detail and version history.

    Reads only. Creating a schedule happens by generating a draft, and no schedule
    can be deleted through the API because it is the root of a version history.
    """

    serializer_class = ScheduleSummarySerializer
    permission_classes = [IsAuthenticated, CanReadScheduleData]
    filter_fields = ("semester", "scope", "department")
    #: Declared for schema generation; every response comes from ``get_queryset``.
    queryset = Schedule.objects.all()

    def get_queryset(self):
        queryset = _schedule_annotations(
            Schedule.objects.select_related(
                "semester",
                "semester__academic_year",
                "department",
                "published_version",
            )
        )
        return queryset.filter(visible_schedules_filter(self.request.user))

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ScheduleDetailSerializer
        return ScheduleSummarySerializer

    def get_object(self):
        """Attach the newest version so the detail response stays one extra query."""
        instance = super().get_object()
        if self.action == "retrieve":
            instance.latest_version_obj = (
                ScheduleVersion.objects.filter(schedule=instance)
                .select_related("created_by")
                .annotate(entry_count=Count("entries"))
                .order_by("-version_number")
                .first()
            )
        return instance

    @extend_schema(
        summary="List the versions of one schedule",
        description=(
            "Version history of one schedule, newest first. A department user only "
            "reaches its own department's schedules and a college-wide draft stays "
            "with college administrators."
        ),
        responses=ScheduleVersionSummarySerializer(many=True),
    )
    @action(detail=True, methods=["get"], url_path="versions")
    def versions(self, request, pk=None):
        schedule = self.get_object()
        queryset = _visible_versions(request.user).filter(schedule=schedule)
        return Response(ScheduleVersionSummarySerializer(queryset, many=True).data)


@extend_schema(tags=SCHEDULING_TAGS)
class ScheduleVersionViewSet(QueryParameterFilterMixin, ReadOnlyModelViewSet):
    """Read persisted schedule versions and their entries.

    Versions are immutable snapshots: no update or delete is exposed, and entries
    are read-only rows written once by the persistence service.
    """

    serializer_class = ScheduleVersionSummarySerializer
    permission_classes = [IsAuthenticated, CanReadScheduleData]
    filter_fields = ("schedule", "status", "source")
    #: Declared for schema generation; every response comes from ``get_queryset``.
    queryset = ScheduleVersion.objects.all()

    def get_queryset(self):
        return _visible_versions(self.request.user)

    def get_serializer_class(self):
        if self.action == "entries":
            return ScheduleEntrySerializer
        if self.action == "retrieve":
            return ScheduleVersionDetailSerializer
        return ScheduleVersionSummarySerializer

    @extend_schema(
        summary="List the entries of one schedule version",
        description=(
            "The sessions stored in one version, rendered from the version's own "
            "snapshot columns, so renaming a course, room, department, instructor "
            "or group later does not change what this version shows.\n\n"
            "Optional exact-match filters: ``managing_department``, "
            "``teaching_component``, ``room``, ``day_of_week``. They narrow the "
            "authorized queryset and can never widen it."
        ),
        responses=ScheduleEntrySerializer(many=True),
    )
    @action(detail=True, methods=["get"], url_path="entries")
    def entries(self, request, pk=None):
        version = self.get_object()
        queryset = (
            ScheduleEntry.objects.filter(schedule_version=version)
            .select_related("teaching_component", "managing_department", "room")
            .prefetch_related("time_slots", "instructors", "student_groups")
        )
        for field_name in ENTRY_FILTER_FIELDS:
            raw_value = request.query_params.get(field_name)
            if raw_value in (None, ""):
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise DRFValidationError(
                    {field_name: "Use a numeric id for this filter."}
                ) from exc
            queryset = queryset.filter(**{field_name: value})
        return Response(ScheduleEntrySerializer(queryset, many=True).data)

    @extend_schema(
        summary="Validate a manual edit of a draft version",
        description=(
            "Checks whether the requested placement changes would produce a valid "
            "weekly timetable, and stores nothing. Every change is applied to an "
            "in-memory copy of the whole version first, so a swap of two sessions is "
            "judged as one final state.\n\n"
            "Placement checks cover the requested periods (existence, activity, "
            "semester, one weekday, adjacency, unchanged duration), the entry's "
            "existing instructors (active, still eligible for the managing "
            "department, available) and the target room (active, shared, satisfying "
            "the component's room requirement, available). Collision checks then "
            "run over the complete proposed version for instructors, rooms, student "
            "groups and teaching components.\n\n"
            "An invalid but well-formed proposal answers ``200`` with "
            "``valid: false``. A version that is not the newest ``DRAFT`` of its "
            "schedule answers ``409``, because editing it would branch history."
        ),
        request=ManualEditRequestSerializer,
        responses={
            200: ManualEditValidationResponseSerializer,
            **_MANUAL_EDIT_RESPONSES,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="validate-manual-edit",
        permission_classes=[IsAuthenticated, CanEditScheduleDraft],
    )
    def validate_manual_edit(self, request, pk=None):
        version = self.get_object()
        serializer = ManualEditRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validation = _manual_edit_service(
            request, version, serializer.validated_data
        ).validate_only()

        blocked = _base_state_issue(validation)
        if blocked is not None:
            return Response(
                ManualEditRejectedSerializer(
                    ManualEditResult(
                        persisted=False,
                        reason=blocked.code,
                        message=blocked.message,
                        validation=validation,
                    )
                ).data,
                status=status.HTTP_409_CONFLICT,
            )
        return Response(ManualEditValidationResponseSerializer(validation).data)

    @extend_schema(
        summary="Apply a manual edit to a draft version",
        description=(
            "Validates the requested placement changes and, when they pass, stores "
            "the result as the schedule's next ``DRAFT`` version with "
            "``source: MANUAL_EDIT`` and the edited version as its parent.\n\n"
            "The new version is a complete copy of the base version with only the "
            "requested placements replaced: sessions, instructors, student groups and "
            "every historical snapshot value are carried over, and a moved entry gets "
            "a documented manual candidate id instead of the solver's. No solver runs "
            "and nothing is re-optimised, so the version carries no solver metadata.\n\n"
            "An invalid proposal answers ``409`` with "
            "``MANUAL_EDIT_VALIDATION_FAILED`` and creates nothing. So does a base "
            "version that is not the newest ``DRAFT``, reported as "
            "``STALE_BASE_VERSION`` or ``BASE_VERSION_NOT_DRAFT``; the freshness check "
            "runs again under a lock, so two simultaneous editors cannot overwrite "
            "each other."
        ),
        request=ManualEditRequestSerializer,
        responses={
            200: ManualEditApplyResponseSerializer,
            **_MANUAL_EDIT_RESPONSES,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="manual-edit",
        permission_classes=[IsAuthenticated, CanEditScheduleDraft],
    )
    def manual_edit(self, request, pk=None):
        version = self.get_object()
        serializer = ManualEditRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = _manual_edit_service(
            request, version, serializer.validated_data
        ).apply()

        if not result.persisted:
            return Response(
                ManualEditRejectedSerializer(result).data,
                status=status.HTTP_409_CONFLICT,
            )
        return Response(ManualEditApplyResponseSerializer(result).data)

    # --- Phase 13: workflow --------------------------------------------------

    @extend_schema(
        summary="Validate a stored version against current configuration",
        description=(
            "Reports whether the stored timetable can still advance through the "
            "workflow. Every entry is measured against today's data: the component's "
            "academic chain, its current weekly session count and session length, its "
            "current teaching assignments and student groups, the stored room's "
            "current requirement and availability, every instructor's eligibility and "
            "availability, the current time grid, and the internal collisions of the "
            "version.\n\n"
            "This endpoint writes nothing. ``valid`` is true only when nothing blocks "
            "progression; every reported issue is a blocking ERROR. The publication "
            "completeness rule applies when publishing, not here."
        ),
        responses=WorkflowValidationResponseSerializer,
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="workflow-validation",
        permission_classes=[IsAuthenticated, CanRunScheduleWorkflow],
    )
    def workflow_validation(self, request, pk=None):
        version = self.get_object()
        validation = WorkflowVersionValidator(version=version).validate()
        return Response(WorkflowValidationResponseSerializer(validation).data)

    # --- Phase 14: analytics -------------------------------------------------

    @extend_schema(
        summary="Read analytics of one stored version",
        description=(
            "Computes counts, workloads, room usage, gaps and quality figures for this "
            "exact persisted version. It works for every workflow status and writes "
            "nothing.\n\n"
            "The descriptive values (course, department, room, instructor and group "
            "names, period labels and times) come from the version's snapshot columns, "
            "so renaming a live record never changes a historical report. The one "
            "exception is room utilization, which needs a denominator the snapshot does "
            "not contain: it is computed from **current** room availability and the "
            "current grid, and every room row says so in ``utilization_basis`` with "
            "``available_minutes: null`` when no denominator exists.\n\n"
            "Access is exactly the access the version already has: an out-of-scope "
            "version answers ``404``."
        ),
        responses={
            200: ScheduleAnalyticsResponseSerializer,
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description="This role may not read schedule analytics."
            ),
            404: OpenApiResponse(
                description="Unknown version, or a version outside the caller's scope."
            ),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="analytics",
        permission_classes=[IsAuthenticated, CanReadScheduleData],
    )
    def analytics(self, request, pk=None):
        version = self.get_object()
        report = ScheduleAnalyticsService.for_version(version).build()
        return Response(ScheduleAnalyticsResponseSerializer(report).data)

    def _perform_workflow_action(self, request, action: str):
        """Run one workflow action and serialize its outcome.

        The view validates the (empty) body, hands the work to the service and maps a
        refusal to ``409``. Every rule about who may advance which stage, and whether
        the stored timetable is still valid, lives in the service.
        """
        version = self.get_object()
        serializer = ScheduleWorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = ScheduleWorkflowService(
            version=version, action=action, user=request.user
        ).transition()
        if not result.applied:
            return Response(
                WorkflowRejectedSerializer(result).data,
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            WorkflowTransitionResponseSerializer(
                replace(result, version=_version_for_response(result.version.pk))
            ).data
        )

    @extend_schema(
        summary="Submit a draft version for review",
        description=(
            "Moves the latest ``DRAFT`` version of a schedule to ``SUBMITTED`` and "
            "records who did it and when. A college administrator may submit any "
            "schedule; a department administrator or scheduler may submit their own "
            "department's.\n\n"
            "The whole version is revalidated first, so a timetable that has decayed "
            "since it was created answers ``409`` with "
            "``SCHEDULE_VALIDATION_FAILED``. Only the status and the submit metadata "
            "change: no entry, period, instructor, room or snapshot is touched."
        ),
        request=ScheduleWorkflowActionSerializer,
        responses={
            200: WorkflowTransitionResponseSerializer,
            400: OpenApiResponse(description="Unsupported field in the body."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description="This role may not move this schedule through the workflow."
            ),
            404: OpenApiResponse(
                description="Unknown version, or a version outside the caller's scope."
            ),
            409: WorkflowRejectedSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="submit",
        permission_classes=[IsAuthenticated, CanRunScheduleWorkflow],
    )
    def submit(self, request, pk=None):
        return self._perform_workflow_action(request, ACTION_SUBMIT)

    @extend_schema(
        summary="Mark a submitted version as reviewed",
        description=(
            "Moves the latest ``SUBMITTED`` version to ``REVIEWED``. Only a college "
            "administrator or superuser may review: a department administrator cannot "
            "review their own department's timetable. The version is revalidated "
            "first, and only the status and the review metadata change."
        ),
        request=ScheduleWorkflowActionSerializer,
        responses={
            200: WorkflowTransitionResponseSerializer,
            400: OpenApiResponse(description="Unsupported field in the body."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description="This role may not review this schedule."
            ),
            404: OpenApiResponse(
                description="Unknown version, or a version outside the caller's scope."
            ),
            409: WorkflowRejectedSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="review",
        permission_classes=[IsAuthenticated, CanRunScheduleWorkflow],
    )
    def review(self, request, pk=None):
        return self._perform_workflow_action(request, ACTION_REVIEW)

    @extend_schema(
        summary="Approve a reviewed version",
        description=(
            "Moves the latest ``REVIEWED`` version to ``APPROVED``. Only a college "
            "administrator or superuser may approve, for department and college "
            "schedules alike. The version is revalidated first, and only the status "
            "and the approval metadata change."
        ),
        request=ScheduleWorkflowActionSerializer,
        responses={
            200: WorkflowTransitionResponseSerializer,
            400: OpenApiResponse(description="Unsupported field in the body."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description="This role may not approve this schedule."
            ),
            404: OpenApiResponse(
                description="Unknown version, or a version outside the caller's scope."
            ),
            409: WorkflowRejectedSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="approve",
        permission_classes=[IsAuthenticated, CanRunScheduleWorkflow],
    )
    def approve(self, request, pk=None):
        return self._perform_workflow_action(request, ACTION_APPROVE)

    @extend_schema(
        summary="Publish an approved college version as the official timetable",
        description=(
            "Makes the latest ``APPROVED`` version of a **college** schedule the "
            "official timetable: its status becomes ``PUBLISHED``, the publish metadata "
            "is recorded, and the schedule's authoritative ``published_version`` pointer "
            "moves to it, all in one transaction.\n\n"
            "A department schedule answers ``409`` with "
            "``DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE``: department schedules are approved "
            "inside the college but never become the authoritative timetable. An empty "
            "version answers ``409`` with ``EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED``.\n\n"
            "Publishing a newer version leaves earlier published versions "
            "``PUBLISHED``; the pointer, not the status, says which one is current, and "
            "no entry of any earlier version is deleted or modified."
        ),
        request=ScheduleWorkflowActionSerializer,
        responses={
            200: WorkflowTransitionResponseSerializer,
            400: OpenApiResponse(description="Unsupported field in the body."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description="Only a college administrator may publish."
            ),
            404: OpenApiResponse(
                description="Unknown version, or a version outside the caller's scope."
            ),
            409: WorkflowRejectedSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
        permission_classes=[IsAuthenticated, CanRunScheduleWorkflow],
    )
    def publish(self, request, pk=None):
        return self._perform_workflow_action(request, ACTION_PUBLISH)


@extend_schema(tags=SCHEDULING_TAGS)
class PublishedScheduleAnalyticsView(APIView):
    """Analytics of the officially published college timetable of one semester.

    The analysed version is the schedule's authoritative ``published_version``, never
    whichever version happens to carry ``status = PUBLISHED``: earlier publications keep
    that status as history, and only the pointer says which one is official.

    A college administrator sees the whole college. A department's administrator,
    scheduler or viewer sees the official entries that concern the department, and the
    entry set is narrowed *before* aggregation, so no figure is derived from an entry
    the caller may not see. An instructor is refused: the published timetable endpoint
    is the instructor-facing source, not this dashboard.
    """

    permission_classes = [IsAuthenticated, CanReadPublishedAnalytics]

    @extend_schema(
        summary="Read analytics of the current published college timetable",
        description=(
            "Returns the same report shape as the version analytics endpoint, computed "
            "over the current publication. Department callers get "
            "``scope: DEPARTMENT``, a ``department_scope`` block that separates the "
            "sessions their department manages from the joint sessions it merely "
            "attends, and every other section restricted to the entries they may see.\n\n"
            "A semester with no publication answers ``404``, matching the published "
            "timetable endpoint; a missing or unknown semester answers ``400``."
        ),
        parameters=[
            OpenApiParameter(
                name="semester",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Semester id whose published timetable to analyse.",
            )
        ],
        responses={
            200: ScheduleAnalyticsResponseSerializer,
            400: OpenApiResponse(
                description="Missing or unknown ``semester`` query parameter."
            ),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(
                description=(
                    "This role has no analytics access: instructors use the published "
                    "timetable endpoint, and a department-scoped account without a "
                    "department fails closed."
                )
            ),
            404: OpenApiResponse(
                description="No college schedule of this semester has been published."
            ),
        },
    )
    def get(self, request):
        semester = _resolve_semester_query(request)
        schedule = current_published_college_schedule(semester=semester)
        if schedule is None:
            return Response(
                {
                    "detail": (
                        "No college schedule of this semester has been published yet."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        department = None
        if not request.user.has_cross_department_access:
            # Fail closed: summaries cannot be narrowed for an account with no
            # department, and the whole college is out of its reach.
            if request.user.department_id is None:
                raise PermissionDenied(
                    "Your account is not attached to a department, so there is no "
                    "official timetable scope to analyse."
                )
            department = Department.objects.filter(
                pk=request.user.department_id
            ).first()
            if department is None:
                raise PermissionDenied(
                    "Your account's department no longer exists, so there is nothing "
                    "to analyse."
                )

        report = ScheduleAnalyticsService.for_published(
            schedule, department=department
        ).build()
        return Response(ScheduleAnalyticsResponseSerializer(report).data)


@extend_schema(tags=SCHEDULING_TAGS)
class PublishedScheduleCurrentView(APIView):
    """The officially published college timetable of one semester.

    This is the first endpoint meant to be consumed outside schedule management, so it
    has its own visibility rule instead of reusing draft scoping: a college
    administrator sees every entry, a department's users see the entries their
    department manages or whose student groups belong to it, and an instructor sees the
    sessions they teach. Everybody else sees an empty list, and a caller without a
    department sees nothing at all.

    Entries are rendered from the published version's stored snapshots, because the
    official timetable is the approved version, not a live view of today's names.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Read the current published college timetable",
        description=(
            "Returns the current authoritative college publication for a semester: the "
            "schedule, the published version identity and the entries the caller may "
            "see. The authoritative version comes from the schedule's "
            "``published_version`` pointer, never from a ``status=PUBLISHED`` query, "
            "because earlier published versions keep that status as history.\n\n"
            "A semester without a published college schedule answers ``404``. A caller "
            "with no published visibility receives an empty ``entries`` list rather "
            "than another department's or another instructor's timetable."
        ),
        parameters=[
            OpenApiParameter(
                name="semester",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Semester id to read the official timetable for.",
            )
        ],
        responses={
            200: PublishedScheduleResponseSerializer,
            400: OpenApiResponse(
                description="Missing or unknown ``semester`` query parameter."
            ),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(
                description="No college schedule of this semester has been published."
            ),
        },
    )
    def get(self, request):
        semester = _resolve_semester_query(request)

        schedule = current_published_college_schedule(semester=semester)
        if schedule is None:
            return Response(
                {
                    "detail": (
                        "No college schedule of this semester has been published yet."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        version = schedule.published_version
        entries = list(published_entries(version=version, user=request.user))
        return Response(
            PublishedScheduleResponseSerializer(
                {
                    "semester": semester,
                    "schedule": schedule,
                    "version": version,
                    "entries": entries,
                }
            ).data
        )
