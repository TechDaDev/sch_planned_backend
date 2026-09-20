"""Acceptance tests for Phase 1 JWT authentication endpoints."""

import pytest

from accounts.models import User

LOGIN_URL = "/api/auth/login/"
REFRESH_URL = "/api/auth/refresh/"


@pytest.fixture
def active_user(db):
    return User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="correct-pass-123",
    )


@pytest.mark.django_db
def test_login_valid_credentials_returns_access_and_refresh(api_client, active_user):
    response = api_client.post(
        LOGIN_URL,
        {"username": active_user.username, "password": "correct-pass-123"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["access"]
    assert response.json()["refresh"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"username": "alice", "password": "wrong-pass"}, 401),
        ({"username": "missing", "password": "correct-pass-123"}, 401),
        ({"username": "alice"}, 400),
    ],
)
def test_login_rejects_invalid_inputs_without_tokens(
    api_client,
    active_user,
    payload,
    expected_status,
):
    response = api_client.post(LOGIN_URL, payload, format="json")

    assert response.status_code == expected_status
    assert response.status_code != 500
    assert "access" not in response.json()
    assert "refresh" not in response.json()


@pytest.mark.django_db
def test_login_rejects_inactive_user_without_tokens(api_client):
    User.objects.create_user(
        username="inactive",
        password="correct-pass-123",
        is_active=False,
    )

    response = api_client.post(
        LOGIN_URL,
        {"username": "inactive", "password": "correct-pass-123"},
        format="json",
    )

    assert response.status_code == 401
    assert response.status_code != 500
    assert "access" not in response.json()
    assert "refresh" not in response.json()


@pytest.mark.django_db
def test_refresh_valid_token_returns_new_access_token(api_client, active_user):
    login_response = api_client.post(
        LOGIN_URL,
        {"username": active_user.username, "password": "correct-pass-123"},
        format="json",
    )
    refresh = login_response.json()["refresh"]

    response = api_client.post(REFRESH_URL, {"refresh": refresh}, format="json")

    assert response.status_code == 200
    assert response.json()["access"]
    assert "refresh" not in response.json()


@pytest.mark.django_db
@pytest.mark.parametrize("refresh", ["not-a-token", "abc.def.ghi"])
def test_refresh_rejects_invalid_or_malformed_token_cleanly(api_client, refresh):
    response = api_client.post(REFRESH_URL, {"refresh": refresh}, format="json")

    assert 400 <= response.status_code < 500
    assert response.status_code != 500
    assert "access" not in response.json()


@pytest.mark.django_db
def test_deactivated_user_cannot_refresh_previously_valid_token(api_client, active_user):
    login_response = api_client.post(
        LOGIN_URL,
        {"username": active_user.username, "password": "correct-pass-123"},
        format="json",
    )
    refresh = login_response.json()["refresh"]

    active_user.is_active = False
    active_user.save(update_fields=["is_active"])

    response = api_client.post(REFRESH_URL, {"refresh": refresh}, format="json")

    assert 400 <= response.status_code < 500
    assert response.status_code != 500
    assert "access" not in response.json()
