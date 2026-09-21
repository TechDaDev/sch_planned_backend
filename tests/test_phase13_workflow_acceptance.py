"""Independent acceptance coverage for Phase 13 workflow and publication."""

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User, UserRole
from scheduling.models import (
    Schedule,
    ScheduleEntry,
    ScheduleEntryInstructor,
    ScheduleEntryStudentGroup,
    ScheduleEntryTimeSlot,
    ScheduleScope,
    ScheduleStatus,
    ScheduleVersion,
)
from tests.test_phase7_validator_acceptance import ready_graph as phase7_ready_graph


DEPARTMENT_DRAFT_URL = "/api/schedules/generate-department-draft/"
COLLEGE_DRAFT_URL = "/api/schedules/generate-college-draft/"
PUBLISHED_URL = "/api/published-schedules/current/"


def authenticate(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def make_user(role, department=None):
    return User.objects.create_user(
        username=f"phase13-{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


@pytest.fixture
def ready_graph(db):
    return phase7_ready_graph.__wrapped__(db)


def version_action_url(version, action):
    return f"/api/schedule-versions/{version.pk}/{action}/"


def test_college_workflow_publishes_without_mutating_entry_snapshots(api_client, ready_graph):
    graph = ready_graph
    admin = make_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    assert api_client.post(
        COLLEGE_DRAFT_URL, {"semester": graph["semester"].pk}, format="json"
    ).status_code == 200
    version = ScheduleVersion.objects.get(version_number=1)
    entry = ScheduleEntry.objects.get(schedule_version=version)
    before = (
        ScheduleEntry.objects.filter(schedule_version=version).count(),
        ScheduleEntryTimeSlot.objects.filter(schedule_entry=entry).count(),
        ScheduleEntryInstructor.objects.filter(schedule_entry=entry).count(),
        ScheduleEntryStudentGroup.objects.filter(schedule_entry=entry).count(),
        entry.candidate_id,
    )

    for action, expected in (
        ("submit", ScheduleStatus.SUBMITTED),
        ("review", ScheduleStatus.REVIEWED),
        ("approve", ScheduleStatus.APPROVED),
        ("publish", ScheduleStatus.PUBLISHED),
    ):
        response = api_client.post(version_action_url(version, action), {}, format="json")
        assert response.status_code == 200, response.content
        version.refresh_from_db()
        assert version.status == expected

    schedule = Schedule.objects.get(scope=ScheduleScope.COLLEGE)
    assert schedule.published_version_id == version.pk
    entry.refresh_from_db()
    assert (
        ScheduleEntry.objects.filter(schedule_version=version).count(),
        ScheduleEntryTimeSlot.objects.filter(schedule_entry=entry).count(),
        ScheduleEntryInstructor.objects.filter(schedule_entry=entry).count(),
        ScheduleEntryStudentGroup.objects.filter(schedule_entry=entry).count(),
        entry.candidate_id,
    ) == before
    published = api_client.get(PUBLISHED_URL, {"semester": graph["semester"].pk})
    assert published.status_code == 200
    assert published.json()["version"]["id"] == version.pk


def test_department_chain_rejects_publication_and_unauthorized_review(api_client, ready_graph):
    graph = ready_graph
    department_admin = make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"])
    authenticate(api_client, department_admin)
    assert api_client.post(
        DEPARTMENT_DRAFT_URL,
        {"semester": graph["semester"].pk, "department": graph["departments"]["A"].pk},
        format="json",
    ).status_code == 200
    version = ScheduleVersion.objects.get(version_number=1)
    assert api_client.post(version_action_url(version, "submit"), {}, format="json").status_code == 200
    review = api_client.post(version_action_url(version, "review"), {}, format="json")
    assert review.status_code == 403
    version.refresh_from_db()
    assert version.status == ScheduleStatus.SUBMITTED

    authenticate(api_client, make_user(UserRole.COLLEGE_ADMIN))
    assert api_client.post(version_action_url(version, "review"), {}, format="json").status_code == 200
    assert api_client.post(version_action_url(version, "approve"), {}, format="json").status_code == 200
    publish = api_client.post(version_action_url(version, "publish"), {}, format="json")
    assert publish.status_code == 409
    assert publish.json()["reason"] == "DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE"
