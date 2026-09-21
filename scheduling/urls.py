"""URLconf for the calendar and time configuration API (mounted under ``/api/``)."""

from rest_framework.routers import SimpleRouter

from scheduling.views import (
    BreakPeriodViewSet,
    CalendarExceptionViewSet,
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

urlpatterns = router.urls
