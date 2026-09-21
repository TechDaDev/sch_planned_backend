"""Phase 6 permission and visibility rules for the calendar layer.

The time grid (working days, time slots, breaks) is college-wide configuration:
everyone authenticated reads it, only college administrators write it.

Calendar exceptions are scoped, so both writes and reads depend on the scope:

* writes need a college administrator, or a department administrator whose
  department owns the targeted resource (``CalendarException.owning_department_id``
  is the single source for that mapping);
* reads give every authenticated user the college-wide and own-department
  exceptions, plus instructor exceptions shared under the Phase 4 instructor
  sharing rules, room exceptions shared under the Phase 5 room rules, and
  student-group exceptions for groups of the user's own department. Joint-course
  participation alone does not expose unrelated private absence/closure records.
"""

from django.db import models
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.permissions import is_authenticated_active_user
from resources.permissions import instructor_sharing_q, room_sharing_q
from scheduling.models import ExceptionScope


def visible_calendar_exceptions_filter(user) -> models.Q:
    """Calendar exceptions a department-scoped user may read."""
    department = user.department
    if department is None:
        return models.Q(pk__in=[])
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


__all__ = [
    "CanManageCalendarExceptions",
    "visible_calendar_exceptions_filter",
]
