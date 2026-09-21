"""Calendar and pre-scheduling permission rules for the scheduling app.

The time grid (working days, time slots, breaks) is college-wide configuration:
everyone authenticated reads it, only college administrators write it.

Calendar exceptions are scoped, so both writes and reads depend on the scope:

* writes need a college administrator, or a department administrator whose
  department owns the targeted resource (``CalendarException.owning_department_id``
  is the single source for that mapping);
* reads give every authenticated user the college-wide exceptions, plus the
  own-department exceptions, instructor exceptions shared under the Phase 4
  instructor sharing rules, room exceptions shared under the Phase 5 room rules,
  and student-group exceptions for groups of the user's own department. Joint
  course participation alone does not expose unrelated private
  absence/closure records, and a user without a department sees the college-wide
  exceptions and nothing else.

Phase 7 adds the validation scope rules: the validator is an operational tool, so
``VIEWER`` and ``INSTRUCTOR`` may not run it, a department-scoped user may only
validate its own department (and never the whole college), and a department-scoped
user without a department fails closed.

Phase 10 adds the college-wide generation gate: scheduling every department at once
is a college-level act, so ``COLLEGE_ADMIN`` and superusers may run it and nobody
else can reach it through this API.

Phase 11 adds persisted schedule drafts. Reading one is an administrative act, not
a teaching convenience: college administrators see every schedule, a department's
own users see that department's drafts, college-wide drafts stay with college
administrators until a later workflow publishes them, and ``INSTRUCTOR`` gets no
administrative access at all. A department user without a department fails closed,
and joint participation in another department's course grants no draft visibility.

Phase 12 adds manual editing of a draft. It is a smaller role set than reading, and
it deliberately reuses the read scoping for reachability: whatever a role cannot see
it also cannot edit, so the two rules cannot disagree.

Phase 13 adds workflow and publication. Advancing a stage needs a management role
(``VIEWER`` and ``INSTRUCTOR`` cannot), which stage a role may advance depends on the
schedule's scope, and the published timetable gets its own visibility rule because it
is the first artefact meant to be read outside schedule management.
"""

from django.db import models
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import UserRole
from accounts.permissions import is_authenticated_active_user
from resources.permissions import instructor_sharing_q, room_sharing_q
from scheduling.models import ExceptionScope, ScheduleScope
from scheduling.services.validation import ValidationScope


def visible_calendar_exceptions_filter(user) -> models.Q:
    """Calendar exceptions a user may read.

    College-wide exceptions affect everybody, so they stay readable to any
    authenticated user - including one without a department. Every other scope
    needs a department to resolve through.
    """
    department = user.department
    if department is None:
        return models.Q(scope_type=ExceptionScope.COLLEGE)
    department_id = department.pk
    return (
        models.Q(scope_type=ExceptionScope.COLLEGE)
        | models.Q(scope_type=ExceptionScope.DEPARTMENT, department_id=department_id)
        | (
            models.Q(scope_type=ExceptionScope.INSTRUCTOR)
            & instructor_sharing_q("instructor__", department)
        )
        | (
            models.Q(scope_type=ExceptionScope.ROOM)
            & room_sharing_q("room__", department)
        )
        | models.Q(
            scope_type=ExceptionScope.STUDENT_GROUP,
            student_group__stage__program__department_id=department_id,
        )
    )


class CanManageCalendarExceptions(BasePermission):
    """Calendar exceptions: college admins anywhere, department admins in scope.

    Read access stays open to authenticated users (queryset scoping decides what
    they see); writes require a college administrator, or a department
    administrator whose department owns the targeted resource.
    """

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return user.has_cross_department_access or (
            user.is_department_admin and user.department_id is not None
        )

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if user.has_cross_department_access:
            return True
        if not (user.is_department_admin and user.department_id is not None):
            return False
        return obj.owning_department_id == user.department_id


class CanRunPreSchedulingValidation(BasePermission):
    """Role gate for the pre-scheduling validator.

    Validation is an operational tool rather than a reading convenience:
    ``SCHEDULER`` and the administrative roles may run it, while ``VIEWER`` and
    ``INSTRUCTOR`` may not. Which semester and department a caller may validate is
    decided separately by :func:`resolve_validation_scope`, because that depends
    on the request body rather than on the role alone.
    """

    #: Roles allowed to run validation.
    allowed_roles = frozenset(
        {UserRole.COLLEGE_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER}
    )

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        user = request.user
        if user.is_superuser:
            return True
        return user.role in self.allowed_roles


class CanRunCollegeScheduleGeneration(BasePermission):
    """Role gate for the college-wide generation endpoint.

    Scheduling every department in one problem is a college-level act, so only a
    college administrator (or a Django superuser) may do it.

    ``DEPARTMENT_ADMIN``, ``SCHEDULER``, ``VIEWER`` and ``INSTRUCTOR`` are denied
    regardless of the department they belong to, and the endpoint takes no scope
    parameter that could relax this: there is no request body that lets a
    department-scoped caller reach the college-wide solver. Cross-department access
    is the same property Phase 7 uses to authorize college-wide validation, so the
    two endpoints cannot disagree about who is a college administrator.

    This gate is about *running* the solver. It never widens academic data: the
    candidate builder still enforces each component's managing-department resource
    rules, so a college administrator cannot schedule an instructor or a room that
    sharing rules withhold from a department.
    """

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        return request.user.has_cross_department_access


#: Roles that may read persisted schedule drafts and their version history.
#: ``INSTRUCTOR`` is deliberately absent: instructor-facing timetables belong to the
#: publication workflow, not to draft administration.
SCHEDULE_READ_ROLES = frozenset(
    {
        UserRole.COLLEGE_ADMIN,
        UserRole.DEPARTMENT_ADMIN,
        UserRole.SCHEDULER,
        UserRole.VIEWER,
    }
)


def can_read_schedule_data(user) -> bool:
    """True when the user's role may read persisted schedule drafts at all."""
    return bool(user.is_superuser or user.role in SCHEDULE_READ_ROLES)


def visible_schedules_filter(user) -> models.Q:
    """Which persisted schedules a user may read.

    College administrators and superusers read everything. A department user reads
    that department's own drafts only: the college-wide draft stays with college
    administrators, another department's draft stays out of reach, and a user
    without a department sees nothing. Joint participation in another department's
    course grants no draft access, because participation is not schedule-management
    authority.
    """
    if user.has_cross_department_access:
        return models.Q()
    if user.department_id is None or not can_read_schedule_data(user):
        return models.Q(pk__in=[])
    return models.Q(
        scope=ScheduleScope.DEPARTMENT, department_id=user.department_id
    )


class CanReadScheduleData(BasePermission):
    """Role gate for the persisted schedule, version and entry read APIs.

    The role decides whether the APIs are reachable at all; which rows come back is
    decided by :func:`visible_schedules_filter`, so an out-of-scope schedule answers
    ``404`` instead of advertising its existence.
    """

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        return can_read_schedule_data(request.user)


#: Roles that may propose and store a manual edit of a draft version.
#: ``VIEWER`` is deliberately absent: reading a draft is not editing it.
SCHEDULE_EDIT_ROLES = frozenset(
    {UserRole.COLLEGE_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER}
)


def can_edit_schedule_data(user) -> bool:
    """True when the user's role may create a manual version at all."""
    return bool(user.is_superuser or user.role in SCHEDULE_EDIT_ROLES)


#: Roles that may move a schedule version along the workflow.
#: ``VIEWER`` is read-only and ``INSTRUCTOR`` has no draft-management authority.
SCHEDULE_WORKFLOW_ROLES = frozenset(
    {UserRole.COLLEGE_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER}
)


def can_run_schedule_workflow(user) -> bool:
    """True when the user's role may advance a workflow stage at all."""
    return bool(user.is_superuser or user.role in SCHEDULE_WORKFLOW_ROLES)


class CanRunScheduleWorkflow(BasePermission):
    """Role gate for the workflow actions and the workflow validation report.

    The role decides whether the endpoints are reachable. The finer question - may
    this role advance *this* stage on *this* schedule - is answered by the workflow
    service, because the answer depends on the schedule's scope as well as the role:
    a department administrator may submit their own draft but never review or approve
    it, and only a college administrator may move a college-wide schedule.

    Reachability reuses the read-scoped queryset, so a version the caller cannot read
    answers ``404`` rather than a disclosing ``403``.
    """

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        return can_run_schedule_workflow(request.user)


class CanEditScheduleDraft(BasePermission):
    """Role gate for the manual-edit validate and apply endpoints.

    The role decides whether manual editing is reachable; *which* schedule may be
    edited is decided by the same queryset scoping the read APIs use. That keeps two
    rules true without restating them: a department administrator cannot reach another
    department's draft, and nobody below college administrator can reach a college-wide
    draft, because such a version is not in their queryset at all (``404`` rather than
    a disclosing ``403``).

    ``VIEWER`` and ``INSTRUCTOR`` are refused outright, and participating in a joint
    course grants no edit authority over the department that manages it.
    """

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        return can_edit_schedule_data(request.user)


def resolve_validation_scope(user, *, scope, department):
    """Authorize a validation request and return the department to validate.

    Raises ``PermissionDenied`` (HTTP 403) when the caller's role or department
    scope forbids the request outright, and ``ValidationError`` (HTTP 400) when
    the submitted department is outside the caller's scope. The 400 follows the
    project convention for an out-of-scope *payload* reference (see
    ``DepartmentScopeWriteMixin``), while 403 marks a role-level denial; neither
    answer reveals anything about another department's data.
    """
    if scope == ValidationScope.COLLEGE:
        if department is not None:
            raise ValidationError(
                {"department": "Omit department when scope is COLLEGE."}
            )
        if not user.has_cross_department_access:
            raise PermissionDenied(
                "Only college administrators may validate the whole college."
            )
        return None

    if department is None:
        raise ValidationError(
            {"department": "This field is required when scope is DEPARTMENT."}
        )
    if user.has_cross_department_access:
        return department
    if user.department_id is None:
        raise PermissionDenied(
            "Your account is not attached to a department, so there is no scope "
            "to validate."
        )
    if department.pk != user.department_id:
        raise ValidationError(
            {"department": "You may only validate your own department."}
        )
    return department


__all__ = [
    "SCHEDULE_EDIT_ROLES",
    "SCHEDULE_READ_ROLES",
    "SCHEDULE_WORKFLOW_ROLES",
    "CanEditScheduleDraft",
    "CanManageCalendarExceptions",
    "CanReadScheduleData",
    "CanRunCollegeScheduleGeneration",
    "CanRunPreSchedulingValidation",
    "CanRunScheduleWorkflow",
    "can_edit_schedule_data",
    "can_read_schedule_data",
    "can_run_schedule_workflow",
    "resolve_validation_scope",
    "visible_calendar_exceptions_filter",
    "visible_schedules_filter",
]
