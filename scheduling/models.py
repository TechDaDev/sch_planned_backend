"""
Scheduling configuration models: the college time grid and calendar exceptions.

Phase 6 defines the *available* scheduling positions (working days, teaching
periods, breaks) and the dates that are not schedulable. Nothing here assigns a
teaching component, instructor, room or student group to a slot — that belongs to
future schedule entries — so those resources appear only as calendar-exception
targets.

``academics.Weekday`` (Sunday → Thursday) is reused; Friday and Saturday are not
ordinary working days in this version.

Delete behaviour: the time grid cascades from its working day, while references
into academic and resource structure (``semester`` and the exception targets) use
``PROTECT`` so structural data cannot be removed silently.

Timestamps are timezone-aware: ``USE_TZ = True`` with ``Asia/Baghdad`` as the
application timezone (see ``config/settings.py``); no manual UTC offsets.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from academics.models import Department, Semester, StudentGroup, Weekday
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
