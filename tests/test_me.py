"""Acceptance tests for the Phase 1 current-user endpoint."""

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from academics.models import Department
from accounts.models import User, UserRole

ME_URL = "/api/me/"


@pytest.mark.django_db
def test_me_rejects_anonymous_user(api_client):
    response = api_client.get(ME_URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_me_returns_authenticated_user_identity_role_and_department(api_client):
    department = Department.objects.create(name="Computer Science", code="CS")
    user = User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="correct-pass-123",
        first_name="Alice",
        last_name="Planner",
        role=UserRole.SCHEDULER,
        department=department,
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")

    response = api_client.get(ME_URL)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": user.id,
        "username": "alice",
        "email": "alice@example.com",
        "first_name": "Alice",
        "last_name": "Planner",
        "full_name": "Alice Planner",
        "role": UserRole.SCHEDULER,
        "department": {
            "id": department.id,
            "name": "Computer Science",
            "code": "CS",
        },
    }
    forbidden_keys = {
        "password",
        "refresh",
        "access",
        "user_permissions",
        "groups",
        "is_superuser",
    }
    assert forbidden_keys.isdisjoint(body)


@pytest.mark.django_db
def test_me_returns_null_department_when_user_has_none(api_client):
    user = User.objects.create_user(username="viewer", password="correct-pass-123")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")

    response = api_client.get(ME_URL)

    assert response.status_code == 200
    assert response.json()["department"] is None


@pytest.mark.django_db
def test_me_full_name_falls_back_to_username(api_client):
    user = User.objects.create_user(
        username="no-names",
        password="correct-pass-123",
        first_name="",
        last_name="",
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")

    response = api_client.get(ME_URL)

    assert response.status_code == 200
    assert response.json()["full_name"] == "no-names"


@pytest.mark.django_db
def test_me_rejects_inactive_user_token(api_client):
    user = User.objects.create_user(username="inactive", password="correct-pass-123")
    token = AccessToken.for_user(user)
    user.is_active = False
    user.save(update_fields=["is_active"])
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    response = api_client.get(ME_URL)

    assert response.status_code == 401
