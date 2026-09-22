"""Independent final acceptance coverage for auth and public API boundaries."""

import pytest

from accounts.models import User, UserRole


LOGIN_URL = "/api/auth/login/"
REFRESH_URL = "/api/auth/refresh/"
ME_URL = "/api/me/"


@pytest.mark.django_db
def test_final_auth_lifecycle_keeps_business_api_private(api_client):
    user = User.objects.create_user(
        username="phase17-user",
        password="secret-pass-123",
        role=UserRole.COLLEGE_ADMIN,
    )
    anonymous = api_client.get("/api/schedules/")
    assert anonymous.status_code == 401

    rejected = api_client.post(
        LOGIN_URL,
        {"username": user.username, "password": "wrong"},
        format="json",
    )
    assert rejected.status_code == 401
    login = api_client.post(
        LOGIN_URL,
        {"username": user.username, "password": "secret-pass-123"},
        format="json",
        HTTP_X_REQUEST_ID="phase17-auth-1",
    )
    assert login.status_code == 200
    assert login["X-Request-ID"] == "phase17-auth-1"
    tokens = login.json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert api_client.get(ME_URL).status_code == 200
    assert api_client.post(REFRESH_URL, {"refresh": tokens["refresh"]}, format="json").status_code == 200
    assert api_client.post(REFRESH_URL, {"refresh": "bad.token"}, format="json").status_code == 401


@pytest.mark.django_db
def test_only_health_and_auth_are_public_representative_surfaces(api_client):
    for path in ("/api/health/", "/api/health/live/", "/api/health/ready/"):
        assert api_client.get(path).status_code == 200
    assert api_client.post(LOGIN_URL, {}, format="json").status_code == 400
    assert api_client.post(REFRESH_URL, {}, format="json").status_code == 400
    for path in ("/api/courses/", "/api/rooms/", "/api/schedules/", "/api/audit-events/"):
        assert api_client.get(path).status_code == 401
