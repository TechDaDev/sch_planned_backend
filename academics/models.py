"""
Academics models.

Phase 1 introduced the minimal ``Department``. Phase 2 added the academic
hierarchy — ``College`` -> ``Department`` -> ``StudyProgram`` -> ``StudyStage``
-> ``StudentGroup`` (with optional subgroups) — plus the college-wide calendar
(``AcademicYear``, ``Semester``).

Phase 3 adds the teaching structure: ``Course`` (catalog definition),
``CourseOffering`` (one delivery in a semester), ``TeachingComponent``
(theory/practical parts with weekly hours) and ``TeachingComponentGroup``
(which groups attend a component, including combined and joint
inter-department teaching).

Instructors, rooms and scheduling remain out of scope.

Timestamps are timezone-aware: ``USE_TZ = True`` with ``Asia/Baghdad`` as the
application timezone (see ``config/settings.py``). No manual UTC offsets are
applied anywhere in this module.
"""

from decimal import Decimal

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

    def ancestor_ids(self) -> set[int]:
        """Return the primary keys of the parent chain above this group."""
        ancestors: set[int] = set()
        current = self.parent_group
        while current is not None and current.pk not in ancestors:
            ancestors.add(current.pk)
            current = current.parent_group
        return ancestors

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Course(models.Model):
    """Catalog definition of a course owned by a department.

    Delivery details (semester, hours, groups, instructors, rooms) deliberately
    live on ``CourseOffering`` and ``TeachingComponent`` so the catalog entry can
    be reused across semesters.
    """

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="courses",
        help_text="Department that owns the course academically.",
    )
    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=20,
        help_text="Course code, for example ML301 or BIO102.",
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "course"
        verbose_name_plural = "courses"
        constraints = [
            models.UniqueConstraint(
                fields=("department", "code"),
                name="unique_course_code_per_department",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class CourseOffering(models.Model):
    """One delivery of a course in a semester.

    The offering's semester already determines the academic year, so no
    redundant academic-year field is stored here.
    """

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="offerings",
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="course_offerings",
    )
    managing_department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="managed_course_offerings",
        help_text="Department responsible for delivering the offering.",
    )
    offering_code = models.CharField(
        max_length=20,
        default="MAIN",
        help_text="Short instance label, for example MAIN, A or EVENING.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("course__code", "offering_code")
        verbose_name = "course offering"
        verbose_name_plural = "course offerings"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "semester", "offering_code"),
                name="unique_offering_code_per_course_semester",
            ),
        ]

    @property
    def total_weekly_hours(self) -> Decimal:
        """Weekly hours of the offering's active teaching components.

        Uses ``active_components`` when the queryset prefetched it, so list
        endpoints stay free of N+1 queries.
        """
        components = getattr(self, "active_components", None)
        if components is None:
            components = self.components.filter(is_active=True)
        return sum(
            (component.weekly_hours for component in components),
            Decimal("0.00"),
        )

    def clean(self):
        super().clean()
        if self.course_id and self.managing_department_id:
            if self.course.department_id != self.managing_department_id:
                raise ValidationError(
                    {
                        "managing_department": (
                            "The managing department must be the department that owns the course."
                        )
                    }
                )

    def __str__(self) -> str:
        return f"{self.course} — {self.semester} [{self.offering_code}]"


class TeachingComponentType(models.TextChoices):
    """Teaching component kinds. Further kinds can be added without redesign."""

    THEORY = "THEORY", "Theory"
    PRACTICAL = "PRACTICAL", "Practical"


class TeachingComponent(models.Model):
    """A theoretical or practical part of a course offering.

    ``sessions_per_week`` is derived from the hours and never stored.
    """

    offering = models.ForeignKey(
        CourseOffering,
        on_delete=models.PROTECT,
        related_name="components",
    )
    component_type = models.CharField(
        max_length=20,
        choices=TeachingComponentType.choices,
    )
    label = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Human-readable label; not semantically authoritative.",
    )
    weekly_hours = models.DecimalField(max_digits=5, decimal_places=2)
    session_duration_hours = models.DecimalField(max_digits=5, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("offering", "component_type", "label")
        verbose_name = "teaching component"
        verbose_name_plural = "teaching components"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weekly_hours__gt=0),
                name="teaching_component_weekly_hours_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(session_duration_hours__gt=0),
                name="teaching_component_session_duration_positive",
            ),
        ]

    @property
    def sessions_per_week(self) -> int | None:
        """Whole number of weekly sessions, or None until both hours are set."""
        if not self.weekly_hours or not self.session_duration_hours:
            return None
        return int(self.weekly_hours / self.session_duration_hours)

    def clean(self):
        """Require positive hours that divide into whole weekly sessions."""
        super().clean()
        errors = {}
        weekly_hours = self.weekly_hours
        session_duration = self.session_duration_hours

        if weekly_hours is not None and weekly_hours <= 0:
            errors["weekly_hours"] = "Weekly hours must be greater than zero."
        if session_duration is not None and session_duration <= 0:
            errors["session_duration_hours"] = (
                "Session duration must be greater than zero."
            )

        if not errors and weekly_hours is not None and session_duration is not None:
            if weekly_hours < session_duration:
                errors["weekly_hours"] = (
                    "Weekly hours must be at least one session duration."
                )
            else:
                sessions = weekly_hours / session_duration
                if sessions != sessions.to_integral_value():
                    errors["session_duration_hours"] = (
                        "Session duration must divide the weekly hours into whole "
                        "sessions; rounding is not applied."
                    )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        label = self.label or self.get_component_type_display()
        return f"{self.offering} — {label}"


class TeachingComponentGroup(models.Model):
    """Attaches a student group (or subgroup) to a teaching component.

    One component may serve several groups: combined lecture groups, practical
    subgroups and joint inter-department courses are all expressed here.
    """

    teaching_component = models.ForeignKey(
        TeachingComponent,
        on_delete=models.PROTECT,
        related_name="group_links",
    )
    student_group = models.ForeignKey(
        StudentGroup,
        on_delete=models.PROTECT,
        related_name="component_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("teaching_component", "student_group")
        verbose_name = "teaching component group"
        verbose_name_plural = "teaching component groups"
        constraints = [
            models.UniqueConstraint(
                fields=("teaching_component", "student_group"),
                name="unique_group_per_teaching_component",
            ),
        ]

    def clean(self):
        """Reject overlapping group hierarchies inside one component.

        A component must not hold a group and one of its ancestors or
        descendants, because those students would be represented twice.
        """
        super().clean()
        if self.teaching_component_id is None or self.student_group_id is None:
            return

        group = self.student_group
        ancestor_ids = group.ancestor_ids()
        conflicts = self.teaching_component.group_links.exclude(pk=self.pk)

        for link in conflicts.select_related("student_group"):
            other = link.student_group
            if other.pk == group.pk:
                message = "This group is already attached to the teaching component."
            elif other.pk in ancestor_ids:
                message = (
                    "A teaching component cannot contain both a group and one of its "
                    "ancestor groups."
                )
            elif group.pk in other.ancestor_ids():
                message = (
                    "A teaching component cannot contain both a group and one of its "
                    "descendant groups."
                )
            else:
                continue
            raise ValidationError({"student_group": message})

    def __str__(self) -> str:
        return f"{self.teaching_component} → {self.student_group}"
