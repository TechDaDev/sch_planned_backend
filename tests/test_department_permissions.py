"""Acceptance tests for department-scoped Phase 1 object permissions."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser

from academics.models import Department
from accounts.models import User, UserRole
from accounts.permissions import IsSameDepartmentOrCollegeAdmin


def request_for(user):
    return SimpleNamespace(user=user)


@pytest.fixture
def departments(db):
    return (
        Department.objects.create(name="Department A", code="A"),
        Department.objects.create(name="Department B", code="B"),
    )


@pytest.fixture
def permission():
    return IsSameDepartmentOrCollegeAdmin()


@pytest.mark.django_db
def test_department_scope_allows_college_admin_for_any_department(permission, departments):
    department_a, department_b = departments
    user = User.objects.create_user(
        username="college-admin",
        password="secret-pass-123",
        role=UserRole.COLLEGE_ADMIN,
    )

    assert permission.has_object_permission(request_for(user), None, department_a) is True
    assert permission.has_object_permission(request_for(user), None, department_b) is True


@pytest.mark.django_db
def test_department_scope_allows_superuser_for_any_department(permission, departments):
    department_a, department_b = departments
    user = User.objects.create_superuser(
        username="operator",
        password="secret-pass-123",
        role=UserRole.VIEWER,
    )

    assert permission.has_object_permission(request_for(user), None, department_a) is True
    assert permission.has_object_permission(request_for(user), None, department_b) is True


@pytest.mark.django_db
def test_department_scope_allows_same_department_admin_only(permission, departments):
    department_a, department_b = departments
    user = User.objects.create_user(
        username="department-admin-a",
        password="secret-pass-123",
        role=UserRole.DEPARTMENT_ADMIN,
        department=department_a,
    )

    assert permission.has_object_permission(request_for(user), None, department_a) is True
    assert permission.has_object_permission(request_for(user), None, department_b) is False


@pytest.mark.django_db
def test_department_scope_denies_department_admin_with_no_department(
    permission,
    departments,
):
    department_a, _ = departments
    user = User.objects.create_user(
        username="department-admin-none",
        password="secret-pass-123",
        role=UserRole.DEPARTMENT_ADMIN,
        department=None,
    )

    assert permission.has_object_permission(request_for(user), None, department_a) is False


@pytest.mark.django_db
def test_department_scope_denies_inactive_or_anonymous_user(permission, departments):
    department_a, _ = departments
    inactive = User.objects.create_user(
        username="inactive-department-admin",
        password="secret-pass-123",
        role=UserRole.DEPARTMENT_ADMIN,
        department=department_a,
        is_active=False,
    )

    assert permission.has_permission(request_for(inactive), None) is False
    assert permission.has_permission(request_for(AnonymousUser()), None) is False


@pytest.mark.django_db
@pytest.mark.parametrize("attr_name", ["department_id", "department"])
def test_department_scope_supports_future_resource_department_shapes(
    permission,
    departments,
    attr_name,
):
    department_a, department_b = departments
    user = User.objects.create_user(
        username=f"department-admin-{attr_name}",
        password="secret-pass-123",
        role=UserRole.DEPARTMENT_ADMIN,
        department=department_a,
    )
    same_department_obj = SimpleNamespace(**{attr_name: department_a})
    different_department_obj = SimpleNamespace(**{attr_name: department_b})
    if attr_name == "department_id":
        same_department_obj.department_id = department_a.id
        different_department_obj.department_id = department_b.id

    assert (
        permission.has_object_permission(request_for(user), None, same_department_obj)
        is True
    )
    assert (
        permission.has_object_permission(request_for(user), None, different_department_obj)
        is False
    )


@pytest.mark.django_db
def test_department_scope_fails_closed_when_department_cannot_be_determined(
    permission,
    departments,
):
    department_a, _ = departments
    user = User.objects.create_user(
        username="department-admin-a",
        password="secret-pass-123",
        role=UserRole.DEPARTMENT_ADMIN,
        department=department_a,
    )

    assert permission.has_object_permission(request_for(user), None, SimpleNamespace()) is False
