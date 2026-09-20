"""
Academics models.

Phase 1 introduced the minimal ``Department``. Phase 2 adds the academic
hierarchy — ``College`` -> ``Department`` -> ``StudyProgram`` -> ``StudyStage``
-> ``StudentGroup`` (with optional subgroups) — plus the college-wide calendar
(``AcademicYear``, ``Semester``).

Courses, course offerings, instructors, rooms and scheduling are not part of
this phase.

Timestamps are timezone-aware: ``USE_TZ = True`` with ``Asia/Baghdad`` as the
application timezone (see ``config/settings.py``). No manual UTC offsets are
applied anywhere in this module.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class College(models.Model):
    """An academic college. The deployment currently serves a single college."""

    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Short college identifier, for example AI, ENG or MED.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "college"
        verbose_name_plural = "colleges"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Department(models.Model):
    """An academic department, the unit that owns programs and schedules."""

    college = models.ForeignKey(
        College,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="departments",
        help_text="Owning college. Nullable so department rows created before Phase 2 stay valid.",
    )
    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Short department identifier, for example BIOAI or CS.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "department"
        verbose_name_plural = "departments"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class AcademicYear(models.Model):
    """An academic year, stored as its two consecutive calendar years."""

    start_year = models.PositiveSmallIntegerField()
    end_year = models.PositiveSmallIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-start_year",)
        verbose_name = "academic year"
        verbose_name_plural = "academic years"
        constraints = [
            models.UniqueConstraint(
                fields=("start_year", "end_year"),
                name="unique_academic_year_range",
            ),
            models.CheckConstraint(
                condition=models.Q(end_year=models.F("start_year") + 1),
                name="academic_year_years_are_consecutive",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.end_year != self.start_year + 1
        ):
            raise ValidationError(
                {"end_year": "End year must be exactly one year after the start year."}
            )

    def __str__(self) -> str:
        return f"{self.start_year}-{self.end_year}"


class SemesterNumber(models.IntegerChoices):
    """The two standard semesters of an academic year."""

    FIRST = 1, "First"
    SECOND = 2, "Second"


class Semester(models.Model):
    """A semester of an academic year. Dates are optional until published."""

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="semesters",
    )
    number = models.PositiveSmallIntegerField(choices=SemesterNumber.choices)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-academic_year__start_year", "number")
        verbose_name = "semester"
        verbose_name_plural = "semesters"
        constraints = [
            models.UniqueConstraint(
                fields=("academic_year", "number"),
                name="unique_semester_number_per_academic_year",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(start_date__isnull=True)
                    | models.Q(end_date__isnull=True)
                    | models.Q(end_date__gte=models.F("start_date"))
                ),
                name="semester_end_date_not_before_start_date",
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "End date must be on or after the start date."}
            )

    def __str__(self) -> str:
        return f"{self.academic_year} — Semester {self.number}"


class StudyType(models.TextChoices):
    """Stable study levels. Study programs must use one of these values."""

    UNDERGRADUATE = "UNDERGRADUATE", "Undergraduate"
    MASTER = "MASTER", "Master"
    PHD = "PHD", "PhD"


class StudyProgram(models.Model):
    """A study program offered by a department, for example "Biomedical AI"."""

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="programs",
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20)
    study_type = models.CharField(max_length=20, choices=StudyType.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "study program"
        verbose_name_plural = "study programs"
        constraints = [
            models.UniqueConstraint(
                fields=("department", "code"),
                name="unique_program_code_per_department",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class StudyStage(models.Model):
    """A stage/year inside a program.

    The number and free-form name keep undergraduate, master's and PhD
    structures expressible without hard-coding a stage count.
    """

    program = models.ForeignKey(
        StudyProgram,
        on_delete=models.PROTECT,
        related_name="stages",
    )
    number = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("program__name", "number")
        verbose_name = "study stage"
        verbose_name_plural = "study stages"
        constraints = [
            models.UniqueConstraint(
                fields=("program", "number"),
                name="unique_stage_number_per_program",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1),
                name="study_stage_number_is_positive",
            ),
        ]

    def clean(self):
        super().clean()
        if self.number is not None and self.number < 1:
            raise ValidationError({"number": "Stage number must be greater than zero."})

    def __str__(self) -> str:
        return f"{self.program} — {self.name}"


class StudentGroup(models.Model):
    """A student group inside a stage, optionally split into subgroups."""

    stage = models.ForeignKey(
        StudyStage,
        on_delete=models.PROTECT,
        related_name="groups",
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    student_count = models.PositiveIntegerField(default=0)
    parent_group = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subgroups",
        help_text="Parent group when this group is a practical-class subgroup.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("stage", "code")
        verbose_name = "student group"
        verbose_name_plural = "student groups"
        constraints = [
            models.UniqueConstraint(
                fields=("stage", "code"),
                name="unique_group_code_per_stage",
            ),
            models.CheckConstraint(
                condition=~models.Q(pk=models.F("parent_group")),
                name="student_group_parent_group_not_self",
            ),
        ]

    def clean(self):
        """Enforce the subgroup hierarchy rules that SQL alone cannot express."""
        super().clean()
        errors = {}

        if self.student_count is not None and self.student_count < 0:
            errors["student_count"] = "Student count cannot be negative."

        if self.parent_group_id is not None:
            if self.pk is not None and self.parent_group_id == self.pk:
                errors["parent_group"] = "A group cannot be its own parent."
            else:
                parent = self.parent_group
                if parent is not None:
                    if self.stage_id is not None and parent.stage_id != self.stage_id:
                        errors["parent_group"] = (
                            "A subgroup must belong to the same stage as its parent group."
                        )
                    elif self._parent_chain_contains_self(parent):
                        errors["parent_group"] = (
                            "Subgroup hierarchy cannot contain a cycle."
                        )

        if errors:
            raise ValidationError(errors)

    def _parent_chain_contains_self(self, parent) -> bool:
        """Return True when walking up from ``parent`` reaches this group."""
        visited = {self.pk} if self.pk is not None else set()
        current = parent
        while current is not None:
            if current.pk in visited:
                return True
            visited.add(current.pk)
            current = current.parent_group
        return False

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"
