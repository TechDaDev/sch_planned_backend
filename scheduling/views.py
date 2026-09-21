"""Calendar and time configuration API views.

The grid resources (working days, time slots, breaks) are college-wide: everyone
authenticated reads them, only college administrators write them. Calendar
exceptions are scope-aware, so they reuse the department-visibility mixin and a
dedicated permission class.

Nothing here assigns resources to slots — that arrives with schedule entries in a
later phase.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated

from academics.permissions import IsCollegeAdminOrReadOnly
from academics.views import AcademicStructureViewSet, DepartmentVisibilityQuerysetMixin
from resources.views import QueryParameterFilterMixin
from scheduling.models import BreakPeriod, CalendarException, TimeSlot, WorkingDay
from scheduling.permissions import (
    CanManageCalendarExceptions,
    visible_calendar_exceptions_filter,
)
from scheduling.serializers import (
    BreakPeriodSerializer,
    BreakPeriodWriteSerializer,
    CalendarExceptionSerializer,
    CalendarExceptionWriteSerializer,
    TimeSlotSerializer,
    TimeSlotWriteSerializer,
    WorkingDaySerializer,
    WorkingDayWriteSerializer,
)

CALENDAR_TAGS = ["calendar"]


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
