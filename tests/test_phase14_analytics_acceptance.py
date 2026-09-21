"""Independent acceptance coverage for Phase 14 analytics."""

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User, UserRole
from scheduling.models import ScheduleEntry, ScheduleVersion
from tests.test_phase7_validator_acceptance import ready_graph as phase7_ready_graph


@pytest.fixture
def ready_graph(db):
    return phase7_ready_graph.__wrapped__(db)


def test_published_analytics_uses_authoritative_version_and_never_writes(api_client, ready_graph):
    graph = ready_graph
    user = User.objects.create_user(
        username="phase14-admin", password="secret-pass-123", role=UserRole.COLLEGE_ADMIN
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    assert api_client.post(
        "/api/schedules/generate-college-draft/", {"semester": graph["semester"].pk}, format="json"
    ).status_code == 200
    version = ScheduleVersion.objects.get(version_number=1)
    for action in ("submit", "review", "approve", "publish"):
        assert api_client.post(f"/api/schedule-versions/{version.pk}/{action}/", {}, format="json").status_code == 200
    before = (ScheduleVersion.objects.count(), ScheduleEntry.objects.count())
    response = api_client.get("/api/published-schedules/current/analytics/", {"semester": graph["semester"].pk})
    assert response.status_code == 200
    body = response.json()
    assert body["version"]["id"] == version.pk
    assert body["summary"]["entry_count"] == 1
    assert body["summary"]["scheduled_minutes"] == 90
    assert (ScheduleVersion.objects.count(), ScheduleEntry.objects.count()) == before
