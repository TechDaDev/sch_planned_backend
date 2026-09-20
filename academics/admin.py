"""Django admin registration for the academics app."""

from django.contrib import admin

from academics.models import (
    AcademicYear,
    College,
    Department,
    Semester,
    StudentGroup,
    StudyProgram,
    StudyStage,
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
