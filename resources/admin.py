"""Django admin registration for the resources app."""

from django.contrib import admin

from resources.models import (
    InstructorAvailability,
    InstructorDepartmentAccess,
    InstructorPreference,
    InstructorProfile,
    Room,
    RoomAvailability,
    RoomCapability,
    RoomCapabilityAssignment,
    RoomDepartmentAccess,
    RoomType,
    TeachingAssignment,
    TeachingComponentCapabilityRequirement,
    TeachingComponentRoomRequirement,
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


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RoomCapability)
class RoomCapabilityAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "owner_department",
        "room_type",
        "capacity",
        "sharing_scope",
        "is_active",
    )
    list_filter = ("is_active", "sharing_scope", "room_type", "owner_department")
    search_fields = ("name", "code", "owner_department__name", "owner_department__code")
    list_select_related = ("owner_department", "room_type")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RoomDepartmentAccess)
class RoomDepartmentAccessAdmin(admin.ModelAdmin):
    list_display = ("room", "department", "is_active", "created_at")
    list_filter = ("is_active", "department")
    search_fields = ("room__name", "room__code", "department__name", "department__code")
    list_select_related = ("room", "room__owner_department", "department")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RoomCapabilityAssignment)
class RoomCapabilityAssignmentAdmin(admin.ModelAdmin):
    list_display = ("room", "capability", "created_at")
    list_filter = ("capability", "room__room_type")
    search_fields = ("room__name", "room__code", "capability__name", "capability__code")
    list_select_related = ("room", "capability")


@admin.register(RoomAvailability)
class RoomAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("room", "semester", "day_of_week", "start_time", "end_time", "is_active")
    list_filter = ("is_active", "day_of_week", "semester", "room__room_type")
    search_fields = ("room__name", "room__code")
    list_select_related = ("room", "semester", "semester__academic_year")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TeachingComponentRoomRequirement)
class TeachingComponentRoomRequirementAdmin(admin.ModelAdmin):
    list_display = (
        "teaching_component",
        "required_room_type",
        "minimum_capacity",
        "is_active",
    )
    list_filter = (
        "is_active",
        "required_room_type",
        "teaching_component__offering__managing_department",
    )
    search_fields = (
        "teaching_component__label",
        "teaching_component__offering__course__name",
        "teaching_component__offering__course__code",
    )
    list_select_related = (
        "teaching_component",
        "teaching_component__offering",
        "teaching_component__offering__course",
        "required_room_type",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(TeachingComponentCapabilityRequirement)
class TeachingComponentCapabilityRequirementAdmin(admin.ModelAdmin):
    list_display = ("room_requirement", "capability", "created_at")
    list_filter = (
        "capability",
        "room_requirement__required_room_type",
    )
    search_fields = (
        "capability__name",
        "capability__code",
        "room_requirement__teaching_component__label",
    )
    list_select_related = (
        "capability",
        "room_requirement",
        "room_requirement__teaching_component",
    )
