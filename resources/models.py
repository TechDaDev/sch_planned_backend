"""
Instructor resource models.

Phase 4 introduces instructors as first-class academic resources: an
``InstructorProfile`` is the teaching resource that gets scheduled, while
``accounts.User`` remains the authentication identity. A profile is valid
without a login account, so administrative data entry (and the future Flutter
instructor app) is never blocked on account creation.

This module also holds instructor sharing (``InstructorDepartmentAccess``), hard
weekly availability (``InstructorAvailability``), soft scheduling preferences
(``InstructorPreference``) and the assignment of instructors to teaching
components (``TeachingAssignment``).

Rooms, laboratories, time slots and timetable generation belong to later phases.

Delete behaviour: instructor-owned configuration rows cascade with the
instructor, while references into the academic structure (``primary_department``,
``semester``, ``teaching_component``) use ``PROTECT`` so structural data cannot
be removed silently.

Timestamps are timezone-aware: ``USE_TZ = True`` with ``Asia/Baghdad`` as the
application timezone (see ``config/settings.py``); no manual UTC offsets.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from academics.models import Department, Semester, TeachingComponent, Weekday
from accounts.models import UserRole


class SharingScope(models.TextChoices):
    """How widely an instructor may be used outside the primary department."""

    PRIVATE = "PRIVATE", "Private (primary department only)"
    SELECTED_DEPARTMENTS = "SELECTED_DEPARTMENTS", "Selected departments"
    COLLEGE_WIDE = "COLLEGE_WIDE", "College-wide"


class AssignmentRole(models.TextChoices):
    """Role of an instructor inside one teaching component."""

    PRIMARY = "PRIMARY", "Primary"
    ASSISTANT = "ASSISTANT", "Assistant"


class PreferenceType(models.TextChoices):
    """Soft scheduling preference; ``AVOID`` is not hard unavailability."""

    PREFERRED = "PREFERRED", "Preferred"
    AVOID = "AVOID", "Avoid"


def _resolve_department(department):
    """Accept a ``Department`` instance or a primary key.

    Shared by instructor and room sharing rules so the "owner or foreign
    department" handling exists once. Returns ``None`` when it cannot resolve.
    """
    if department is None:
        return None
    if isinstance(department, Department):
        return department
    return Department.objects.filter(pk=department).first()


class InstructorProfile(models.Model):
    """An instructor as a schedulable teaching resource."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="instructor_profile",
        help_text=(
            "Optional login account; a profile may exist before an account is created."
        ),
    )
    primary_department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="instructors",
        help_text="Department that owns this instructor resource.",
    )
    staff_code = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        help_text="Optional institutional identifier; blank values are stored as NULL.",
    )
    full_name = models.CharField(max_length=150)
    academic_title = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Free text, for example Professor or Assistant Lecturer.",
    )
    max_weekly_hours = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    max_daily_hours = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    sharing_scope = models.CharField(
        max_length=32,
        choices=SharingScope.choices,
        default=SharingScope.PRIVATE,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("full_name",)
        verbose_name = "instructor profile"
        verbose_name_plural = "instructor profiles"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_weekly_hours__isnull=True)
                | models.Q(max_weekly_hours__gt=0),
                name="instructor_max_weekly_hours_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(max_daily_hours__isnull=True)
                | models.Q(max_daily_hours__gt=0),
                name="instructor_max_daily_hours_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_weekly_hours__isnull=True)
                    | models.Q(max_daily_hours__isnull=True)
                    | models.Q(max_daily_hours__lte=models.F("max_weekly_hours"))
                ),
                name="instructor_daily_hours_not_above_weekly",
            ),
        ]

    def can_teach_in_department(self, department) -> bool:
        """Return True when this instructor may teach for ``department``.

        This is the single source of truth for instructor eligibility and is
        reused by assignment validation: an inactive instructor can never teach,
        the primary department always can, ``PRIVATE`` allows nothing else,
        ``SELECTED_DEPARTMENTS`` requires an active access grant, and
        ``COLLEGE_WIDE`` allows any active department.
        """
        if not self.is_active:
            return False
        resolved = _resolve_department(department)
        if resolved is None:
            return False
        if resolved.pk == self.primary_department_id:
            return True
        if self.sharing_scope == SharingScope.COLLEGE_WIDE:
            return bool(resolved.is_active)
        if self.sharing_scope == SharingScope.SELECTED_DEPARTMENTS:
            return self.department_access.filter(
                department_id=resolved.pk, is_active=True
            ).exists()
        return False

    def clean(self):
        """Validate workload limits and the optional linked account."""
        super().clean()
        errors = {}

        if self.staff_code is not None and not str(self.staff_code).strip():
            # Canonicalise blank identifiers so uniqueness validation and the
            # unique index both treat "no staff code" as NULL.
            self.staff_code = None

        for field_name in ("max_weekly_hours", "max_daily_hours"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                errors[field_name] = "Workload limits must be greater than zero."

        if (
            self.max_weekly_hours is not None
            and self.max_daily_hours is not None
            and self.max_daily_hours > self.max_weekly_hours
        ):
            errors["max_daily_hours"] = (
                "The daily hour limit cannot exceed the weekly hour limit."
            )

        if self.user_id is not None:
            linked_user = self.user
            if linked_user.role != UserRole.INSTRUCTOR:
                errors["user"] = "The linked account must have the INSTRUCTOR role."
            elif (
                self.primary_department_id is not None
                and linked_user.department_id != self.primary_department_id
            ):
                errors["user"] = (
                    "The linked account must belong to the instructor's primary "
                    "department."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.staff_code is not None and not str(self.staff_code).strip():
            self.staff_code = None
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.full_name


class InstructorDepartmentAccess(models.Model):
    """Explicit grant letting a shared instructor teach for another department.

    Only meaningful while ``instructor.sharing_scope`` is
    ``SELECTED_DEPARTMENTS``; rows are kept when the scope changes rather than
    being silently deleted.
    """

    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.CASCADE,
        related_name="department_access",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="instructor_access_grants",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("instructor", "department")
        verbose_name = "instructor department access"
        verbose_name_plural = "instructor department access grants"
        constraints = [
            models.UniqueConstraint(
                fields=("instructor", "department"),
                name="unique_instructor_department_access",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.instructor_id is not None
            and self.department_id is not None
            and self.department_id == self.instructor.primary_department_id
        ):
            raise ValidationError(
                {
                    "department": (
                        "The primary department already has inherent access; an explicit "
                        "grant is only needed for other departments."
                    )
                }
            )

    def __str__(self) -> str:
        return f"{self.instructor} → {self.department}"


def _validate_window(
    instance,
    *,
    parent_field: str,
    related_manager_name: str,
    errors: dict,
    label: str,
) -> None:
    """Validate a recurring weekday window shared by windows of one parent.

    Enforces ``start_time < end_time`` and rejects active windows that overlap
    another active window of the same parent (instructor or room), semester and
    weekday. Inactive rows neither conflict nor block.
    """
    if (
        instance.start_time
        and instance.end_time
        and instance.start_time >= instance.end_time
    ):
        errors["end_time"] = f"{label} must end after it starts."
        return

    if (
        not instance.is_active
        or getattr(instance, f"{parent_field}_id", None) is None
        or instance.semester_id is None
        or instance.day_of_week is None
    ):
        return

    sibling_windows = (
        getattr(getattr(instance, parent_field), related_manager_name)
        .filter(
            is_active=True,
            semester_id=instance.semester_id,
            day_of_week=instance.day_of_week,
        )
        .exclude(pk=instance.pk)
    )
    overlapping = sibling_windows.filter(
        start_time__lt=instance.end_time,
        end_time__gt=instance.start_time,
    )
    if overlapping.exists():
        errors["start_time"] = (
            f"This window overlaps another active {label.lower()} for that weekday."
        )


class InstructorAvailability(models.Model):
    """A recurring hard weekly availability window.

    Absence of rows means "availability not configured", never "unrestricted";
    the pre-scheduling validation phase decides how to treat that.
    """

    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.CASCADE,
        related_name="availability_slots",
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="instructor_availability",
    )
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("instructor", "day_of_week", "start_time")
        verbose_name = "instructor availability"
        verbose_name_plural = "instructor availability windows"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="instructor_availability_start_before_end",
            ),
            models.UniqueConstraint(
                fields=(
                    "instructor",
                    "semester",
                    "day_of_week",
                    "start_time",
                    "end_time",
                ),
                condition=models.Q(is_active=True),
                name="unique_active_instructor_availability_window",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        _validate_window(
            self,
            parent_field="instructor",
            related_manager_name="availability_slots",
            errors=errors,
            label="Availability end time",
        )
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return (
            f"{self.instructor} — {self.get_day_of_week_display()} "
            f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"
        )


class InstructorPreference(models.Model):
    """A soft scheduling preference window (never hard unavailability)."""

    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="instructor_preferences",
    )
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    preference_type = models.CharField(max_length=20, choices=PreferenceType.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("instructor", "day_of_week", "start_time")
        verbose_name = "instructor preference"
        verbose_name_plural = "instructor preferences"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="instructor_preference_start_before_end",
            ),
            models.UniqueConstraint(
                fields=(
                    "instructor",
                    "semester",
                    "day_of_week",
                    "start_time",
                    "end_time",
                ),
                condition=models.Q(is_active=True),
                name="unique_active_instructor_preference_window",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        _validate_window(
            self,
            parent_field="instructor",
            related_manager_name="preferences",
            errors=errors,
            label="Preference end time",
        )
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return (
            f"{self.instructor} — {self.get_day_of_week_display()} "
            f"{self.get_preference_type_display()}"
        )


class TeachingAssignment(models.Model):
    """Assigns an instructor to a teaching component.

    Instructors are attached here rather than on ``Course`` or
    ``TeachingComponent``, so instructor data stays out of the academic models.
    """

    teaching_component = models.ForeignKey(
        TeachingComponent,
        on_delete=models.PROTECT,
        related_name="instructor_assignments",
    )
    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.CASCADE,
        related_name="teaching_assignments",
    )
    assignment_role = models.CharField(max_length=20, choices=AssignmentRole.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("teaching_component", "assignment_role", "instructor")
        verbose_name = "teaching assignment"
        verbose_name_plural = "teaching assignments"
        constraints = [
            models.UniqueConstraint(
                fields=("teaching_component", "instructor"),
                name="unique_instructor_per_teaching_component",
            ),
            models.UniqueConstraint(
                fields=("teaching_component",),
                condition=models.Q(
                    is_active=True, assignment_role=AssignmentRole.PRIMARY
                ),
                name="single_active_primary_instructor_per_component",
            ),
        ]

    def clean(self):
        """Validate active assignments against instructor eligibility.

        The eligibility rule applies to every writer, including college
        administrators: sharing must be changed on the instructor first.
        """
        super().clean()
        if not self.is_active or self.teaching_component_id is None:
            return

        errors = {}
        component = self.teaching_component
        offering = component.offering

        if self.instructor_id is not None and not self.instructor.is_active:
            errors["instructor"] = "Inactive instructors cannot hold active assignments."
        if not component.is_active:
            errors["teaching_component"] = "This teaching component is inactive."
        elif not offering.is_active:
            errors["teaching_component"] = "The offering of this component is inactive."
        elif not offering.course.is_active:
            errors["teaching_component"] = "The course of this offering is inactive."
        elif not self.instructor.can_teach_in_department(offering.managing_department):
            errors["instructor"] = (
                "This instructor is not allowed to teach in the managing department "
                "of the offering."
            )

        if self.assignment_role == AssignmentRole.PRIMARY:
            existing_primary = (
                component.instructor_assignments.filter(
                    is_active=True, assignment_role=AssignmentRole.PRIMARY
                ).exclude(pk=self.pk)
            )
            if existing_primary.exists():
                errors["assignment_role"] = (
                    "This teaching component already has an active primary instructor."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.instructor} — {self.teaching_component} ({self.assignment_role})"


# --- Phase 5: rooms, laboratories, capabilities and requirements -------------


class RoomType(models.Model):
    """College-wide category of teaching space.

    Rows are administrative data (lecture hall, computer laboratory, ...); no
    room types are hard-coded in migrations.
    """

    name = models.CharField(max_length=100)
    code = models.CharField(
        max_length=32,
        unique=True,
        help_text="Short code, for example LECTURE_HALL or COMPUTER_LAB.",
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "room type"
        verbose_name_plural = "room types"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class RoomCapability(models.Model):
    """College-wide capability/equipment vocabulary for rooms."""

    name = models.CharField(max_length=100)
    code = models.CharField(
        max_length=32,
        unique=True,
        help_text="Short code, for example COMPUTERS or PROJECTOR.",
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "room capability"
        verbose_name_plural = "room capabilities"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Room(models.Model):
    """A physical teaching space owned by a department.

    Sharing grants *use* of the room; ownership always stays with
    ``owner_department``, so a foreign department can never manage a shared
    room's identity, capacity, type, capabilities or availability.
    """

    owner_department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="rooms",
        help_text="Department that owns this room.",
    )
    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=32,
        unique=True,
        help_text="Globally unique physical room code, for example AI-LAB-1.",
    )
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.PROTECT,
        related_name="rooms",
    )
    capacity = models.PositiveIntegerField(
        help_text="Number of students the room can host.",
    )
    sharing_scope = models.CharField(
        max_length=32,
        choices=SharingScope.choices,
        default=SharingScope.PRIVATE,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "room"
        verbose_name_plural = "rooms"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1),
                name="room_capacity_at_least_one",
            ),
        ]

    def can_be_used_by_department(self, department) -> bool:
        """Return True when ``department`` may use this room.

        Canonical sharing rule, reused by the suitability helper: an inactive
        room or an inactive room type is never usable; the owner department
        always may use it; ``SELECTED_DEPARTMENTS`` additionally requires an
        active access row; ``COLLEGE_WIDE`` allows any active department;
        ``PRIVATE`` grants nothing beyond the owner.
        """
        if not self.is_active:
            return False
        if not self.room_type.is_active:
            return False
        resolved = _resolve_department(department)
        if resolved is None:
            return False
        if resolved.pk == self.owner_department_id:
            return True
        if self.sharing_scope == SharingScope.COLLEGE_WIDE:
            return bool(resolved.is_active)
        if self.sharing_scope == SharingScope.SELECTED_DEPARTMENTS:
            return self.department_access.filter(
                department_id=resolved.pk, is_active=True
            ).exists()
        return False

    def evaluate_suitability(self, requirement) -> list[str]:
        """Return the reasons why this room does not satisfy ``requirement``.

        Evaluates room and room-type activity, access for the requirement's
        managing department, the required room type, the effective minimum
        capacity and every required capability. An empty list means suitable.

        Time slots are deliberately excluded: no proposed timetable slot exists
        yet, so availability is left to the scheduling layer.
        """
        reasons: list[str] = []

        if not self.is_active:
            reasons.append("The room is inactive.")
        if not self.room_type.is_active:
            reasons.append("The room type is inactive.")

        component = requirement.teaching_component
        if not self.can_be_used_by_department(component.offering.managing_department):
            reasons.append(
                "The room is not shared with the offering's managing department."
            )

        required_type_id = requirement.required_room_type_id
        if required_type_id is not None and required_type_id != self.room_type_id:
            reasons.append("The room type does not match the requirement.")

        if self.capacity < requirement.effective_minimum_capacity:
            reasons.append("The room capacity is below the effective minimum capacity.")

        available_capability_ids = {
            assignment.capability_id
            for assignment in self.capability_assignments.select_related("capability")
            if assignment.capability.is_active
        }
        missing: list[str] = []
        inactive: list[str] = []
        for link in requirement.capability_requirements.select_related("capability"):
            capability = link.capability
            if not capability.is_active:
                inactive.append(capability.name)
            elif capability.pk not in available_capability_ids:
                missing.append(capability.name)

        if missing:
            reasons.append(
                "The room is missing required capabilities: " + ", ".join(sorted(missing)) + "."
            )
        if inactive:
            reasons.append(
                "Required capabilities are inactive: " + ", ".join(sorted(inactive)) + "."
            )

        return reasons

    def meets_requirement(self, requirement) -> bool:
        """True when the room satisfies every part of ``requirement``."""
        return not self.evaluate_suitability(requirement)

    def is_suitable_for_teaching_component(self, component) -> bool:
        """Conservative suitability check for a teaching component.

        Returns False when the component has no active room-requirement record,
        because nothing then states what the component needs — the helper never
        claims a room is suitable without a requirement. Call
        ``evaluate_suitability`` with the requirement for the explicit reasons.
        """
        requirement = getattr(component, "room_requirement", None)
        if requirement is None or not requirement.is_active:
            return False
        return self.meets_requirement(requirement)

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class RoomDepartmentAccess(models.Model):
    """Explicit grant letting a department use a shared room.

    Only meaningful while ``room.sharing_scope`` is
    ``SELECTED_DEPARTMENTS``; rows are kept when the scope changes rather than
    being silently deleted.
    """

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="department_access",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="room_access_grants",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("room", "department")
        verbose_name = "room department access"
        verbose_name_plural = "room department access grants"
        constraints = [
            models.UniqueConstraint(
                fields=("room", "department"),
                name="unique_room_department_access",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.room_id is not None
            and self.department_id is not None
            and self.department_id == self.room.owner_department_id
        ):
            raise ValidationError(
                {
                    "department": (
                        "The owner department already has inherent access; an explicit "
                        "grant is only needed for other departments."
                    )
                }
            )

    def __str__(self) -> str:
        return f"{self.room} → {self.department}"


class RoomCapabilityAssignment(models.Model):
    """A capability physically available in a room."""

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="capability_assignments",
    )
    capability = models.ForeignKey(
        RoomCapability,
        on_delete=models.CASCADE,
        related_name="room_assignments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("room", "capability")
        verbose_name = "room capability assignment"
        verbose_name_plural = "room capability assignments"
        constraints = [
            models.UniqueConstraint(
                fields=("room", "capability"),
                name="unique_capability_per_room",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.room} — {self.capability}"


class RoomAvailability(models.Model):
    """A recurring weekly window in which a room is available.

    Absence of rows means "availability not configured", never "available all
    day"; the scheduling validator decides how to treat that.
    """

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="availability_slots",
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="room_availability",
    )
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("room", "day_of_week", "start_time")
        verbose_name = "room availability"
        verbose_name_plural = "room availability windows"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="room_availability_start_before_end",
            ),
            models.UniqueConstraint(
                fields=("room", "semester", "day_of_week", "start_time", "end_time"),
                condition=models.Q(is_active=True),
                name="unique_active_room_availability_window",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        _validate_window(
            self,
            parent_field="room",
            related_manager_name="availability_slots",
            errors=errors,
            label="Availability end time",
        )
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return (
            f"{self.room} — {self.get_day_of_week_display()} "
            f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"
        )


class TeachingComponentRoomRequirement(models.Model):
    """General room requirement of a teaching component.

    A component defines *requirements* only; the actual room is chosen later by
    the scheduling layer, so no room reference is stored here.
    """

    teaching_component = models.OneToOneField(
        TeachingComponent,
        on_delete=models.PROTECT,
        related_name="room_requirement",
    )
    required_room_type = models.ForeignKey(
        RoomType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="room_requirements",
        help_text="Null means no specific room-type restriction.",
    )
    minimum_capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Explicit minimum capacity override; null means the expected student "
            "count decides."
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("teaching_component",)
        verbose_name = "teaching component room requirement"
        verbose_name_plural = "teaching component room requirements"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minimum_capacity__isnull=True)
                | models.Q(minimum_capacity__gte=1),
                name="room_requirement_minimum_capacity_positive",
            ),
        ]

    @property
    def expected_student_count(self) -> int:
        """Students expected in the component (sum of attached group counts)."""
        return self.teaching_component.expected_student_count

    @property
    def effective_minimum_capacity(self) -> int:
        """Capacity a room must offer: expected students or the explicit override."""
        return max(self.expected_student_count, self.minimum_capacity or 0)

    def clean(self):
        """Validate the capacity override and the one-requirement-per-component rule.

        The OneToOne column already prevents duplicates at the database level;
        this check turns the same rule into a clean HTTP 400 for API writes.
        """
        super().clean()
        errors = {}

        if self.minimum_capacity is not None and self.minimum_capacity < 1:
            errors["minimum_capacity"] = "Minimum capacity must be greater than zero."

        if self.teaching_component_id is not None:
            duplicates = TeachingComponentRoomRequirement.objects.filter(
                teaching_component_id=self.teaching_component_id
            ).exclude(pk=self.pk)
            if duplicates.exists():
                errors["teaching_component"] = (
                    "This teaching component already has a room requirement."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"Room requirement for {self.teaching_component}"


class TeachingComponentCapabilityRequirement(models.Model):
    """A capability a room must provide for a teaching component's requirement."""

    room_requirement = models.ForeignKey(
        TeachingComponentRoomRequirement,
        on_delete=models.CASCADE,
        related_name="capability_requirements",
    )
    capability = models.ForeignKey(
        RoomCapability,
        on_delete=models.PROTECT,
        related_name="room_requirements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("room_requirement", "capability")
        verbose_name = "teaching component capability requirement"
        verbose_name_plural = "teaching component capability requirements"
        constraints = [
            models.UniqueConstraint(
                fields=("room_requirement", "capability"),
                name="unique_capability_per_room_requirement",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.room_requirement} — {self.capability}"
