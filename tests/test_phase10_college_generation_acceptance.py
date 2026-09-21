"""Independent acceptance coverage for Phase 10 college generation."""

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User, UserRole
from tests.test_phase7_validator_acceptance import ready_graph as phase7_ready_graph


GENERATE_COLLEGE_URL = "/api/scheduling/generate-college/"


def authenticate(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


@pytest.fixture
def ready_graph(db):
    return phase7_ready_graph.__wrapped__(db)


def college_admin():
    return User.objects.create_user(
        username=f"phase10-college-{User.objects.count()}",
        password="secret-pass-123",
        role=UserRole.COLLEGE_ADMIN,
    )


@pytest.mark.parametrize(
    "unexpected_field, value",
    (("department", 1), ("scope", "COLLEGE")),
)
def test_college_generation_rejects_unsupported_scope_fields(
    api_client, ready_graph, unexpected_field, value
):
    """College endpoint must reject fields that could imply a hidden scope bypass."""
    authenticate(api_client, college_admin())
    response = api_client.post(
        GENERATE_COLLEGE_URL,
        {"semester": ready_graph["semester"].pk, unexpected_field: value},
        format="json",
    )
    assert response.status_code == 400
