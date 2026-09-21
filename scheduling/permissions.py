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
"""

from django.db import models
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import UserRole
from accounts.permissions import is_authenticated_active_user
from resources.permissions import instructor_sharing_q, room_sharing_q
from scheduling.models import ExceptionScope
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
    "CanManageCalendarExceptions",
    "CanRunPreSchedulingValidation",
    "resolve_validation_scope",
    "visible_calendar_exceptions_filter",
]
