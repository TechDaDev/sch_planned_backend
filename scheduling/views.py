"""Calendar and time configuration API views.

The grid resources (working days, time slots, breaks) are college-wide: everyone
authenticated reads them, only college administrators write them. Calendar
exceptions are scope-aware, so they reuse the department-visibility mixin and a
dedicated permission class.

Nothing here assigns resources to slots — that arrives with schedule entries in a
later phase.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.permissions import IsCollegeAdminOrReadOnly
from academics.views import AcademicStructureViewSet, DepartmentVisibilityQuerysetMixin
from resources.views import QueryParameterFilterMixin
from scheduling.models import BreakPeriod, CalendarException, TimeSlot, WorkingDay
from scheduling.permissions import (
    CanManageCalendarExceptions,
    CanRunCollegeScheduleGeneration,
    CanRunPreSchedulingValidation,
    resolve_validation_scope,
    visible_calendar_exceptions_filter,
)
from scheduling.serializers import (
    BreakPeriodSerializer,
    BreakPeriodWriteSerializer,
    CalendarExceptionSerializer,
    CalendarExceptionWriteSerializer,
    CollegeGenerationRejectedSerializer,
    CollegeGenerationResponseSerializer,
    CollegeScheduleGenerationInputSerializer,
    DepartmentGenerationResponseSerializer,
    GenerationRejectedSerializer,
    PreSchedulingValidationInputSerializer,
    PreSchedulingValidationResponseSerializer,
    ScheduleGenerationInputSerializer,
    TimeSlotSerializer,
    TimeSlotWriteSerializer,
    WorkingDaySerializer,
    WorkingDayWriteSerializer,
)
from scheduling.services.generation import (
    CollegeScheduleGenerator,
    DepartmentScheduleGenerator,
)
from scheduling.services.validation import PreSchedulingValidator, ValidationScope

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
