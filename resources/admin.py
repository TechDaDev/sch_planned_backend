"""Django admin registration for the resources app."""

from django.contrib import admin

from resources.models import (
    InstructorAvailability,
    InstructorDepartmentAccess,
    InstructorPreference,
    InstructorProfile,
    TeachingAssignment,
)


@admin.register(InstructorProfile)
class InstructorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "staff_code",
        "primary_department",
        "sharing_scope",
        "is_active",
    )
    list_filter = ("is_active", "sharing_scope", "primary_department")
    search_fields = ("full_name", "staff_code", "user__username")
    list_select_related = ("primary_department", "user")
    readonly_fields = ("created_at", "updated_at")


@admin.register(InstructorDepartmentAccess)
class InstructorDepartmentAccessAdmin(admin.ModelAdmin):
    list_display = ("instructor", "department", "is_active", "created_at")
    list_filter = ("is_active", "department")
    search_fields = ("instructor__full_name", "instructor__staff_code")
    list_select_related = ("instructor", "instructor__primary_department", "department")
    readonly_fields = ("created_at", "updated_at")


@admin.register(InstructorAvailability)
class InstructorAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        "instructor",
        "semester",
        "day_of_week",
        "start_time",
        "end_time",
        "is_active",
    )
    list_filter = ("is_active", "day_of_week", "semester")
    search_fields = ("instructor__full_name", "instructor__staff_code")
    list_select_related = ("instructor", "semester", "semester__academic_year")
    readonly_fields = ("created_at", "updated_at")


@admin.register(InstructorPreference)
class InstructorPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "instructor",
        "semester",
        "day_of_week",
        "start_time",
        "end_time",
        "preference_type",
        "is_active",
    )
    list_filter = ("is_active", "preference_type", "day_of_week", "semester")
    search_fields = ("instructor__full_name", "instructor__staff_code")
    list_select_related = ("instructor", "semester", "semester__academic_year")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TeachingAssignment)
class TeachingAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "instructor",
        "teaching_component",
        "assignment_role",
        "is_active",
    )
    list_filter = (
        "is_active",
        "assignment_role",
        "instructor__primary_department",
        "teaching_component__offering__managing_department",
    )
    search_fields = (
        "instructor__full_name",
        "instructor__staff_code",
        "teaching_component__label",
        "teaching_component__offering__course__name",
        "teaching_component__offering__course__code",
    )
    list_select_related = (
        "instructor",
        "teaching_component",
        "teaching_component__offering",
        "teaching_component__offering__course",
    )
    readonly_fields = ("created_at", "updated_at")
