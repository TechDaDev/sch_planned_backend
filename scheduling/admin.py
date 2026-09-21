"""Django admin registration for the scheduling app."""

from django.contrib import admin

from scheduling.models import BreakPeriod, CalendarException, TimeSlot, WorkingDay


@admin.register(WorkingDay)
class WorkingDayAdmin(admin.ModelAdmin):
    list_display = ("semester", "day_of_week", "start_time", "end_time", "is_active")
    list_filter = ("is_active", "day_of_week", "semester")
    search_fields = ("semester__academic_year__start_year",)
    list_select_related = ("semester", "semester__academic_year")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = (
        "working_day",
        "sequence",
        "label",
        "start_time",
        "end_time",
        "is_active",
    )
    list_filter = ("is_active", "working_day__day_of_week", "working_day__semester")
    search_fields = ("label",)
    list_select_related = ("working_day", "working_day__semester")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BreakPeriod)
class BreakPeriodAdmin(admin.ModelAdmin):
    list_display = ("working_day", "name", "start_time", "end_time", "is_active")
    list_filter = ("is_active", "working_day__day_of_week", "working_day__semester")
    search_fields = ("name",)
    list_select_related = ("working_day", "working_day__semester")
    readonly_fields = ("created_at", "updated_at")


@admin.register(CalendarException)
class CalendarExceptionAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "exception_type",
        "scope_type",
        "semester",
        "title",
        "is_active",
    )
    list_filter = (
        "is_active",
        "exception_type",
        "scope_type",
        "semester",
        "department",
    )
    search_fields = ("title", "description")
    list_select_related = (
        "semester",
        "semester__academic_year",
        "department",
        "instructor",
        "room",
        "student_group",
    )
    readonly_fields = ("created_at", "updated_at")
