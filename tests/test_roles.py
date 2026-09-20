"""Acceptance tests for reusable Phase 1 role permissions."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser

from accounts.models import User, UserRole
from accounts.permissions import (
    IsCollegeAdmin,
    IsCollegeOrDepartmentAdmin,
    IsDepartmentAdmin,
    IsInstructor,
    IsScheduler,
    IsViewer,
)


ROLE_PERMISSION_CASES = [
    (IsCollegeAdmin, UserRole.COLLEGE_ADMIN),
    (IsDepartmentAdmin, UserRole.DEPARTMENT_ADMIN),
    (IsScheduler, UserRole.SCHEDULER),
    (IsViewer, UserRole.VIEWER),
    (IsInstructor, UserRole.INSTRUCTOR),
]


def request_for(user):
    return SimpleNamespace(user=user)


@pytest.mark.django_db
@pytest.mark.parametrize(("permission_class", "allowed_role"), ROLE_PERMISSION_CASES)
@pytest.mark.parametrize("role", [choice.value for choice in UserRole])
def test_role_permissions_allow_only_their_matching_role(
    permission_class,
    allowed_role,
    role,
):
    user = User.objects.create_user(
        username=f"{permission_class.__name__}-{role}",
        password="secret-pass-123",
        role=role,
    )

    allowed = permission_class().has_permission(request_for(user), view=None)

    assert allowed is (role == allowed_role)


@pytest.mark.django_db
@pytest.mark.parametrize(("permission_class", "allowed_role"), ROLE_PERMISSION_CASES)
def test_role_permissions_deny_anonymous_users(permission_class, allowed_role):
    allowed = permission_class().has_permission(request_for(AnonymousUser()), view=None)

    assert allowed is False


@pytest.mark.django_db
@pytest.mark.parametrize(("permission_class", "allowed_role"), ROLE_PERMISSION_CASES)
def test_role_permissions_deny_inactive_users(permission_class, allowed_role):
    user = User.objects.create_user(
        username=f"inactive-{permission_class.__name__}",
        password="secret-pass-123",
        role=allowed_role,
        is_active=False,
    )

    allowed = permission_class().has_permission(request_for(user), view=None)

    assert allowed is False


@pytest.mark.django_db
def test_combined_admin_permission_allows_college_and_department_admins_only():
    for role in UserRole:
        user = User.objects.create_user(
            username=f"combined-{role.value}",
            password="secret-pass-123",
            role=role,
        )

        allowed = IsCollegeOrDepartmentAdmin().has_permission(request_for(user), None)

        assert allowed is (role in {UserRole.COLLEGE_ADMIN, UserRole.DEPARTMENT_ADMIN})


@pytest.mark.django_db
def test_superuser_behavior_is_limited_to_administrative_permissions():
    superuser = User.objects.create_superuser(
        username="operator",
        password="secret-pass-123",
        role=UserRole.VIEWER,
    )

    assert IsCollegeAdmin().has_permission(request_for(superuser), None) is True
    assert IsDepartmentAdmin().has_permission(request_for(superuser), None) is True
    assert IsCollegeOrDepartmentAdmin().has_permission(request_for(superuser), None) is True
    assert IsScheduler().has_permission(request_for(superuser), None) is False
    assert IsViewer().has_permission(request_for(superuser), None) is True
    assert IsInstructor().has_permission(request_for(superuser), None) is False
