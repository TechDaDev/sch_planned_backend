"""Django admin registration for the academics app."""

from django.contrib import admin

from academics.models import (
    AcademicYear,
    College,
    Course,
    CourseOffering,
    Department,
    Semester,
    StudentGroup,
    StudyProgram,
    StudyStage,
    TeachingComponent,
    TeachingComponentGroup,
)


@admin.register(College)
class CollegeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "college", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "college")
    search_fields = ("name", "code")
    list_select_related = ("college",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("start_year", "end_year", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("=start_year", "=end_year")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("academic_year", "number", "start_date", "end_date", "is_active")
    list_filter = ("is_active", "number", "academic_year")
    list_select_related = ("academic_year",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(StudyProgram)
class StudyProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "study_type", "department", "is_active")
    list_filter = ("is_active", "study_type", "department")
    search_fields = ("name", "code")
    list_select_related = ("department",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(StudyStage)
class StudyStageAdmin(admin.ModelAdmin):
    list_display = ("program", "number", "name", "is_active")
    list_filter = ("is_active", "program__department")
    search_fields = ("name", "program__name", "program__code")
    list_select_related = ("program", "program__department")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StudentGroup)
class StudentGroupAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "stage",
        "student_count",
        "parent_group",
        "is_active",
    )
    list_filter = ("is_active", "stage__program__department")
    search_fields = ("name", "code", "stage__name", "stage__program__name")
    list_select_related = ("stage", "stage__program", "parent_group")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "department", "is_active")
    list_filter = ("is_active", "department")
    search_fields = ("name", "code", "department__name", "department__code")
    list_select_related = ("department",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = (
        "course",
        "semester",
        "offering_code",
        "managing_department",
        "is_active",
    )
    list_filter = ("is_active", "managing_department", "semester")
    search_fields = ("course__name", "course__code", "offering_code")
    list_select_related = (
        "course",
        "course__department",
        "semester",
        "semester__academic_year",
        "managing_department",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(TeachingComponent)
class TeachingComponentAdmin(admin.ModelAdmin):
    list_display = (
        "offering",
        "component_type",
        "label",
        "weekly_hours",
        "session_duration_hours",
        "is_active",
    )
    list_filter = ("is_active", "component_type", "offering__managing_department")
    search_fields = ("label", "offering__course__name", "offering__course__code")
    list_select_related = ("offering", "offering__course", "offering__semester")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TeachingComponentGroup)
class TeachingComponentGroupAdmin(admin.ModelAdmin):
    list_display = ("teaching_component", "student_group", "created_at")
    list_filter = (
        "teaching_component__component_type",
        "student_group__stage__program__department",
    )
    search_fields = (
        "teaching_component__label",
        "teaching_component__offering__course__name",
        "student_group__name",
        "student_group__code",
    )
    list_select_related = (
        "teaching_component",
        "teaching_component__offering",
        "student_group",
        "student_group__stage",
    )
    readonly_fields = ("created_at",)
