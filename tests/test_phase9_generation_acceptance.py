"""Independent acceptance tests for Phase 9 department generation."""

from datetime import time
from unittest.mock import patch

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from academics.models import Weekday
from accounts.models import User, UserRole
from resources.models import (
    AssignmentRole,
    InstructorAvailability,
    InstructorProfile,
    RoomAvailability,
    TeachingAssignment,
)
from scheduling.services.generation.blocks import (
    GridSlot,
    find_exact_contiguous_slot_blocks,
)
from scheduling.services.generation.candidates import DepartmentProblemBuilder
from tests.test_phase7_validator_acceptance import ready_graph as phase7_ready_graph


GENERATE_URL = "/api/scheduling/generate/"


def authenticate(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def make_user(role, department=None):
    return User.objects.create_user(
        username=f"phase9-{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


@pytest.fixture
def ready_graph(db):
    return phase7_ready_graph.__wrapped__(db)


def request_data(graph, **extra):
    return {
        "semester": graph["semester"].pk,
        "department": graph["departments"]["A"].pk,
        **extra,
    }


def test_generate_returns_pure_deterministic_preview(api_client, ready_graph):
    graph = ready_graph
    authenticate(
        api_client,
        make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"]),
    )

    first = api_client.post(GENERATE_URL, request_data(graph), format="json")
    second = api_client.post(GENERATE_URL, request_data(graph), format="json")

    assert first.status_code == second.status_code == 200
    assert first.json()["generated"] is True
    assert first.json()["persisted"] is False
    assert first.json()["placements"] == second.json()["placements"]
    placement = first.json()["placements"][0]
    assert placement["teaching_component"]["id"] == graph["component"].pk
    assert placement["slots"][0]["start_time"] == "08:00"
    assert placement["slots"][1]["end_time"] == "09:30"


def test_generate_permission_and_method_boundaries(api_client, ready_graph):
    graph = ready_graph
    payload = request_data(graph)
    assert api_client.get(GENERATE_URL).status_code == 401
    assert api_client.post(GENERATE_URL, payload, format="json").status_code == 401

    for role in (UserRole.VIEWER, UserRole.INSTRUCTOR):
        authenticate(api_client, make_user(role, graph["departments"]["A"]))
        assert api_client.post(GENERATE_URL, payload, format="json").status_code == 403

    authenticate(api_client, make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"]))
    assert api_client.get(GENERATE_URL).status_code == 405
    assert api_client.post(
        GENERATE_URL,
        request_data(graph, department=graph["departments"]["B"].pk),
        format="json",
    ).status_code == 400

    authenticate(api_client, make_user(UserRole.SCHEDULER, graph["departments"]["A"]))
    assert api_client.post(GENERATE_URL, payload, format="json").status_code == 200


def test_generate_rejects_bad_payloads_without_server_errors(api_client, ready_graph):
    graph = ready_graph
    authenticate(api_client, make_user(UserRole.COLLEGE_ADMIN))
    for payload in (
        {},
        request_data(graph, semester=999999),
        request_data(graph, department=999999),
        request_data(graph, max_time_seconds=0),
        request_data(graph, max_time_seconds=999999),
        request_data(graph, max_time_seconds="not-a-number"),
        {**request_data(graph), "scope": "COLLEGE"},
    ):
        response = api_client.post(GENERATE_URL, payload, format="json")
        assert response.status_code in (200, 400), response.content


def test_candidate_builder_requires_every_instructor_and_room_available(ready_graph):
    graph = ready_graph
    InstructorAvailability.objects.filter(instructor=graph["instructor"]).delete()
    bundle = DepartmentProblemBuilder(
        semester=graph["semester"], department=graph["departments"]["A"]
    ).build()
    assert not bundle.is_buildable
    assert not bundle.candidates


def test_candidate_builder_requires_assistant_availability(ready_graph):
    graph = ready_graph
    assistant = InstructorProfile.objects.create(
        primary_department=graph["departments"]["A"],
        full_name="Assistant", staff_code="PHASE9-ASSIST", max_weekly_hours="10.00",
        max_daily_hours="5.00",
    )
    TeachingAssignment.objects.create(
        teaching_component=graph["component"], instructor=assistant,
        assignment_role=AssignmentRole.ASSISTANT,
    )

    bundle = DepartmentProblemBuilder(
        semester=graph["semester"], department=graph["departments"]["A"]
    ).build()
    assert not bundle.is_buildable
    assert not bundle.candidates


def test_blocking_phase7_gate_returns_409_without_solver(api_client, ready_graph):
    graph = ready_graph
    authenticate(
        api_client,
        make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"]),
    )
    InstructorAvailability.objects.filter(instructor=graph["instructor"]).delete()

    with patch(
        "scheduling.services.generation.service.CpSatSchedulingEngine.solve"
    ) as solve:
        response = api_client.post(GENERATE_URL, request_data(graph), format="json")

    assert response.status_code == 409
    assert response.json()["generated"] is False
    assert response.json()["reason"] == "PRE_SCHEDULING_VALIDATION_FAILED"
    solve.assert_not_called()

    InstructorAvailability.objects.create(
        instructor=graph["instructor"], semester=graph["semester"],
        day_of_week=Weekday.MONDAY, start_time=time(8), end_time=time(9, 30),
    )
    RoomAvailability.objects.filter(room=graph["room"]).delete()
    bundle = DepartmentProblemBuilder(
        semester=graph["semester"], department=graph["departments"]["A"]
    ).build()
    assert not bundle.is_buildable
    assert not bundle.candidates


def test_exact_blocks_reject_gaps_and_overlong_periods():
    slots = (
        GridSlot(1, 0, 1, 8 * 60, 8 * 60 + 45),
        GridSlot(2, 0, 2, 8 * 60 + 45, 9 * 60 + 30),
        GridSlot(3, 0, 3, 10 * 60, 10 * 60 + 60),
    )
    blocks = find_exact_contiguous_slot_blocks(slots, 90)
    assert [block.slot_ids for block in blocks] == [(1, 2)]
    assert find_exact_contiguous_slot_blocks(slots, 100) == ()
