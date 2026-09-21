"""Independent acceptance coverage for Phase 11 schedule persistence."""

import pytest
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.tokens import AccessToken
from unittest.mock import patch

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
from scheduling.services.generation.service import DepartmentScheduleGenerator
from scheduling.services.persistence.service import SchedulePersistenceService
from tests.test_phase7_validator_acceptance import ready_graph as phase7_ready_graph


DEPARTMENT_DRAFT_URL = "/api/schedules/generate-department-draft/"
DEPARTMENT_PREVIEW_URL = "/api/scheduling/generate/"
COLLEGE_DRAFT_URL = "/api/schedules/generate-college-draft/"


def authenticate(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def make_user(role, department=None):
    return User.objects.create_user(
        username=f"phase11-{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


@pytest.fixture
def ready_graph(db):
    return phase7_ready_graph.__wrapped__(db)


def department_payload(graph, **extra):
    return {
        "semester": graph["semester"].pk,
        "department": graph["departments"]["A"].pk,
        **extra,
    }


def test_department_draft_persists_complete_snapshot_and_strict_lineage(
    api_client, ready_graph
):
    graph = ready_graph
    authenticate(
        api_client,
        make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"]),
    )

    first = api_client.post(DEPARTMENT_DRAFT_URL, department_payload(graph), format="json")
    second = api_client.post(DEPARTMENT_DRAFT_URL, department_payload(graph), format="json")

    assert first.status_code == second.status_code == 200
    assert first.json()["persisted"] is True
    assert first.json()["version"]["status"] == ScheduleStatus.DRAFT
    assert first.json()["version"]["version_number"] == 1
    schedule = Schedule.objects.get(
        semester=graph["semester"], scope=ScheduleScope.DEPARTMENT,
        department=graph["departments"]["A"],
    )
    versions = list(schedule.versions.order_by("version_number"))
    assert len(versions) == 2
    assert [version.version_number for version in versions] == [1, 2]
    assert versions[0].parent_version is None
    assert versions[1].parent_version_id == versions[0].pk
    assert all(version.status == ScheduleStatus.DRAFT for version in versions)
    assert ScheduleEntry.objects.filter(schedule_version=versions[0]).count() == 1

    entry = ScheduleEntry.objects.get(schedule_version=versions[0])
    assert entry.session_id.startswith(f"component:{graph['component'].pk}:session:")
    assert entry.teaching_component_id == graph["component"].pk
    assert entry.managing_department_id == graph["departments"]["A"].pk
    assert ScheduleEntryTimeSlot.objects.filter(schedule_entry=entry).count() == 2
    assert ScheduleEntryInstructor.objects.filter(schedule_entry=entry).count() == 1
    assert ScheduleEntryStudentGroup.objects.filter(schedule_entry=entry).count() == 1
    original_course_name = entry.course_name_snapshot
    course = graph["component"].offering.course
    course.name = "Renamed after persistence"
    course.save(update_fields=["name"])
    entry.refresh_from_db()
    assert entry.course_name_snapshot == original_course_name


def test_preview_stays_nonpersistent_and_draft_rejects_client_control_fields(
    api_client, ready_graph
):
    graph = ready_graph
    authenticate(
        api_client,
        make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"]),
    )

    preview = api_client.post(DEPARTMENT_PREVIEW_URL, department_payload(graph), format="json")
    assert preview.status_code == 200
    assert preview.json()["persisted"] is False
    assert not Schedule.objects.exists()
    assert not ScheduleVersion.objects.exists()
    assert not ScheduleEntry.objects.exists()

    for field, value in (
        ("status", "PUBLISHED"),
        ("version_number", 99),
        ("placements", [{"room": 999}]),
        ("scope", "COLLEGE"),
        ("reservations", []),
        ("random_seed", 7),
    ):
        response = api_client.post(
            DEPARTMENT_DRAFT_URL, department_payload(graph, **{field: value}),
            format="json",
        )
        assert response.status_code == 400, (field, response.content)


def test_schedule_scope_and_logical_uniqueness_database_constraints(ready_graph):
    graph = ready_graph
    semester = graph["semester"]
    department_a = graph["departments"]["A"]
    department_b = graph["departments"]["B"]

    Schedule.objects.create(
        semester=semester, scope=ScheduleScope.DEPARTMENT, department=department_a
    )
    Schedule.objects.create(
        semester=semester, scope=ScheduleScope.DEPARTMENT, department=department_b
    )
    Schedule.objects.create(semester=semester, scope=ScheduleScope.COLLEGE)

    with pytest.raises(IntegrityError), transaction.atomic():
        Schedule.objects.create(
            semester=semester, scope=ScheduleScope.DEPARTMENT, department=department_a
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Schedule.objects.create(semester=semester, scope=ScheduleScope.COLLEGE)
    with pytest.raises(IntegrityError), transaction.atomic():
        Schedule.objects.create(semester=semester, scope=ScheduleScope.DEPARTMENT)
    with pytest.raises(IntegrityError), transaction.atomic():
        Schedule.objects.create(
            semester=semester, scope=ScheduleScope.COLLEGE, department=department_a
        )


def test_college_draft_persists_college_scope_and_rejects_department_roles(
    api_client, ready_graph
):
    graph = ready_graph
    payload = {"semester": graph["semester"].pk}
    authenticate(
        api_client,
        make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"]),
    )
    assert api_client.post(COLLEGE_DRAFT_URL, payload, format="json").status_code == 403

    authenticate(api_client, make_user(UserRole.COLLEGE_ADMIN))
    response = api_client.post(COLLEGE_DRAFT_URL, payload, format="json")
    assert response.status_code == 200
    assert response.json()["persisted"] is True
    schedule = Schedule.objects.get(semester=graph["semester"], scope=ScheduleScope.COLLEGE)
    assert schedule.department_id is None
    assert schedule.versions.get().version_number == 1


def test_persistence_write_failure_rolls_back_new_schedule_and_version(ready_graph):
    graph = ready_graph
    outcome = DepartmentScheduleGenerator(
        semester=graph["semester"], department=graph["departments"]["A"],
        max_time_seconds=1,
    ).generate()
    service = SchedulePersistenceService(
        semester=graph["semester"], scope=ScheduleScope.DEPARTMENT,
        department=graph["departments"]["A"],
    )

    with patch.object(service, "_write_entries", side_effect=RuntimeError("forced")):
        with pytest.raises(RuntimeError, match="forced"):
            service.persist(outcome)

    assert not Schedule.objects.exists()
    assert not ScheduleVersion.objects.exists()
    assert not ScheduleEntry.objects.exists()
