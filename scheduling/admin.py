"""Django admin registration for the scheduling app.

Persisted schedules are registered read-oriented: they are written by the
persistence service and never edited by hand, because a version is an immutable
snapshot and a half-edited history is worse than none. The admin classes carry no
generation or persistence logic of their own.
"""

from django.contrib import admin

from scheduling.models import (
    AuditEvent,
    BreakPeriod,
    CalendarException,
    Schedule,
    ScheduleEntry,
    ScheduleEntryInstructor,
    ScheduleEntryStudentGroup,
    ScheduleEntryTimeSlot,
    ScheduleVersion,
    TimeSlot,
    WorkingDay,
)


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


class ScheduleEntryTimeSlotInline(admin.TabularInline):
    """Occupied periods of an entry, shown as snapshots."""

    model = ScheduleEntryTimeSlot
    extra = 0
    ordering = ("position",)
    readonly_fields = (
        "time_slot",
        "position",
        "sequence_snapshot",
        "label_snapshot",
        "start_time_snapshot",
        "end_time_snapshot",
    )
    can_delete = False


class ScheduleEntryInstructorInline(admin.TabularInline):
    """Instructors included in an entry."""

    model = ScheduleEntryInstructor
    extra = 0
    readonly_fields = (
        "instructor",
        "assignment_role_snapshot",
        "full_name_snapshot",
    )
    can_delete = False


class ScheduleEntryStudentGroupInline(admin.TabularInline):
    """Student groups included in an entry, with their departments."""

    model = ScheduleEntryStudentGroup
    extra = 0
    readonly_fields = (
        "student_group",
        "code_snapshot",
        "name_snapshot",
        "department_id_snapshot",
        "department_code_snapshot",
        "department_name_snapshot",
    )
    can_delete = False


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    """Logical timetables. Created by generating a draft, never by hand."""

    list_display = ("id", "semester", "scope", "department", "published_version", "created_at")
    list_filter = ("scope", "semester")
    search_fields = ("department__code", "department__name")
    list_select_related = (
        "semester",
        "semester__academic_year",
        "department",
        "published_version",
    )
    readonly_fields = ("created_at", "updated_at", "published_version")


@admin.register(ScheduleVersion)
class ScheduleVersionAdmin(admin.ModelAdmin):
    """Immutable versions. Read-oriented: a stored snapshot is not edited."""

    list_display = (
        "id",
        "schedule",
        "version_number",
        "status",
        "source",
        "parent_version",
        "solver_status",
        "created_at",
    )
    list_filter = ("status", "source", "solver_status", "schedule__scope")
    search_fields = ("notes",)
    list_select_related = ("schedule", "schedule__semester", "created_by", "parent_version")
    readonly_fields = (
        "created_at",
        "submitted_by",
        "submitted_at",
        "reviewed_by",
        "reviewed_at",
        "approved_by",
        "approved_at",
        "published_by",
        "published_at",
    )

    def has_change_permission(self, request, obj=None) -> bool:
        """History is append-only, so the admin never edits a version.

        A manual edit is a copy-on-write API operation, not an admin form: editing a
        stored snapshot here would bypass versioning entirely.
        """
        return False


@admin.register(ScheduleEntry)
class ScheduleEntryAdmin(admin.ModelAdmin):
    """Persisted weekly sessions, shown with their snapshot children."""

    list_display = (
        "id",
        "session_id",
        "schedule_version",
        "day_of_week",
        "start_time",
        "room_code_snapshot",
        "penalty",
    )
    list_filter = ("day_of_week", "managing_department")
    search_fields = ("session_id", "course_code_snapshot", "course_name_snapshot")
    list_select_related = ("schedule_version", "teaching_component", "room")
    readonly_fields = ("created_at",)
    inlines = (
        ScheduleEntryTimeSlotInline,
        ScheduleEntryInstructorInline,
        ScheduleEntryStudentGroupInline,
    )


@admin.register(ScheduleEntryTimeSlot)
class ScheduleEntryTimeSlotAdmin(admin.ModelAdmin):
    list_display = ("id", "schedule_entry", "position", "time_slot")
    list_select_related = ("schedule_entry", "time_slot")


@admin.register(ScheduleEntryInstructor)
class ScheduleEntryInstructorAdmin(admin.ModelAdmin):
    list_display = ("id", "schedule_entry", "instructor", "assignment_role_snapshot")
    list_select_related = ("schedule_entry", "instructor")


@admin.register(ScheduleEntryStudentGroup)
class ScheduleEntryStudentGroupAdmin(admin.ModelAdmin):
    list_display = ("id", "schedule_entry", "student_group", "code_snapshot")
    list_select_related = ("schedule_entry", "student_group")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """The audit trail, readable and immutable - including from the admin.

    Adding, changing and deleting are all refused, and the model exposes no delete
    endpoint anywhere: an audit record that an administrator can edit is not evidence.
    The queryset is served read-only through ``has_*_permission`` overrides, so the admin
    cannot be used as a back door around that rule.
    """

    list_display = (
        "created_at",
        "action",
        "actor_username_snapshot",
        "actor_role_snapshot",
        "department",
        "object_type",
        "object_id",
    )
    list_filter = ("action", "actor_role_snapshot", "department")
    search_fields = ("actor_username_snapshot", "object_id", "request_id")
    list_select_related = ("actor", "department", "semester", "schedule")
    readonly_fields = (
        "id",
        "created_at",
        "action",
        "actor",
        "actor_username_snapshot",
        "actor_role_snapshot",
        "department",
        "semester",
        "schedule",
        "schedule_version",
        "object_type",
        "object_id",
        "request_id",
        "metadata",
    )
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def get_actions(self, request):
        """No bulk actions, so no bulk deletion is reachable from the admin."""
        return {}
