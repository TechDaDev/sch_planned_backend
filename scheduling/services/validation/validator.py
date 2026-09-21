"""The pre-scheduling validator.

Timetable generation is expensive and opaque when its inputs are wrong, so this
service inspects the data already stored in the backend and reports what would
make generation fail, before any solver runs. It is a set of *necessary*
feasibility checks, not a solver: it never places a session, never assigns a room
and never writes anything.

Scope of the checks:

* the time grid (working days, their active periods, contiguous blocks);
* the demand (active components of a semester, their groups and student counts);
* instructor presence, eligibility, availability and necessary workload ceilings;
* room requirements, currently suitable rooms and their available blocks.

Deliberately out of scope, because they cannot be decided without solving:
placement, collision avoidance, preference optimisation, daily distribution,
and calendar-exception subtraction from recurring weekly capacity.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import models
from django.db.models import Prefetch

from academics.models import (
    Department,
    Semester,
    TeachingComponent,
    TeachingComponentGroup,
    Weekday,
)
from resources.models import AssignmentRole, TeachingAssignment
from scheduling.services.validation.issues import (
    EntityType,
    IssueCode,
    IssueCollector,
    Severity,
    ValidationIssue,
)
from scheduling.services.validation.resources import ResourceFacts
from scheduling.services.validation.time_grid import TimeGrid, hours_to_minutes


class ValidationScope(models.TextChoices):
    """How much of the college one validation run covers."""

    COLLEGE = "COLLEGE", "College"
    DEPARTMENT = "DEPARTMENT", "Department"


@dataclass(frozen=True)
class ValidationSummary:
    """Counts shown alongside the issues."""

    components_checked: int
    errors: int
    warnings: int


@dataclass(frozen=True)
class ValidationResult:
    """The complete outcome of one validation run."""

    ready: bool
    scope: str
    semester: Semester
    department: Department | None
    summary: ValidationSummary
    issues: tuple[ValidationIssue, ...]


class PreSchedulingValidator:
    """Deterministic readiness checks for one semester and one scope.

    ``ready`` is true only when no ``ERROR`` was reported; warnings are
    informational and never block generation.
    """

    def __init__(
        self,
        *,
        semester: Semester,
        scope: str,
        department: Department | None = None,
    ) -> None:
        self.semester = semester
        self.scope = scope
        self.department = department if scope == ValidationScope.DEPARTMENT else None
        self.collector = IssueCollector()
        self.grid = TimeGrid.load(semester)
        self.resources = ResourceFacts(semester=semester, grid=self.grid)
        self._demand: list[TeachingComponent] = []
        self._instructors: dict[int, object] = {}
        self._assignments: dict[int, dict[int, TeachingComponent]] = {}

    # --- entry point -------------------------------------------------------

    def run(self) -> ValidationResult:
        """Validate the requested scope and return the report."""
        self._check_time_grid()
        self._check_components(self._load_components())
        self._check_instructor_totals()

        issues = tuple(self.collector.issues())
        summary = ValidationSummary(
            components_checked=len(self._demand),
            errors=self.collector.error_count,
            warnings=self.collector.warning_count,
        )
        return ValidationResult(
            ready=summary.errors == 0,
            scope=self.scope,
            semester=self.semester,
            department=self.department,
            summary=summary,
            issues=issues,
        )

    # --- loading -----------------------------------------------------------

    def _load_components(self) -> list[TeachingComponent]:
        """Active components of the semester inside the requested scope.

        Only *active* components are demand: an inactive component describes
        nothing that has to be scheduled. Inactive offerings, courses and
        managing departments are loaded too, so an inconsistent active/inactive
        combination is reported instead of silently skipped, and stale rows never
        crash the run.
        """
        queryset = (
            TeachingComponent.objects.filter(
                is_active=True,
                offering__semester=self.semester,
            )
            .select_related(
                "offering",
                "offering__course",
                "offering__managing_department",
                "room_requirement",
                "room_requirement__required_room_type",
            )
            .prefetch_related(
                Prefetch(
                    "group_links",
                    queryset=TeachingComponentGroup.objects.select_related(
                        "student_group",
                        "student_group__stage",
                        "student_group__stage__program",
                        "student_group__stage__program__department",
                    ).order_by("student_group_id"),
                    to_attr="attached_group_links",
                ),
                Prefetch(
                    "instructor_assignments",
                    queryset=TeachingAssignment.objects.filter(is_active=True)
                    .select_related("instructor", "instructor__primary_department")
                    .order_by("assignment_role", "instructor_id"),
                ),
                "room_requirement__capability_requirements",
            )
            .order_by("pk")
        )
        if self.scope == ValidationScope.DEPARTMENT:
            queryset = queryset.filter(offering__managing_department=self.department)
        return list(queryset)

    # --- time grid ---------------------------------------------------------

    def _check_time_grid(self) -> None:
        """The recurring weekly grid a schedule has to fit into."""
        if not self.grid.has_working_days:
            self.collector.add(
                IssueCode.NO_ACTIVE_WORKING_DAYS,
                Severity.ERROR,
                "The semester has no active working day, so nothing can be scheduled.",
                EntityType.SEMESTER,
                self.semester.pk,
                semester_number=int(self.semester.number),
            )
        for working_day in self.grid.days_without_slots:
            self.collector.add(
                IssueCode.WORKING_DAY_NO_ACTIVE_SLOTS,
                Severity.ERROR,
                "This active working day has no active time slot.",
                EntityType.WORKING_DAY,
                working_day.pk,
                day_of_week=int(working_day.day_of_week),
                day_of_week_code=Weekday(working_day.day_of_week).name,
            )

    # --- components --------------------------------------------------------

    def _check_components(self, components: list[TeachingComponent]) -> None:
        grid_has_slots = self.grid.has_slots
        grid_total_minutes = self.grid.total_slot_minutes
        grid_max_block = self.grid.max_contiguous_minutes

        for component in components:
            if not self._check_academic_dependencies(component):
                continue
            self._demand.append(component)
            self._check_component_demand(
                component,
                grid_has_slots=grid_has_slots,
                grid_total_minutes=grid_total_minutes,
                grid_max_block=grid_max_block,
            )
            self._check_component_instructors(component)
            self._check_component_room(component)

    def _check_academic_dependencies(self, component: TeachingComponent) -> bool:
        """Report a broken dependency chain; True when the component counts as demand.

        An offering, course or managing department that is switched off means the
        component cannot be scheduled at all, so it is reported once and left out
        of the deeper per-component checks (reporting room or instructor problems
        for demand that does not exist would only add noise). The deeper checks
        still run for components whose *participating groups* sit in inactive
        structure, because the component itself remains real demand.
        """
        offering = component.offering
        broken: tuple[str, int, str, str] | None = None
        if not offering.is_active:
            broken = (
                EntityType.COURSE_OFFERING,
                offering.pk,
                "The course offering of this teaching component is inactive.",
                "offering",
            )
        elif not offering.course.is_active:
            broken = (
                EntityType.COURSE,
                offering.course.pk,
                "The course of this teaching component is inactive.",
                "course",
            )
        elif not offering.managing_department.is_active:
            broken = (
                EntityType.DEPARTMENT,
                offering.managing_department.pk,
                "The managing department of this teaching component is inactive.",
                "managing_department",
            )
        if broken is None:
            return True

        dependency_type, dependency_id, message, role = broken
        self.collector.add(
            IssueCode.INACTIVE_ACADEMIC_DEPENDENCY,
            Severity.ERROR,
            message,
            EntityType.TEACHING_COMPONENT,
            component.pk,
            dependency_type=dependency_type,
            dependency_id=dependency_id,
            dependency_role=role,
            component_type=component.component_type,
            course_code=offering.course.code,
        )
        return False

    def _check_component_demand(
        self,
        component: TeachingComponent,
        *,
        grid_has_slots: bool,
        grid_total_minutes: int,
        grid_max_block: int,
    ) -> None:
        """Groups, student counts and the component's own fit against the grid."""
        links = list(getattr(component, "attached_group_links", []) or [])
        if not links:
            self.collector.add(
                IssueCode.COMPONENT_NO_STUDENT_GROUPS,
                Severity.ERROR,
                "This teaching component has no student group attached.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                course_code=component.offering.course.code,
                component_type=component.component_type,
            )
        for link in links:
            self._check_component_group(link.student_group)

        session_minutes = hours_to_minutes(component.session_duration_hours)
        weekly_minutes = hours_to_minutes(component.weekly_hours)
        context = {
            "course_code": component.offering.course.code,
            "component_type": component.component_type,
            "session_duration_minutes": session_minutes,
            "weekly_minutes": weekly_minutes,
        }

        # When the grid holds no slot at all, the grid-level errors already say
        # why nothing fits; repeating it per component would only add noise.
        if not grid_has_slots:
            return
        if session_minutes > grid_max_block:
            self.collector.add(
                IssueCode.SESSION_DURATION_NOT_SUPPORTED_BY_GRID,
                Severity.ERROR,
                "The session duration of this component does not fit any "
                "contiguous block of active time slots.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                longest_grid_block_minutes=grid_max_block,
                **context,
            )
        if weekly_minutes > grid_total_minutes:
            self.collector.add(
                IssueCode.COMPONENT_WEEKLY_HOURS_EXCEED_GRID,
                Severity.ERROR,
                "The weekly hours of this component exceed the entire weekly "
                "time grid.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                grid_weekly_minutes=grid_total_minutes,
                **context,
            )

    def _check_component_group(self, group) -> None:
        """One attached group: activity, academic hierarchy and student count.

        Reported against the group itself, so a group shared by several
        components produces one issue rather than one per component. An inactive
        group is reported once and its other properties are not re-litigated.
        """
        if not group.is_active:
            self.collector.add(
                IssueCode.STUDENT_GROUP_INACTIVE,
                Severity.ERROR,
                "This student group is inactive but is still attached to a "
                "teaching component.",
                EntityType.STUDENT_GROUP,
                group.pk,
                group_code=group.code,
            )
            return

        stage = group.stage
        program = stage.program
        broken: tuple[str, int] | None = None
        if not stage.is_active:
            broken = (EntityType.STUDY_STAGE, stage.pk)
        elif not program.is_active:
            broken = (EntityType.STUDY_PROGRAM, program.pk)
        elif not program.department.is_active:
            broken = (EntityType.DEPARTMENT, program.department.pk)
        if broken is not None:
            dependency_type, dependency_id = broken
            self.collector.add(
                IssueCode.INACTIVE_ACADEMIC_DEPENDENCY,
                Severity.ERROR,
                "The academic structure this student group belongs to is inactive.",
                EntityType.STUDENT_GROUP,
                group.pk,
                dependency_type=dependency_type,
                dependency_id=dependency_id,
                group_code=group.code,
            )

        if group.student_count <= 0:
            self.collector.add(
                IssueCode.STUDENT_COUNT_ZERO,
                Severity.ERROR,
                "This student group has no students registered, so room capacity "
                "cannot be planned.",
                EntityType.STUDENT_GROUP,
                group.pk,
                group_code=group.code,
                student_count=group.student_count,
            )

    # --- instructors -------------------------------------------------------

    def _check_component_instructors(self, component: TeachingComponent) -> None:
        """Primary instructor presence, eligibility and per-component fit."""
        assignments = list(component.instructor_assignments.all())
        primaries = [
            assignment
            for assignment in assignments
            if assignment.assignment_role == AssignmentRole.PRIMARY
        ]
        if not primaries:
            self.collector.add(
                IssueCode.PRIMARY_INSTRUCTOR_MISSING,
                Severity.ERROR,
                "This teaching component has no active primary instructor.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                course_code=component.offering.course.code,
                component_type=component.component_type,
            )
        elif len(primaries) > 1:
            self.collector.add(
                IssueCode.MULTIPLE_PRIMARY_INSTRUCTORS,
                Severity.ERROR,
                "This teaching component has more than one active primary "
                "instructor.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                primary_instructor_count=len(primaries),
            )

        session_minutes = hours_to_minutes(component.session_duration_hours)
        for assignment in assignments:
            self._check_assignment(
                assignment, component, session_minutes=session_minutes
            )

    def _check_assignment(
        self,
        assignment: TeachingAssignment,
        component: TeachingComponent,
        *,
        session_minutes: int,
    ) -> None:
        """Current state of one active assignment.

        Eligibility is re-derived instead of trusted: sharing scope and access
        grants may have changed since the assignment was created. Instructor-level
        problems are reported per instructor (never per component), while the
        component-specific duration problem stays per component.
        """
        instructor = assignment.instructor
        self._instructors[instructor.pk] = instructor
        self._assignments.setdefault(instructor.pk, {})[component.pk] = component

        if not instructor.is_active:
            self._add_instructor_issue(
                IssueCode.INSTRUCTOR_INACTIVE,
                "This instructor is inactive but still holds an active assignment.",
                instructor,
            )
            return

        offering = component.offering
        if not self.resources.is_eligible(instructor, offering.managing_department):
            self._add_instructor_issue(
                IssueCode.INSTRUCTOR_NOT_ELIGIBLE,
                "This instructor may no longer teach for the managing department "
                "of the offering.",
                instructor,
                managing_department_id=offering.managing_department_id,
            )
            return

        if not self.resources.has_instructor_availability(instructor.pk):
            self._add_instructor_issue(
                IssueCode.INSTRUCTOR_AVAILABILITY_MISSING,
                "This instructor has no active availability for the semester.",
                instructor,
            )
            return

        usable = self.resources.usable_for_instructor(instructor.pk)
        if session_minutes > usable.max_contiguous_minutes:
            self.collector.add(
                IssueCode.INSTRUCTOR_SESSION_DURATION_UNSUPPORTED,
                Severity.ERROR,
                "The session duration of this component does not fit any "
                "contiguous block of time slots the instructor is available for.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                instructor_id=instructor.pk,
                session_duration_minutes=session_minutes,
                instructor_longest_block_minutes=usable.max_contiguous_minutes,
            )

    def _add_instructor_issue(
        self,
        code: str,
        message: str,
        instructor,
        *,
        severity: str = Severity.ERROR,
        **details,
    ) -> None:
        """Record an instructor-scoped issue, deduplicated per instructor.

        The severity is explicit because the missing-limit findings are warnings
        while everything else at instructor level blocks generation; defaulting to
        ``ERROR`` here is what a caller expects in the common case.
        """
        self.collector.add(
            code,
            severity,
            message,
            EntityType.INSTRUCTOR,
            instructor.pk,
            full_name=instructor.full_name,
            staff_code=instructor.staff_code,
            **details,
        )

    def _check_instructor_totals(self) -> None:
        """Necessary weekly and daily workload ceilings per active instructor.

        Only active instructors with at least one active assignment inside the
        validated scope are aggregated; an inactive instructor already has an
        error of its own and its workload numbers would be misleading.
        """
        for instructor_id in sorted(self._assignments):
            instructor = self._instructors[instructor_id]
            if not instructor.is_active:
                continue
            components = list(self._assignments[instructor_id].values())
            assigned_minutes = sum(
                hours_to_minutes(component.weekly_hours) for component in components
            )
            usable = self.resources.usable_for_instructor(instructor_id)
            self._check_instructor_load(instructor, assigned_minutes, usable)

    def _check_instructor_load(self, instructor, assigned_minutes: int, usable) -> None:
        """Compare assigned minutes with limits and with usable availability."""
        if self.resources.has_instructor_availability(instructor.pk):
            if assigned_minutes > usable.total_minutes:
                self._add_instructor_issue(
                    IssueCode.INSTRUCTOR_AVAILABLE_TIME_INSUFFICIENT,
                    "The assigned weekly hours exceed the time slots covered by "
                    "the instructor's availability.",
                    instructor,
                    assigned_weekly_minutes=assigned_minutes,
                    usable_availability_minutes=usable.total_minutes,
                )

        max_weekly_minutes = hours_to_minutes(instructor.max_weekly_hours)
        if instructor.max_weekly_hours is None:
            self._add_instructor_issue(
                IssueCode.INSTRUCTOR_MAX_WEEKLY_HOURS_NOT_CONFIGURED,
                "This instructor has no weekly hour limit configured, so weekly "
                "load cannot be checked.",
                instructor,
                severity=Severity.WARNING,
            )
        elif assigned_minutes > max_weekly_minutes:
            self._add_instructor_issue(
                IssueCode.INSTRUCTOR_MAX_WEEKLY_HOURS_EXCEEDED,
                "The assigned weekly hours exceed the instructor's weekly limit.",
                instructor,
                assigned_weekly_minutes=assigned_minutes,
                max_weekly_minutes=max_weekly_minutes,
            )

        # Severity differs from the other instructor issues, so it bypasses the
        # ERROR-defaulting helper above.
        if instructor.max_daily_hours is None:
            self.collector.add(
                IssueCode.INSTRUCTOR_MAX_DAILY_HOURS_NOT_CONFIGURED,
                Severity.WARNING,
                "This instructor has no daily hour limit configured, so daily "
                "load cannot be checked.",
                EntityType.INSTRUCTOR,
                instructor.pk,
                full_name=instructor.full_name,
                staff_code=instructor.staff_code,
            )
            return

        max_daily_minutes = hours_to_minutes(instructor.max_daily_hours)
        components = list(self._assignments[instructor.pk].values())
        longest_session = max(
            hours_to_minutes(component.session_duration_hours)
            for component in components
        )
        if longest_session > max_daily_minutes:
            self._add_instructor_issue(
                IssueCode.INSTRUCTOR_MAX_DAILY_HOURS_IMPOSSIBLE,
                "A session of this instructor is longer than the instructor's "
                "daily hour limit, so it can never be placed.",
                instructor,
                reason="session_longer_than_daily_limit",
                longest_session_minutes=longest_session,
                max_daily_minutes=max_daily_minutes,
            )
        elif usable.days * max_daily_minutes < assigned_minutes:
            self._add_instructor_issue(
                IssueCode.INSTRUCTOR_MAX_DAILY_HOURS_IMPOSSIBLE,
                "The assigned weekly hours exceed the weekly ceiling implied by "
                "the instructor's daily limit and usable working days.",
                instructor,
                reason="weekly_ceiling_below_demand",
                assigned_weekly_minutes=assigned_minutes,
                usable_days=usable.days,
                max_daily_minutes=max_daily_minutes,
                usable_weekly_ceiling_minutes=usable.days * max_daily_minutes,
            )

    # --- rooms -------------------------------------------------------------

    def _check_component_room(self, component: TeachingComponent) -> None:
        """Room requirement validity, then the existence of a viable room.

        A broken requirement chain (inactive requirement, inactive required room
        type or an inactive required capability) is reported once and stops the
        deeper check: no room could satisfy it, so a "no suitable room" error
        would only restate the same root cause.
        """
        requirement = getattr(component, "room_requirement", None)
        if requirement is None:
            self.collector.add(
                IssueCode.ROOM_REQUIREMENT_MISSING,
                Severity.ERROR,
                "This teaching component has no active room requirement.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                course_code=component.offering.course.code,
                component_type=component.component_type,
            )
            return
        if not requirement.is_active:
            self.collector.add(
                IssueCode.ROOM_REQUIREMENT_INACTIVE,
                Severity.ERROR,
                "The room requirement of this teaching component exists but is "
                "inactive.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                room_requirement_id=requirement.pk,
                course_code=component.offering.course.code,
            )
            return

        required_type = requirement.required_room_type
        if required_type is not None and not required_type.is_active:
            self.collector.add(
                IssueCode.ROOM_TYPE_INACTIVE,
                Severity.ERROR,
                "This room type is required by a teaching component but is "
                "inactive.",
                EntityType.ROOM_TYPE,
                required_type.pk,
                room_type_code=required_type.code,
                room_type_name=required_type.name,
            )
            return

        capability_links = list(requirement.capability_requirements.all())
        inactive_capability = False
        for link in capability_links:
            capability = link.capability
            if not capability.is_active:
                inactive_capability = True
                self.collector.add(
                    IssueCode.ROOM_CAPABILITY_INACTIVE,
                    Severity.ERROR,
                    "This room capability is required by a teaching component but "
                    "is inactive.",
                    EntityType.ROOM_CAPABILITY,
                    capability.pk,
                    capability_code=capability.code,
                    capability_name=capability.name,
                )
        if inactive_capability:
            return

        candidates = self.resources.candidate_rooms(requirement)
        session_minutes = hours_to_minutes(component.session_duration_hours)
        weekly_minutes = hours_to_minutes(component.weekly_hours)
        if not candidates:
            self.collector.add(
                IssueCode.NO_SUITABLE_ROOM,
                Severity.ERROR,
                "No active room currently satisfies the requirement of this "
                "teaching component.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                course_code=component.offering.course.code,
                component_type=component.component_type,
                effective_minimum_capacity=requirement.effective_minimum_capacity,
                required_room_type_id=requirement.required_room_type_id,
            )
            return

        viable = 0
        best_block = 0
        best_usable = 0
        for room in candidates:
            usable = self.resources.usable_for_room(room.pk)
            best_block = max(best_block, usable.max_contiguous_minutes)
            best_usable = max(best_usable, usable.total_minutes)
            if (
                usable.max_contiguous_minutes >= session_minutes
                and usable.total_minutes >= weekly_minutes
            ):
                viable += 1

        # At least one candidate must be able to host both a single session and
        # the component's whole weekly demand. This proves a room *exists*; it
        # does not reserve it or avoid collisions with other components.
        if viable == 0:
            self.collector.add(
                IssueCode.NO_SUITABLE_ROOM_WITH_AVAILABILITY,
                Severity.ERROR,
                "Suitable rooms exist, but none of them has enough available "
                "time-slot block for this teaching component.",
                EntityType.TEACHING_COMPONENT,
                component.pk,
                course_code=component.offering.course.code,
                component_type=component.component_type,
                candidate_room_count=len(candidates),
                session_duration_minutes=session_minutes,
                weekly_minutes=weekly_minutes,
                best_candidate_block_minutes=best_block,
                best_candidate_usable_minutes=best_usable,
            )
