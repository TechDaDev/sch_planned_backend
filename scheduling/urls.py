"""URLconf for the calendar, scheduling and persistence APIs (mounted under ``/api/``)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from scheduling.views import (
    AuditEventViewSet,
    BreakPeriodViewSet,
    CalendarExceptionViewSet,
    CollegeScheduleDraftView,
    CollegeScheduleGenerationView,
    DepartmentScheduleDraftView,
    DepartmentScheduleGenerationView,
    PreSchedulingValidationView,
    PublishedScheduleAnalyticsView,
    PublishedScheduleCurrentView,
    PublishedScheduleExportPdfView,
    PublishedScheduleExportXlsxView,
    ScheduleVersionViewSet,
    ScheduleViewSet,
    SemesterPlanApplyView,
    SemesterPlanTemplateView,
    SemesterPlanValidateView,
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
# Phase 11: persisted schedules and their immutable versions. Both are read-only.
router.register("schedules", ScheduleViewSet, basename="schedule")
router.register(
    "schedule-versions", ScheduleVersionViewSet, basename="schedule-version"
)
# Phase 16: the audit trail, read-only like every other operational record.
router.register("audit-events", AuditEventViewSet, basename="audit-event")

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
    # Phase 11: the generate-and-persist endpoints sit before the router so that
    # "schedules/generate-department-draft/" is not read as a schedule detail id.
    path(
        "schedules/generate-department-draft/",
        DepartmentScheduleDraftView.as_view(),
        name="department-schedule-draft",
    ),
    path(
        "schedules/generate-college-draft/",
        CollegeScheduleDraftView.as_view(),
        name="college-schedule-draft",
    ),
    # Phase 13: the official timetable, readable outside schedule management. It is an
    # action path rather than a collection because there is exactly one current
    # publication per semester.
    path(
        "published-schedules/current/",
        PublishedScheduleCurrentView.as_view(),
        name="published-schedule-current",
    ),
    # Phase 14: read-only analytics over the same authoritative publication.
    path(
        "published-schedules/current/analytics/",
        PublishedScheduleAnalyticsView.as_view(),
        name="published-schedule-analytics",
    ),
    # Phase 15: the same authoritative publication as a downloadable workbook or PDF.
    path(
        "published-schedules/current/export/xlsx/",
        PublishedScheduleExportXlsxView.as_view(),
        name="published-schedule-export-xlsx",
    ),
    path(
        "published-schedules/current/export/pdf/",
        PublishedScheduleExportPdfView.as_view(),
        name="published-schedule-export-pdf",
    ),
    # Phase 15: the semester teaching plan template and import. These are the only
    # multipart endpoints in the API; each opts in through its own parser_classes.
    path(
        "imports/semester-plan/template/",
        SemesterPlanTemplateView.as_view(),
        name="semester-plan-template",
    ),
    path(
        "imports/semester-plan/validate/",
        SemesterPlanValidateView.as_view(),
        name="semester-plan-validate",
    ),
    path(
        "imports/semester-plan/apply/",
        SemesterPlanApplyView.as_view(),
        name="semester-plan-apply",
    ),
    *router.urls,
]
