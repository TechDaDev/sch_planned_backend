"""
Scheduling configuration models: the college time grid and calendar exceptions.

Phase 6 defines the *available* scheduling positions (working days, teaching
periods, breaks) and the dates that are not schedulable. Phase 11 adds the
persisted timetable: ``Schedule`` is the logical timetable of one semester and
scope, ``ScheduleVersion`` is one immutable generated snapshot of it, and
``ScheduleEntry`` plus its three child tables record the sessions that were placed.

``academics.Weekday`` (Sunday → Thursday) is reused; Friday and Saturday are not
ordinary working days in this version.

Delete behaviour: the time grid cascades from its working day, while references
into academic and resource structure (``semester`` and the exception targets) use
``PROTECT`` so structural data cannot be removed silently. Persistence follows the
same rule — version history cascades from its schedule, but a saved entry protects
the component, room and department it refers to, because a stored version must not
become structurally corrupt when the configuration changes.

Timestamps are timezone-aware: ``USE_TZ = True`` with ``Asia/Baghdad`` as the
application timezone (see ``config/settings.py``); no manual UTC offsets.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from academics.models import (
    Department,
    Semester,
    StudentGroup,
    TeachingComponent,
    Weekday,
)
from academics.permissions import resolve_department_id
from resources.models import InstructorProfile, Room


def _find_grid_conflict(
    working_day,
    start,
    end,
    *,
    ignore_time_slot=None,
    ignore_break=None,
) -> str | None:
    """Return a message when ``(start, end)`` overlaps an active grid row.

    Shared by ``TimeSlot`` and ``BreakPeriod`` so both directions of the
    slot/break consistency rule use one implementation: a slot may not overlap an
    active break, and a break may not overlap an active slot. Inactive rows
    neither conflict nor block.
    """
    if working_day is None or start is None or end is None:
        return None

    slots = working_day.time_slots.filter(
        is_active=True, start_time__lt=end, end_time__gt=start
    )
    if ignore_time_slot is not None and ignore_time_slot.pk is not None:
        slots = slots.exclude(pk=ignore_time_slot.pk)
    if slots.exists():
        return "This window overlaps an active time slot on the same working day."

    breaks = working_day.break_periods.filter(
        is_active=True, start_time__lt=end, end_time__gt=start
    )
    if ignore_break is not None and ignore_break.pk is not None:
        breaks = breaks.exclude(pk=ignore_break.pk)
    if breaks.exists():
        return "This window overlaps an active break on the same working day."

    return None


class WorkingDay(models.Model):
    """One schedulable weekday of a semester with its opening hours.

    An active working day may contain teaching periods; an inactive one is not
    schedulable. Nothing assumes that all five weekdays exist — administrators
    configure them per semester.
    """

    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="working_days",
    )
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("semester", "day_of_week")
        verbose_name = "working day"
        verbose_name_plural = "working days"
        constraints = [
            models.UniqueConstraint(
                fields=("semester", "day_of_week"),
                name="unique_working_day_per_semester",
            ),
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="working_day_start_before_end",
            ),
        ]

    def clean(self):
        """Validate the day window and keep existing children inside it.

        Narrowing the opening hours must not silently invalidate the active time
        slots and breaks that already exist, so those are checked here.
        """
        super().clean()
        errors = {}

        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = "The working day must end after it starts."
        elif self.pk is not None:
            outside = [
                str(child)
                for child in list(self.time_slots.filter(is_active=True))
                + list(self.break_periods.filter(is_active=True))
                if child.start_time < self.start_time or child.end_time > self.end_time
            ]
            if outside:
                errors["end_time"] = (
                    "Existing active time slots or breaks fall outside the new window "
                    "and must be adjusted first: " + ", ".join(outside) + "."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.semester} — {self.get_day_of_week_display()}"


class TimeSlot(models.Model):
    """A teaching period inside a working day.

    Time slots are available scheduling positions only; no teaching component,
    instructor, room or student group is attached to them here.
    """

    working_day = models.ForeignKey(
        WorkingDay,
        on_delete=models.CASCADE,
        related_name="time_slots",
    )
    sequence = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    label = models.CharField(max_length=100, blank=True, default="")
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("working_day", "sequence")
        verbose_name = "time slot"
        verbose_name_plural = "time slots"
        constraints = [
            models.UniqueConstraint(
                fields=("working_day", "sequence"),
                name="unique_time_slot_sequence_per_working_day",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="time_slot_sequence_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="time_slot_start_before_end",
            ),
            models.UniqueConstraint(
                fields=("working_day", "start_time", "end_time"),
                condition=models.Q(is_active=True),
                name="unique_active_time_slot_window",
            ),
        ]

    @property
    def duration_minutes(self) -> int | None:
        """Length of the slot in minutes (derived, never stored)."""
        if self.start_time is None or self.end_time is None:
            return None
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        return end - start

    def clean(self):
        """Validate ordering, day boundaries and overlap with the day's grid."""
        super().clean()
        errors = {}

        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = "The time slot must end after it starts."
        else:
            if self.sequence is not None and self.sequence < 1:
                errors["sequence"] = "Sequence must be 1 or greater."
            if self.working_day_id is not None:
                working_day = self.working_day
                if (
                    self.start_time < working_day.start_time
                    or self.end_time > working_day.end_time
                ):
                    errors["start_time"] = (
                        "The time slot must fit inside the working day window."
                    )
                elif self.is_active:
                    conflict = _find_grid_conflict(
                        working_day,
                        self.start_time,
                        self.end_time,
                        ignore_time_slot=self,
                    )
                    if conflict:
                        errors["start_time"] = conflict

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        label = self.label or f"Period {self.sequence}"
        return f"{self.working_day} — {label} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class BreakPeriod(models.Model):
    """An explicit break inside a working day (morning, lunch, prayer, ...)."""

    working_day = models.ForeignKey(
        WorkingDay,
        on_delete=models.CASCADE,
        related_name="break_periods",
    )
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("working_day", "start_time")
        verbose_name = "break period"
        verbose_name_plural = "break periods"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="break_period_start_before_end",
            ),
        ]

    def clean(self):
        """Validate ordering, day boundaries and overlap with slots and breaks."""
        super().clean()
        errors = {}

        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = "The break must end after it starts."
        elif self.working_day_id is not None:
            working_day = self.working_day
            if (
                self.start_time < working_day.start_time
                or self.end_time > working_day.end_time
            ):
                errors["start_time"] = "The break must fit inside the working day window."
            elif self.is_active:
                conflict = _find_grid_conflict(
                    working_day,
                    self.start_time,
                    self.end_time,
                    ignore_break=self,
                )
                if conflict:
                    errors["start_time"] = conflict

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.working_day} — {self.name} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class ExceptionType(models.TextChoices):
    """Kind of calendar exception."""

    HOLIDAY = "HOLIDAY", "Holiday"
    EXAM = "EXAM", "Examination"
    EVENT = "EVENT", "Event"
    MAINTENANCE = "MAINTENANCE", "Maintenance"
    INSTRUCTOR_ABSENCE = "INSTRUCTOR_ABSENCE", "Instructor absence"
    ROOM_CLOSURE = "ROOM_CLOSURE", "Room closure"


class ExceptionScope(models.TextChoices):
    """What a calendar exception targets."""

    COLLEGE = "COLLEGE", "College-wide"
    DEPARTMENT = "DEPARTMENT", "Department"
    INSTRUCTOR = "INSTRUCTOR", "Instructor"
    ROOM = "ROOM", "Room"
    STUDENT_GROUP = "STUDENT_GROUP", "Student group"


class CalendarException(models.Model):
    """A dated exception (holiday, exam, closure, absence, ...) to the time grid."""

    #: scope -> (target field, path from that target to its owning department)
    SCOPE_TARGET_FIELDS = {
        ExceptionScope.DEPARTMENT: ("department", "pk"),
        ExceptionScope.INSTRUCTOR: ("instructor", "primary_department"),
        ExceptionScope.ROOM: ("room", "owner_department"),
        ExceptionScope.STUDENT_GROUP: ("student_group", "stage__program__department"),
    }

    #: exception types that only make sense for one scope
    TYPE_SCOPE_RULES = {
        ExceptionType.INSTRUCTOR_ABSENCE: ExceptionScope.INSTRUCTOR,
        ExceptionType.ROOM_CLOSURE: ExceptionScope.ROOM,
    }

    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="calendar_exceptions",
    )
    date = models.DateField()
    exception_type = models.CharField(max_length=32, choices=ExceptionType.choices)
    scope_type = models.CharField(max_length=32, choices=ExceptionScope.choices)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="calendar_exceptions",
    )
    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="calendar_exceptions",
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="calendar_exceptions",
    )
    student_group = models.ForeignKey(
        StudentGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="calendar_exceptions",
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date", "semester")
        verbose_name = "calendar exception"
        verbose_name_plural = "calendar exceptions"
        indexes = [
            models.Index(
                fields=("semester", "date"),
                name="cal_exc_semester_date_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(start_time__isnull=True) & models.Q(end_time__isnull=True)
                )
                | (
                    models.Q(start_time__isnull=False)
                    & models.Q(end_time__isnull=False)
                ),
                name="calendar_exception_time_window_complete",
            ),
            models.CheckConstraint(
                condition=models.Q(start_time__isnull=True)
                | models.Q(end_time__isnull=True)
                | models.Q(start_time__lt=models.F("end_time")),
                name="calendar_exception_start_before_end",
            ),
        ]

    @property
    def is_full_day(self) -> bool:
        """True when the exception has no time window (all day)."""
        return self.start_time is None and self.end_time is None

    @property
    def scope_target_field(self) -> str | None:
        """Name of the target field for this scope, or None for college scope."""
        target = self.SCOPE_TARGET_FIELDS.get(self.scope_type)
        return target[0] if target is not None else None

    @property
    def owning_department_id(self) -> int | None:
        """Department that owns the targeted resource, or None for college scope."""
        target = self.SCOPE_TARGET_FIELDS.get(self.scope_type)
        if target is None:
            return None
        field_name, path = target
        value = getattr(self, field_name, None)
        if value is None:
            return None
        return resolve_department_id(value, path)

    def clean(self):
        """Validate the time shape, the scope target and the semester range.

        Exactly the target matching ``scope_type`` must be populated (a
        college-wide exception targets nothing in particular), types such as
        instructor absence and room closure are pinned to their scope, and the
        date must fall inside the semester's configured dates when they exist.
        """
        super().clean()
        errors = {}

        if (self.start_time is None) != (self.end_time is None):
            errors["start_time"] = (
                "Provide both start and end times for a partial-day exception, or "
                "neither for a full-day exception."
            )
        elif self.start_time is not None and self.start_time >= self.end_time:
            errors["end_time"] = "The exception must end after it starts."

        expected_field = self.scope_target_field
        populated = [
            name
            for name in ("department", "instructor", "room", "student_group")
            if getattr(self, f"{name}_id", None) is not None
        ]
        if expected_field is None:
            if populated:
                errors[populated[0]] = (
                    "A college-wide exception must not target a specific resource."
                )
        elif expected_field not in populated:
            errors[expected_field] = (
                f"A {self.get_scope_type_display()} exception requires this target."
            )
        else:
            extra = next((name for name in populated if name != expected_field), None)
            if extra is not None:
                errors[extra] = "Only the target matching the scope may be set."

        required_scope = self.TYPE_SCOPE_RULES.get(self.exception_type)
        if required_scope is not None and self.scope_type != required_scope:
            errors["scope_type"] = (
                f"{self.get_exception_type_display()} must be scoped to "
                f"{ExceptionScope(required_scope).label.lower()}."
            )

        if self.semester_id is not None and self.date is not None:
            semester = self.semester
            if semester.start_date and self.date < semester.start_date:
                errors["date"] = "The exception date is before the semester starts."
            elif semester.end_date and self.date > semester.end_date:
                errors["date"] = "The exception date is after the semester ends."

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return (
            f"{self.get_exception_type_display()} on {self.date} "
            f"({self.get_scope_type_display()})"
        )


# --- Phase 11: persisted schedules and versions -----------------------------


class ScheduleScope(models.TextChoices):
    """Which slice of the college one logical timetable covers.

    A model-level choice set rather than a serializer enum: the scope is stored on
    the row and constrained by the database, so a payload cannot invent a third
    scope.
    """

    DEPARTMENT = "DEPARTMENT", "Department"
    COLLEGE = "COLLEGE", "College"


class ScheduleStatus(models.TextChoices):
    """Version lifecycle states.

    Phase 11 only ever creates ``DRAFT``. The remaining values exist so the
    workflow phases can add transitions without a data migration, and the field is
    deliberately wider than today's needs.
    """

    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    REVIEWED = "REVIEWED", "Reviewed"
    APPROVED = "APPROVED", "Approved"
    PUBLISHED = "PUBLISHED", "Published"


class ScheduleVersionSource(models.TextChoices):
    """How a version was produced.

    The generation values describe server-side solving. ``MANUAL_EDIT`` describes a
    copy of an existing version whose placements a user moved by hand, which is why
    a manual version stores no solver metadata: claiming an engine produced it would
    be a lie.
    """

    DEPARTMENT_GENERATION = "DEPARTMENT_GENERATION", "Department generation"
    COLLEGE_GENERATION = "COLLEGE_GENERATION", "College generation"
    MANUAL_EDIT = "MANUAL_EDIT", "Manual edit"


class Schedule(models.Model):
    """The logical timetable of one semester and one scope.

    A department schedule belongs to exactly one department and a college schedule
    belongs to none; both rules are enforced by a database check constraint, so a
    half-scoped row cannot be stored. Exactly one logical schedule exists per
    (semester, department) and one per (semester) college-wide, which is what makes
    regenerating produce version 2 of the same schedule instead of a sibling.

    Nothing is hard-deleted through the API: a schedule is the root of a version
    history, so ``semester`` and ``department`` use ``PROTECT`` and no destroy
    endpoint exists in Phase 11.
    """

    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="schedules",
    )
    scope = models.CharField(max_length=32, choices=ScheduleScope.choices)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="schedules",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("semester", "scope", "department")
        verbose_name = "schedule"
        verbose_name_plural = "schedules"
        constraints = [
            # One department schedule per semester and department.
            models.UniqueConstraint(
                fields=("semester", "department"),
                condition=models.Q(scope=ScheduleScope.DEPARTMENT),
                name="sched_uniq_dept_scope",
            ),
            # One college schedule per semester.
            models.UniqueConstraint(
                fields=("semester",),
                condition=models.Q(scope=ScheduleScope.COLLEGE),
                name="sched_uniq_college_scope",
            ),
            # DEPARTMENT needs a department, COLLEGE forbids one.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scope=ScheduleScope.DEPARTMENT, department__isnull=False
                    )
                    | models.Q(
                        scope=ScheduleScope.COLLEGE, department__isnull=True
                    )
                ),
                name="sched_scope_dept_consistency",
            ),
        ]

    def clean(self):
        """Keep scope and department consistent before the database sees it."""
        errors = {}
        if self.scope == ScheduleScope.DEPARTMENT and self.department_id is None:
            errors["department"] = "A department schedule must name its department."
        if self.scope == ScheduleScope.COLLEGE and self.department_id is not None:
            errors["department"] = "A college schedule must not name a department."
        if errors:
            raise ValidationError(errors)

    @property
    def is_college_scope(self) -> bool:
        """True for the single college-wide schedule of the semester."""
        return self.scope == ScheduleScope.COLLEGE

    def __str__(self) -> str:
        target = self.department.code if self.department_id else "college"
        return f"{self.semester} - {self.get_scope_display()} ({target})"


class ScheduleVersion(models.Model):
    """One immutable snapshot of a schedule.

    Versions are created only by the persistence service, only as ``DRAFT``, and
    only with a number one above the previous latest. The row is never updated
    afterwards: a new generation writes a new version and points ``parent_version``
    at its predecessor, so history is append-only.

    Solver statistics and the validation/generation summaries are stored as plain
    JSON, never as OR-Tools or Django objects.
    """

    schedule = models.ForeignKey(
        Schedule,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="1 for the first persisted generation, then 2, 3, ...",
    )
    status = models.CharField(
        max_length=32,
        choices=ScheduleStatus.choices,
        default=ScheduleStatus.DRAFT,
    )
    source = models.CharField(
        max_length=40,
        choices=ScheduleVersionSource.choices,
    )
    parent_version = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="child_versions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_versions",
    )
    notes = models.TextField(blank=True, default="")

    # Solver provenance of the generation that produced this version. A manually
    # edited version stores null here instead of borrowing its parent's statistics.
    solver_status = models.CharField(max_length=32, null=True, blank=True, default=None)
    objective_value = models.IntegerField(null=True, blank=True)
    solver_wall_time_seconds = models.FloatField(null=True, blank=True)
    solver_num_conflicts = models.IntegerField(null=True, blank=True)
    solver_num_branches = models.IntegerField(null=True, blank=True)

    validation_summary = models.JSONField(default=dict, blank=True)
    generation_summary = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("schedule", "-version_number")
        verbose_name = "schedule version"
        verbose_name_plural = "schedule versions"
        constraints = [
            models.UniqueConstraint(
                fields=("schedule", "version_number"),
                name="schedver_uniq_number",
            ),
            models.CheckConstraint(
                condition=models.Q(version_number__gte=1),
                name="schedver_number_min_one",
            ),
        ]

    def clean(self):
        """Reject a parent that belongs to another schedule.

        The service always links to the same schedule's previous version; this check
        keeps the invariant true for admin edits and future callers too.
        """
        if (
            self.parent_version_id is not None
            and self.schedule_id is not None
            and self.parent_version.schedule_id != self.schedule_id
        ):
            raise ValidationError(
                {"parent_version": "The parent version belongs to another schedule."}
            )

    def __str__(self) -> str:
        return f"{self.schedule} - v{self.version_number} ({self.status})"


class ScheduleEntry(models.Model):
    """One persisted weekly session placement inside a version.

    Live foreign keys keep the academic structure reachable - the component it was
    generated for, the managing department, the room and (through the child tables)
    the periods, instructors and student groups - while the ``*_snapshot`` fields
    preserve what the timetable looked like when it was generated. Recipes, room
    names and department labels are editable, so rendering an old version must not
    depend on today's values.

    ``session_id`` and ``candidate_id`` are stored unchanged from the generation
    result, which is what makes a persisted row traceable back to a deterministic
    candidate.
    """

    schedule_version = models.ForeignKey(
        ScheduleVersion,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    session_id = models.CharField(max_length=200)
    candidate_id = models.CharField(max_length=300)

    teaching_component = models.ForeignKey(
        TeachingComponent,
        on_delete=models.PROTECT,
        related_name="schedule_entries",
    )
    managing_department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="schedule_entries",
    )
    session_ordinal = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="1-based index of this session inside its teaching component.",
    )

    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="schedule_entries",
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    penalty = models.IntegerField(default=0)

    course_id_snapshot = models.PositiveIntegerField()
    course_code_snapshot = models.CharField(max_length=32)
    course_name_snapshot = models.CharField(max_length=150)
    offering_id_snapshot = models.PositiveIntegerField()
    offering_code_snapshot = models.CharField(max_length=64, blank=True, default="")
    component_type_snapshot = models.CharField(max_length=32, blank=True, default="")
    component_label_snapshot = models.CharField(max_length=150, blank=True, default="")
    managing_department_code_snapshot = models.CharField(max_length=32)
    managing_department_name_snapshot = models.CharField(max_length=150)
    room_code_snapshot = models.CharField(max_length=32, blank=True, default="")
    room_name_snapshot = models.CharField(max_length=150, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("schedule_version", "day_of_week", "start_time", "session_id")
        verbose_name = "schedule entry"
        verbose_name_plural = "schedule entries"
        indexes = [
            models.Index(
                fields=("schedule_version", "day_of_week"),
                name="schedentry_version_day_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("schedule_version", "session_id"),
                name="schedentry_uniq_session",
            ),
            models.UniqueConstraint(
                fields=("schedule_version", "teaching_component", "session_ordinal"),
                name="schedentry_uniq_component",
            ),
            models.CheckConstraint(
                condition=models.Q(session_ordinal__gte=1),
                name="schedentry_ordinal_min_one",
            ),
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="schedentry_time_order",
            ),
            models.CheckConstraint(
                condition=models.Q(penalty__gte=0),
                name="schedentry_penalty_nonneg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.session_id} ({self.day_of_week}, {self.start_time})"


class ScheduleEntryTimeSlot(models.Model):
    """One exact period a persisted entry occupies, with its snapshot values.

    The occupied periods are stored as rows rather than ids in JSON so a historical
    version keeps both the identity and the original time labels, and the
    ``position`` column preserves the order the entry occupied them in.
    """

    schedule_entry = models.ForeignKey(
        ScheduleEntry,
        on_delete=models.CASCADE,
        related_name="time_slots",
    )
    time_slot = models.ForeignKey(
        TimeSlot,
        on_delete=models.PROTECT,
        related_name="schedule_entry_slots",
    )
    position = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="1-based position of this period inside the entry.",
    )
    sequence_snapshot = models.IntegerField()
    label_snapshot = models.CharField(max_length=100, blank=True, default="")
    start_time_snapshot = models.TimeField()
    end_time_snapshot = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("schedule_entry", "position")
        verbose_name = "schedule entry time slot"
        verbose_name_plural = "schedule entry time slots"
        constraints = [
            models.UniqueConstraint(
                fields=("schedule_entry", "time_slot"),
                name="schedslot_uniq_slot",
            ),
            models.UniqueConstraint(
                fields=("schedule_entry", "position"),
                name="schedslot_uniq_position",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="schedslot_position_min_one",
            ),
            models.CheckConstraint(
                condition=models.Q(start_time_snapshot__lt=models.F("end_time_snapshot")),
                name="schedslot_time_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.schedule_entry.session_id} #{self.position}"


class ScheduleEntryInstructor(models.Model):
    """One instructor included in a persisted entry, with its snapshot values.

    The rows are the placement's own instructor set, so a later change to the
    component's assignments cannot rewrite an old version.
    """

    schedule_entry = models.ForeignKey(
        ScheduleEntry,
        on_delete=models.CASCADE,
        related_name="instructors",
    )
    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.PROTECT,
        related_name="schedule_entry_instructors",
    )
    assignment_role_snapshot = models.CharField(max_length=32, blank=True, default="")
    full_name_snapshot = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("schedule_entry", "instructor")
        verbose_name = "schedule entry instructor"
        verbose_name_plural = "schedule entry instructors"
        constraints = [
            models.UniqueConstraint(
                fields=("schedule_entry", "instructor"),
                name="schedinst_uniq_instructor",
            ),
        ]

    def __str__(self) -> str:
        return self.full_name_snapshot


class ScheduleEntryStudentGroup(models.Model):
    """One student group included in a persisted entry, with its snapshot values.

    Joint courses keep the groups of every participating department, together with
    each group's own department snapshot, so an old version can still report who
    attended without consulting today's component links.
    """

    schedule_entry = models.ForeignKey(
        ScheduleEntry,
        on_delete=models.CASCADE,
        related_name="student_groups",
    )
    student_group = models.ForeignKey(
        StudentGroup,
        on_delete=models.PROTECT,
        related_name="schedule_entry_groups",
    )
    code_snapshot = models.CharField(max_length=32)
    name_snapshot = models.CharField(max_length=100)
    department_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    department_code_snapshot = models.CharField(max_length=32, blank=True, default="")
    department_name_snapshot = models.CharField(
        max_length=150, blank=True, default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("schedule_entry", "student_group")
        verbose_name = "schedule entry student group"
        verbose_name_plural = "schedule entry student groups"
        constraints = [
            models.UniqueConstraint(
                fields=("schedule_entry", "student_group"),
                name="schedgroup_uniq_group",
            ),
        ]

    def __str__(self) -> str:
        return self.code_snapshot
