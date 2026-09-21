"""Independent acceptance tests for Phase 7 pre-scheduling validation."""

from datetime import time

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework_simplejwt.tokens import AccessToken

from academics.models import (
    AcademicYear,
    College,
    Course,
    CourseOffering,
    Department,
    Semester,
    StudentGroup,
    StudyProgram,
    StudyStage,
    StudyType,
    TeachingComponent,
    TeachingComponentGroup,
    TeachingComponentType,
    Weekday,
)
from accounts.models import User, UserRole
from resources.models import (
    AssignmentRole,
    InstructorAvailability,
    InstructorProfile,
    Room,
    RoomAvailability,
    RoomCapability,
    RoomCapabilityAssignment,
    RoomType,
    TeachingAssignment,
    TeachingComponentCapabilityRequirement,
    TeachingComponentRoomRequirement,
)
from scheduling.models import TimeSlot, WorkingDay
from scheduling.services.validation import PreSchedulingValidator, ValidationScope


VALIDATE_URL = "/api/scheduling/validate/"


def authenticate(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def make_user(role, department=None):
    return User.objects.create_user(
        username=f"{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


def issue_codes(response):
    return {issue["code"] for issue in response.json()["issues"]}


@pytest.fixture
def ready_graph(db):
    college = College.objects.create(name="College", code="COL")
    department_a = Department.objects.create(name="Department A", code="A", college=college)
    department_b = Department.objects.create(name="Department B", code="B", college=college)
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    semester = Semester.objects.create(academic_year=year, number=1)
    program = StudyProgram.objects.create(
        department=department_a,
        name="Program A",
        code="PA",
        study_type=StudyType.UNDERGRADUATE,
    )
    stage = StudyStage.objects.create(program=program, number=1, name="Stage 1")
    group = StudentGroup.objects.create(
        stage=stage, name="Group A", code="GA", student_count=25
    )
    course = Course.objects.create(
        department=department_a, name="Course A", code="CA"
    )
    offering = CourseOffering.objects.create(
        course=course,
        semester=semester,
        managing_department=department_a,
        offering_code="MAIN",
    )
    component = TeachingComponent.objects.create(
        offering=offering,
        component_type=TeachingComponentType.THEORY,
        weekly_hours="1.50",
        session_duration_hours="1.50",
    )
    TeachingComponentGroup.objects.create(
        teaching_component=component, student_group=group
    )
    instructor = InstructorProfile.objects.create(
        primary_department=department_a,
        full_name="Ada Lovelace",
        staff_code="I-A",
        max_weekly_hours="10.00",
        max_daily_hours="5.00",
    )
    TeachingAssignment.objects.create(
        teaching_component=component,
        instructor=instructor,
        assignment_role=AssignmentRole.PRIMARY,
    )
    room_type = RoomType.objects.create(name="Lecture", code="LECT")
    room = Room.objects.create(
        owner_department=department_a,
        name="Room A",
        code="RA",
        room_type=room_type,
        capacity=30,
    )
    TeachingComponentRoomRequirement.objects.create(
        teaching_component=component,
        required_room_type=room_type,
    )
    day = WorkingDay.objects.create(
        semester=semester,
        day_of_week=Weekday.MONDAY,
        start_time=time(8),
        end_time=time(10),
    )
    for sequence, start, end in ((1, time(8), time(8, 45)), (2, time(8, 45), time(9, 30))):
        TimeSlot.objects.create(
            working_day=day,
            sequence=sequence,
            start_time=start,
            end_time=end,
        )
    InstructorAvailability.objects.create(
        instructor=instructor,
        semester=semester,
        day_of_week=Weekday.MONDAY,
        start_time=time(8),
        end_time=time(9, 30),
    )
    RoomAvailability.objects.create(
        room=room,
        semester=semester,
        day_of_week=Weekday.MONDAY,
        start_time=time(8),
        end_time=time(9, 30),
    )
    return {
        "departments": {"A": department_a, "B": department_b},
        "semester": semester,
        "component": component,
        "instructor": instructor,
        "room": room,
        "day": day,
    }


@pytest.mark.django_db
def test_validator_endpoint_scope_input_and_read_only_behavior(api_client, ready_graph):
    graph = ready_graph
    payload = {
        "semester": graph["semester"].id,
        "scope": "DEPARTMENT",
        "department": graph["departments"]["A"].id,
    }
    assert api_client.post(VALIDATE_URL, payload, format="json").status_code == 401

    scheduler = make_user(UserRole.SCHEDULER, graph["departments"]["A"])
    authenticate(api_client, scheduler)
    before = {
        model: model.objects.count()
        for model in (TeachingComponent, TeachingAssignment, WorkingDay, TimeSlot, Room)
    }
    response = api_client.post(VALIDATE_URL, payload, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["scope"] == "DEPARTMENT"
    assert body["department"]["id"] == graph["departments"]["A"].id
    assert body["semester"]["id"] == graph["semester"].id
    assert body["summary"] == {"components_checked": 1, "errors": 0, "warnings": 0}
    assert body["issues"] == []
    assert before == {model: model.objects.count() for model in before}
    assert api_client.post(VALIDATE_URL, payload, format="json").json() == body

    invalid_payloads = (
        {"semester": graph["semester"].id, "scope": "DEPARTMENT"},
        {"semester": graph["semester"].id, "scope": "COLLEGE", "department": graph["departments"]["A"].id},
        {"semester": graph["semester"].id, "scope": "INVALID"},
        {"semester": 999999, "scope": "COLLEGE"},
        {"semester": graph["semester"].id, "scope": "DEPARTMENT", "department": 999999},
    )
    for invalid in invalid_payloads:
        assert api_client.post(VALIDATE_URL, invalid, format="json").status_code == 400


@pytest.mark.django_db
def test_validator_scope_authorization_isolation_and_role_gate(api_client, ready_graph):
    graph = ready_graph
    own = {
        "semester": graph["semester"].id,
        "scope": "DEPARTMENT",
        "department": graph["departments"]["A"].id,
    }
    foreign = {**own, "department": graph["departments"]["B"].id}
    college = {"semester": graph["semester"].id, "scope": "COLLEGE"}

    for role in (UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER):
        authenticate(api_client, make_user(role, graph["departments"]["A"]))
        assert api_client.post(VALIDATE_URL, own, format="json").status_code == 200
        assert api_client.post(VALIDATE_URL, foreign, format="json").status_code == 400
        assert api_client.post(VALIDATE_URL, college, format="json").status_code == 403

    college_admin = make_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, college_admin)
    assert api_client.post(VALIDATE_URL, foreign, format="json").status_code == 200
    assert api_client.post(VALIDATE_URL, college, format="json").status_code == 200

    for role in (UserRole.VIEWER, UserRole.INSTRUCTOR):
        authenticate(api_client, make_user(role, graph["departments"]["A"]))
        assert api_client.post(VALIDATE_URL, own, format="json").status_code == 403
    for role in (UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER):
        authenticate(api_client, make_user(role))
        assert api_client.post(VALIDATE_URL, own, format="json").status_code == 403


@pytest.mark.django_db
def test_validator_grid_and_resource_failures_and_warning_semantics(api_client, ready_graph):
    graph = ready_graph
    authenticate(api_client, make_user(UserRole.COLLEGE_ADMIN))
    payload = {"semester": graph["semester"].id, "scope": "COLLEGE"}

    graph["day"].time_slots.update(is_active=False)
    response = api_client.post(VALIDATE_URL, payload, format="json")
    assert response.status_code == 200
    assert "WORKING_DAY_NO_ACTIVE_SLOTS" in issue_codes(response)

    graph["day"].time_slots.update(is_active=True)
    RoomAvailability.objects.filter(room=graph["room"]).update(is_active=False)
    response = api_client.post(VALIDATE_URL, payload, format="json")
    assert "NO_SUITABLE_ROOM_WITH_AVAILABILITY" in issue_codes(response)

    RoomAvailability.objects.filter(room=graph["room"]).update(is_active=True)
    graph["instructor"].max_weekly_hours = None
    graph["instructor"].max_daily_hours = None
    graph["instructor"].save(update_fields=["max_weekly_hours", "max_daily_hours"])
    response = api_client.post(VALIDATE_URL, payload, format="json")
    assert response.json()["ready"] is True
    assert issue_codes(response) == {
        "INSTRUCTOR_MAX_WEEKLY_HOURS_NOT_CONFIGURED",
        "INSTRUCTOR_MAX_DAILY_HOURS_NOT_CONFIGURED",
    }
    assert response.json()["summary"] == {"components_checked": 1, "errors": 0, "warnings": 2}


@pytest.mark.django_db
def test_validator_prefetches_requirement_capabilities_without_per_row_queries(ready_graph):
    """Capability validation must not issue one query for every requirement link."""
    graph = ready_graph
    requirement = graph["component"].room_requirement
    for index in range(4):
        capability = RoomCapability.objects.create(
            name=f"Capability {index}", code=f"CAP-{index}"
        )
        RoomCapabilityAssignment.objects.create(room=graph["room"], capability=capability)
        TeachingComponentCapabilityRequirement.objects.create(
            room_requirement=requirement, capability=capability
        )

    with CaptureQueriesContext(connection) as queries:
        result = PreSchedulingValidator(
            semester=graph["semester"],
            scope=ValidationScope.COLLEGE,
        ).run()

    assert result.ready is True
    capability_point_lookups = [
        query["sql"]
        for query in queries.captured_queries
        if 'FROM "resources_roomcapability"' in query["sql"]
        and 'WHERE "resources_roomcapability"."id" =' in query["sql"]
    ]
    assert capability_point_lookups == []
