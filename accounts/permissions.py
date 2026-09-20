"""Reusable DRF permission classes for application roles and department scope.

Conventions applied consistently across the project:

* ``has_permission`` always requires an authenticated **and active** user.
  Inactive users are rejected here as defence in depth (SimpleJWT already
  refuses to authenticate them).
* Django superusers pass the *administrative* role checks (college admin,
  department admin): ``createsuperuser`` accounts are framework-level operators
  and are not required to carry an application role. Superusers do **not**
  automatically pass the functional role checks (scheduler, viewer,
  instructor), because those describe a job function rather than a privilege
  level.
* Views must reuse these classes, or the ``User`` role properties, instead of
  comparing role strings inline.
"""

from rest_framework.permissions import BasePermission

from accounts.models import User, UserRole
from academics.models import Department


def is_authenticated_active_user(request) -> bool:
    """Return True when the request carries an authenticated, active user.

    Public because the Phase 2 academic permissions reuse this exact rule
    instead of defining a second active-user check.
    """
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_active)


class HasRole(BasePermission):
    """Base class for permissions that gate on a single application role."""

    role: str = ""
    #: Whether superusers bypass the role check (only for administrative roles).
    allow_superuser: bool = False

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        if self.allow_superuser and request.user.is_superuser:
            return True
        return request.user.role == self.role


class IsCollegeAdmin(HasRole):
    """Allows college administrators (and superusers)."""

    role = UserRole.COLLEGE_ADMIN
    allow_superuser = True


class IsDepartmentAdmin(HasRole):
    """Allows department administrators (and superusers)."""

    role = UserRole.DEPARTMENT_ADMIN
    allow_superuser = True


class IsScheduler(HasRole):
    """Allows schedulers. Superusers are not granted an implicit pass."""

    role = UserRole.SCHEDULER


class IsViewer(HasRole):
    """Allows viewers. Superusers are not granted an implicit pass."""

    role = UserRole.VIEWER


class IsInstructor(HasRole):
    """Allows instructors. Superusers are not granted an implicit pass."""

    role = UserRole.INSTRUCTOR


class IsCollegeOrDepartmentAdmin(BasePermission):
    """Allows any administrative application role, or a Django superuser."""

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        return request.user.is_superuser or request.user.has_admin_role


class IsSameDepartmentOrCollegeAdmin(BasePermission):
    """Object permission for department-owned resources.

    * Django superusers and college administrators may access objects belonging
      to any department.
    * Every other authenticated, active user may only access objects belonging
      to their own ``request.user.department``.
    * Fails closed: when the object's department cannot be determined, or a
      department-scoped user has no department of their own, access is denied.

    Authorization is based solely on ``request.user.department`` and the
    persisted object; department ids supplied by the client are never trusted.
    """

    def has_permission(self, request, view) -> bool:
        return is_authenticated_active_user(request)

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.has_cross_department_access:
            return True
        user_department_id = user.department_id
        if user_department_id is None:
            return False
        return _resolve_department_id(obj) == user_department_id


def _resolve_department_id(obj) -> int | None:
    """Return the department id of ``obj``, or None when it cannot be determined."""
    if isinstance(obj, Department):
        return obj.pk
    department_id = getattr(obj, "department_id", None)
    if department_id is not None:
        return department_id
    department = getattr(obj, "department", None)
    if department is None:
        return None
    return getattr(department, "pk", None)


__all__ = [
    "HasRole",
    "IsCollegeAdmin",
    "IsCollegeOrDepartmentAdmin",
    "IsDepartmentAdmin",
    "IsInstructor",
    "IsSameDepartmentOrCollegeAdmin",
    "IsScheduler",
    "IsViewer",
    "is_authenticated_active_user",
]
