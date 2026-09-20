"""Phase 2 permission classes for the academic structure API.

These build on the Phase 1 role model: ``COLLEGE_ADMIN`` (plus Django
superusers) may manage the whole college, ``DEPARTMENT_ADMIN`` may manage the
academic structure of their own department, and the remaining roles are
read-only. Every check fails closed for users without the required role or
without a department.

Queryset scoping in ``academics.views`` mirrors these rules so out-of-scope
records answer 404 instead of leaking their existence.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.permissions import IsCollegeAdmin, is_authenticated_active_user


def user_can_manage_department(user, department_id: int | None) -> bool:
    """Return True when ``user`` may manage records owned by ``department_id``.

    College administrators and superusers may manage any department; department
    administrators only their own. Returns False for an unresolvable department
    and for department-scoped users without a department.
    """
    if department_id is None:
        return False
    if user.has_cross_department_access:
        return True
    return bool(user.is_department_admin and user.department_id == department_id)


def resolve_department_id(obj, lookup_path: str) -> int | None:
    """Resolve the owning department id of ``obj`` following a model path.

    ``"pk"`` resolves the object itself (a department), ``"department"`` its own
    department foreign key, and ``"program__department"`` the department of its
    program. Returns None as soon as a hop is missing so callers fail closed.
    """
    current = obj
    parts = lookup_path.split("__")
    for part in parts[:-1]:
        current = getattr(current, part, None)
        if current is None:
            return None
    if parts[-1] == "pk":
        return getattr(current, "pk", None)
    return getattr(current, f"{parts[-1]}_id", None)


class IsCollegeAdminOrReadOnly(BasePermission):
    """College-wide resources (college, academic years, semesters).

    Any authenticated, active user may read them; only college administrators
    and superusers may write.
    """

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        if request.method in SAFE_METHODS:
            return True
        return IsCollegeAdmin().has_permission(request, view)


class CanManageDepartments(BasePermission):
    """Departments: reads for any authenticated user, writes role-restricted.

    Creating a department is reserved for college administrators (and
    superusers). Updating is allowed for college administrators and for the
    department's own administrator.
    """

    def has_permission(self, request, view) -> bool:
        if not is_authenticated_active_user(request):
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.method == "POST":
            return IsCollegeAdmin().has_permission(request, view)
        user = request.user
        return user.has_cross_department_access or (
            user.is_department_admin and user.department_id is not None
        )

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return user_can_manage_department(request.user, obj.pk)


class IsDepartmentScopedWriter(BasePermission):
    """Department-owned resources (programs, stages, student groups).

    Reads are open to any authenticated, active user (queryset scoping limits
    what they actually see). Writes require a college administrator, a
    superuser, or a department administrator whose department owns the record.

    The owning department is resolved through ``view.department_lookup``, the
    same ORM path the viewset uses to scope its queryset.
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
        lookup_path = getattr(view, "department_lookup", "department")
        return user_can_manage_department(
            request.user, resolve_department_id(obj, lookup_path)
        )


__all__ = [
    "CanManageDepartments",
    "IsCollegeAdminOrReadOnly",
    "IsDepartmentScopedWriter",
    "resolve_department_id",
    "user_can_manage_department",
]
