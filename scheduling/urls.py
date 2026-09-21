"""URLconf for the calendar and time configuration API (mounted under ``/api/``)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from scheduling.views import (
    BreakPeriodViewSet,
    CalendarExceptionViewSet,
    CollegeScheduleGenerationView,
    DepartmentScheduleGenerationView,
    PreSchedulingValidationView,
    TimeSlotViewSet,
    WorkingDayViewSet,
)

app_name = "scheduling"

router = SimpleRouter()
router.register("working-days", WorkingDayViewSet, basename="working-day")
router.register("time-slots", TimeSlotViewSet, basename="time-slot")
router.register("break-periods", BreakPeriodViewSet, basename="break-period")
router.register(
    "calendar-exceptions", CalendarExceptionViewSet, basename="calendar-exception"
)

urlpatterns = [
    # Phase 7: a computed, read-only report rather than a resource collection, so
    # it is a plain action path and not part of the router's CRUD surface.
    path(
        "scheduling/validate/",
        PreSchedulingValidationView.as_view(),
        name="pre-scheduling-validation",
    ),
    # Phase 9: generation returns a preview and persists nothing, so it is an
    # action path too. Department scope only.
    path(
        "scheduling/generate/",
        DepartmentScheduleGenerationView.as_view(),
        name="department-schedule-generation",
    ),
    # Phase 10: college-wide generation is a separate, explicitly named path rather
    # than a ``scope`` value on the department endpoint, so neither endpoint can be
    # turned into the other by a request body.
    path(
        "scheduling/generate-college/",
        CollegeScheduleGenerationView.as_view(),
        name="college-schedule-generation",
    ),
    *router.urls,
]
