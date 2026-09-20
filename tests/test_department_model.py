"""Acceptance tests for the Phase 1 Department model."""

import pytest
from django.db import IntegrityError, transaction

from academics.models import Department
from accounts.models import User


@pytest.mark.django_db
def test_department_has_required_identity_fields():
    department = Department.objects.create(name="Computer Science", code="CS")

    assert department.name == "Computer Science"
    assert department.code == "CS"
    assert department.is_active is True
    assert department.created_at is not None
    assert department.updated_at is not None
    assert str(department) == "Computer Science (CS)"


@pytest.mark.django_db
def test_department_code_is_unique_at_database_level():
    Department.objects.create(name="Computer Science", code="CS")

    with pytest.raises(IntegrityError), transaction.atomic():
        Department.objects.create(name="Computing Systems", code="CS")


@pytest.mark.django_db
def test_deleting_department_nulls_user_department():
    department = Department.objects.create(name="Computer Science", code="CS")
    user = User.objects.create_user(
        username="department-admin",
        password="secret-pass-123",
        department=department,
    )

    department.delete()
    user.refresh_from_db()

    assert user.department is None
    assert User.objects.filter(pk=user.pk).exists()
