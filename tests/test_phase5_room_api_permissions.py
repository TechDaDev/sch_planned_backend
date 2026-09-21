"""Independent acceptance tests for Phase 5 room API permissions."""

from datetime import time

import pytest
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
    Room,
    RoomAvailability,
    RoomCapability,
    RoomCapabilityAssignment,
    RoomDepartmentAccess,
    RoomType,
    SharingScope,
    TeachingComponentCapabilityRequirement,
    TeachingComponentRoomRequirement,
)

ROOM_TYPES_URL = "/api/room-types/"
ROOM_CAPABILITIES_URL = "/api/room-capabilities/"
ROOMS_URL = "/api/rooms/"
ROOM_ACCESS_URL = "/api/room-department-access/"
ROOM_CAPABILITY_ASSIGNMENTS_URL = "/api/room-capability-assignments/"
ROOM_AVAILABILITY_URL = "/api/room-availability/"
ROOM_REQUIREMENTS_URL = "/api/teaching-component-room-requirements/"
CAPABILITY_REQUIREMENTS_URL = "/api/teaching-component-capability-requirements/"

PHASE5_URLS = [
    ROOM_TYPES_URL,
    ROOM_CAPABILITIES_URL,
    ROOMS_URL,
    ROOM_ACCESS_URL,
    ROOM_CAPABILITY_ASSIGNMENTS_URL,
    ROOM_AVAILABILITY_URL,
    ROOM_REQUIREMENTS_URL,
    CAPABILITY_REQUIREMENTS_URL,
]


def authenticate(api_client, user):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def create_user(role, department=None, username=None):
    return User.objects.create_user(
        username=username or f"{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


def ids(response):
    return {item["id"] for item in response.json()}


@pytest.fixture
def phase5_graph(db):
    college = College.objects.create(name="College", code="COL")
    departments = {
        code: Department.objects.create(name=f"Department {code}", code=code, college=college)
        for code in ("A", "B", "C")
    }
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    semester = Semester.objects.create(academic_year=year, number=1)
    room_type = RoomType.objects.create(name="Lecture Hall", code="LECTURE")
    lab_type = RoomType.objects.create(name="Computer Lab", code="LAB")
    projector = RoomCapability.objects.create(name="Projector", code="PROJECTOR")
    computers = RoomCapability.objects.create(name="Computers", code="COMPUTERS")
    result = {
        "departments": departments,
        "semester": semester,
        "room_type": room_type,
        "lab_type": lab_type,
        "projector": projector,
        "computers": computers,
    }

    for code, department in departments.items():
        program = StudyProgram.objects.create(
            department=department,
            name=f"Program {code}",
            code=f"P{code}",
            study_type=StudyType.UNDERGRADUATE,
        )
        stage = StudyStage.objects.create(program=program, number=1, name="Stage 1")
        group = StudentGroup.objects.create(
            stage=stage,
            name=f"Group {code}",
            code=f"G{code}",
            student_count=20,
        )
        course = Course.objects.create(
            department=department,
            name=f"Course {code}",
            code=f"C{code}",
        )
        offering = CourseOffering.objects.create(
            course=course,
            semester=semester,
            managing_department=department,
            offering_code="MAIN",
        )
        component = TeachingComponent.objects.create(
            offering=offering,
            component_type=TeachingComponentType.THEORY,
            weekly_hours="2.00",
            session_duration_hours="2.00",
        )
        TeachingComponentGroup.objects.create(
            teaching_component=component,
            student_group=group,
        )
        room = Room.objects.create(
            owner_department=department,
            name=f"Room {code}",
            code=f"R-{code}",
            room_type=room_type,
            capacity=40,
        )
        RoomCapabilityAssignment.objects.create(room=room, capability=projector)
        RoomAvailability.objects.create(
            room=room,
            semester=semester,
            day_of_week=Weekday.SUNDAY,
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        requirement = TeachingComponentRoomRequirement.objects.create(
            teaching_component=component,
            required_room_type=room_type,
        )
        TeachingComponentCapabilityRequirement.objects.create(
            room_requirement=requirement,
            capability=projector,
        )
        result[code] = {
            "group": group,
            "course": course,
            "offering": offering,
            "component": component,
            "room": room,
            "requirement": requirement,
        }
    RoomDepartmentAccess.objects.create(
        room=result["A"]["room"],
        department=departments["C"],
    )
    return result


@pytest.mark.django_db
@pytest.mark.parametrize("url", PHASE5_URLS)
def test_phase5_endpoints_require_authentication_and_disable_delete(
    api_client,
    phase5_graph,
    url,
):
    assert api_client.get(url).status_code == 401
    assert api_client.post(url, {}, format="json").status_code == 401

    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    object_id = api_client.get(url).json()[0]["id"]
    assert api_client.delete(f"{url}{object_id}/").status_code == 405


@pytest.mark.django_db
def test_room_type_and_capability_are_college_admin_writable_only(api_client, phase5_graph):
    department_admin = create_user(
        UserRole.DEPARTMENT_ADMIN,
        department=phase5_graph["departments"]["A"],
    )
    authenticate(api_client, department_admin)
    assert api_client.get(ROOM_TYPES_URL).status_code == 200
    assert api_client.post(
        ROOM_TYPES_URL,
        {"name": "Seminar", "code": "SEMINAR"},
        format="json",
    ).status_code == 403
    assert api_client.post(
        ROOM_CAPABILITIES_URL,
        {"name": "Microscope", "code": "MICROSCOPE"},
        format="json",
    ).status_code == 403

    college_admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, college_admin)
    assert api_client.post(
        ROOM_TYPES_URL,
        {"name": "Seminar", "code": "SEMINAR"},
        format="json",
    ).status_code == 201
    assert api_client.post(
        ROOM_CAPABILITIES_URL,
        {"name": "Microscope", "code": "MICROSCOPE"},
        format="json",
    ).status_code == 201


@pytest.mark.django_db
def test_owner_department_admin_manages_room_children_and_foreign_writes_fail(api_client, phase5_graph):
    dept_a = phase5_graph["departments"]["A"]
    dept_b = phase5_graph["departments"]["B"]
    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_a)
    authenticate(api_client, admin_a)

    created = api_client.post(
        ROOMS_URL,
        {
            "owner_department": dept_a.id,
            "name": "New Lab A",
            "code": "NEW-A",
            "room_type": phase5_graph["lab_type"].id,
            "capacity": 30,
            "sharing_scope": SharingScope.SELECTED_DEPARTMENTS,
        },
        format="json",
    )
    assert created.status_code == 201
    room_id = created.json()["id"]

    assert api_client.patch(
        f"{ROOMS_URL}{room_id}/",
        {"owner_department": dept_b.id},
        format="json",
    ).status_code == 400
    assert api_client.patch(
        f"{ROOMS_URL}{phase5_graph['B']['room'].id}/",
        {"name": "Wrong"},
        format="json",
    ).status_code == 404

    assert api_client.post(
        ROOM_CAPABILITY_ASSIGNMENTS_URL,
        {"room": room_id, "capability": phase5_graph["computers"].id},
        format="json",
    ).status_code == 201
    assert api_client.post(
        ROOM_AVAILABILITY_URL,
        {
            "room": room_id,
            "semester": phase5_graph["semester"].id,
            "day_of_week": Weekday.MONDAY,
            "start_time": "08:00",
            "end_time": "10:00",
        },
        format="json",
    ).status_code == 201
    grant = api_client.post(
        ROOM_ACCESS_URL,
        {"room": room_id, "department": dept_b.id},
        format="json",
    )
    assert grant.status_code == 201

    assert api_client.post(
        ROOM_CAPABILITY_ASSIGNMENTS_URL,
        {"room": phase5_graph["B"]["room"].id, "capability": phase5_graph["computers"].id},
        format="json",
    ).status_code == 400


@pytest.mark.django_db
def test_shared_room_consumer_can_read_but_not_write_or_self_grant(api_client, phase5_graph):
    dept_a = phase5_graph["departments"]["A"]
    dept_b = phase5_graph["departments"]["B"]
    room_a = phase5_graph["A"]["room"]
    room_a.sharing_scope = SharingScope.SELECTED_DEPARTMENTS
    room_a.save(update_fields=["sharing_scope"])

    admin_b = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_b)
    authenticate(api_client, admin_b)
    self_grant = api_client.post(
        ROOM_ACCESS_URL,
        {"room": room_a.id, "department": dept_b.id},
        format="json",
    )
    assert self_grant.status_code == 400

    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_a)
    authenticate(api_client, admin_a)
    grant = api_client.post(
        ROOM_ACCESS_URL,
        {"room": room_a.id, "department": dept_b.id},
        format="json",
    )
    assert grant.status_code == 201

    authenticate(api_client, admin_b)
    assert room_a.id in ids(api_client.get(ROOMS_URL))
    assert RoomCapabilityAssignment.objects.get(room=room_a).id in ids(
        api_client.get(ROOM_CAPABILITY_ASSIGNMENTS_URL)
    )
    assert RoomAvailability.objects.get(room=room_a).id in ids(
        api_client.get(ROOM_AVAILABILITY_URL)
    )
    assert grant.json()["id"] in ids(api_client.get(ROOM_ACCESS_URL))

    assert api_client.patch(
        f"{ROOMS_URL}{room_a.id}/",
        {"name": "Consumer Edit"},
        format="json",
    ).status_code == 403
    assert api_client.patch(
        f"{ROOM_ACCESS_URL}{grant.json()['id']}/",
        {"is_active": False},
        format="json",
    ).status_code == 403


@pytest.mark.django_db
def test_room_requirement_management_and_joint_participant_read_only(api_client, phase5_graph):
    dept_a = phase5_graph["departments"]["A"]
    dept_b = phase5_graph["departments"]["B"]
    TeachingComponentGroup.objects.create(
        teaching_component=phase5_graph["A"]["component"],
        student_group=phase5_graph["B"]["group"],
    )
    phase5_graph["A"]["requirement"].delete()

    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_a)
    authenticate(api_client, admin_a)
    created = api_client.post(
        ROOM_REQUIREMENTS_URL,
        {
            "teaching_component": phase5_graph["A"]["component"].id,
            "required_room_type": phase5_graph["room_type"].id,
            "minimum_capacity": 25,
            "expected_student_count": 999,
            "effective_minimum_capacity": 999,
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.json()["expected_student_count"] == 40
    assert created.json()["effective_minimum_capacity"] == 40
    requirement_id = created.json()["id"]

    assert api_client.post(
        CAPABILITY_REQUIREMENTS_URL,
        {"room_requirement": requirement_id, "capability": phase5_graph["computers"].id},
        format="json",
    ).status_code == 201

    admin_b = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_b)
    authenticate(api_client, admin_b)
    assert requirement_id in ids(api_client.get(ROOM_REQUIREMENTS_URL))
    assert api_client.patch(
        f"{ROOM_REQUIREMENTS_URL}{requirement_id}/",
        {"minimum_capacity": 50},
        format="json",
    ).status_code == 403
    assert api_client.post(
        CAPABILITY_REQUIREMENTS_URL,
        {"room_requirement": requirement_id, "capability": phase5_graph["computers"].id},
        format="json",
    ).status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("role", [UserRole.SCHEDULER, UserRole.VIEWER, UserRole.INSTRUCTOR])
def test_read_only_roles_can_read_visible_rooms_but_not_write(api_client, phase5_graph, role):
    scoped_user = create_user(role, department=phase5_graph["departments"]["A"])
    authenticate(api_client, scoped_user)

    assert phase5_graph["A"]["room"].id in ids(api_client.get(ROOMS_URL))
    assert phase5_graph["A"]["requirement"].id in ids(api_client.get(ROOM_REQUIREMENTS_URL))
    assert api_client.post(
        ROOMS_URL,
        {
            "owner_department": phase5_graph["departments"]["A"].id,
            "name": "Denied",
            "code": "DENIED",
            "room_type": phase5_graph["room_type"].id,
            "capacity": 20,
        },
        format="json",
    ).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER, UserRole.VIEWER, UserRole.INSTRUCTOR],
)
def test_departmentless_scoped_users_fail_closed_for_room_resources(api_client, phase5_graph, role):
    scoped_user = create_user(role, department=None)
    authenticate(api_client, scoped_user)

    for url in (
        ROOMS_URL,
        ROOM_ACCESS_URL,
        ROOM_CAPABILITY_ASSIGNMENTS_URL,
        ROOM_AVAILABILITY_URL,
        ROOM_REQUIREMENTS_URL,
        CAPABILITY_REQUIREMENTS_URL,
    ):
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.django_db
def test_phase5_payload_tampering_returns_controlled_errors(api_client, phase5_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    payloads = (
        (
            ROOMS_URL,
            {
                "owner_department": phase5_graph["departments"]["A"].id,
                "name": "Bad",
                "code": "BAD",
                "room_type": phase5_graph["room_type"].id,
                "capacity": 0,
            },
        ),
        (
            ROOMS_URL,
            {
                "owner_department": 999999,
                "name": "Bad",
                "code": "BAD2",
                "room_type": phase5_graph["room_type"].id,
                "capacity": 10,
            },
        ),
        (ROOM_ACCESS_URL, {"room": 999999, "department": phase5_graph["departments"]["A"].id}),
        (ROOM_CAPABILITY_ASSIGNMENTS_URL, {"room": phase5_graph["A"]["room"].id, "capability": 999999}),
        (
            ROOM_AVAILABILITY_URL,
            {
                "room": phase5_graph["A"]["room"].id,
                "semester": phase5_graph["semester"].id,
                "day_of_week": 999,
                "start_time": "08:00",
                "end_time": "10:00",
            },
        ),
        (
            ROOM_REQUIREMENTS_URL,
            {
                "teaching_component": 999999,
                "required_room_type": phase5_graph["room_type"].id,
            },
        ),
        (
            CAPABILITY_REQUIREMENTS_URL,
            {"room_requirement": phase5_graph["A"]["requirement"].id, "capability": 999999},
        ),
    )

    for url, payload in payloads:
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
def test_phase5_openapi_documents_routes(api_client, phase5_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    response = api_client.get("/api/schema/", {"format": "json"})

    assert response.status_code == 200
    paths = response.json()["paths"]
    for url in PHASE5_URLS:
        assert "get" in paths[url]
        assert paths[url]["get"].get("security")
        assert "post" in paths[url]
        assert "delete" not in paths[f"{url}{{id}}/"]
