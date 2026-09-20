"""Independent acceptance tests for Phase 3 course API behavior."""

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
)
from accounts.models import User, UserRole

COURSES_URL = "/api/courses/"
OFFERINGS_URL = "/api/course-offerings/"
COMPONENTS_URL = "/api/teaching-components/"
COMPONENT_GROUPS_URL = "/api/teaching-component-groups/"
PHASE3_URLS = [COURSES_URL, OFFERINGS_URL, COMPONENTS_URL, COMPONENT_GROUPS_URL]


def authenticate(api_client, user):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def create_user(role, department=None, **kwargs):
    username = kwargs.pop("username", f"{role.lower()}-{User.objects.count()}")
    return User.objects.create_user(
        username=username,
        password="secret-pass-123",
        role=role,
        department=department,
        **kwargs,
    )


@pytest.fixture
def teaching_graph(db):
    college = College.objects.create(name="College", code="COL")
    departments = {
        code: Department.objects.create(name=f"Department {code}", code=code, college=college)
        for code in ("A", "B", "C", "D")
    }
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    semester = Semester.objects.create(academic_year=year, number=1)
    result = {"college": college, "departments": departments, "semester": semester}

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
            code="ML301",
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
        result[code] = {
            "program": program,
            "stage": stage,
            "group": group,
            "course": course,
            "offering": offering,
            "component": component,
        }
    return result


def response_ids(response):
    return {item["id"] for item in response.json()}


@pytest.mark.django_db
@pytest.mark.parametrize("url", PHASE3_URLS)
def test_phase3_endpoints_require_authentication_and_disable_delete(
    api_client,
    teaching_graph,
    url,
):
    assert api_client.get(url).status_code == 401
    assert api_client.post(url, {}, format="json").status_code == 401

    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    object_id = api_client.get(url).json()[0]["id"]
    assert api_client.delete(f"{url}{object_id}/").status_code == 405


@pytest.mark.django_db
def test_college_admin_can_manage_phase3_resources_across_departments(
    api_client,
    teaching_graph,
):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    dept_a = teaching_graph["departments"]["A"]
    dept_b = teaching_graph["departments"]["B"]

    response = api_client.post(
        COURSES_URL,
        {"department": dept_b.id, "name": "B Advanced ML", "code": "AML"},
        format="json",
    )
    assert response.status_code == 201

    response = api_client.post(
        OFFERINGS_URL,
        {
            "course": teaching_graph["A"]["course"].id,
            "semester": teaching_graph["semester"].id,
            "managing_department": dept_a.id,
            "offering_code": "JOINT",
        },
        format="json",
    )
    assert response.status_code == 201
    offering_id = response.json()["id"]

    response = api_client.post(
        COMPONENTS_URL,
        {
            "offering": offering_id,
            "component_type": TeachingComponentType.THEORY,
            "weekly_hours": "4.00",
            "session_duration_hours": "2.00",
            "sessions_per_week": 999,
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["sessions_per_week"] == 2

    response = api_client.post(
        COMPONENT_GROUPS_URL,
        {
            "teaching_component": response.json()["id"],
            "student_group": teaching_graph["B"]["group"].id,
        },
        format="json",
    )
    assert response.status_code == 201


@pytest.mark.django_db
def test_api_rejects_invalid_types_hours_duplicates_and_tampering(api_client, teaching_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    dept_a = teaching_graph["departments"]["A"]
    course_a = teaching_graph["A"]["course"]
    offering_a = teaching_graph["A"]["offering"]

    duplicate_course = api_client.post(
        COURSES_URL,
        {"department": dept_a.id, "name": "Duplicate", "code": course_a.code},
        format="json",
    )
    assert duplicate_course.status_code == 400

    duplicate_offering = api_client.post(
        OFFERINGS_URL,
        {
            "course": course_a.id,
            "semester": teaching_graph["semester"].id,
            "managing_department": dept_a.id,
            "offering_code": offering_a.offering_code,
        },
        format="json",
    )
    assert duplicate_offering.status_code == 400

    bad_offering = api_client.post(
        OFFERINGS_URL,
        {
            "course": course_a.id,
            "semester": teaching_graph["semester"].id,
            "managing_department": teaching_graph["departments"]["B"].id,
            "offering_code": "BAD",
        },
        format="json",
    )
    assert bad_offering.status_code == 400

    for component_type in ("LECTURE", "LAB", "OTHER", "abc"):
        response = api_client.post(
            COMPONENTS_URL,
            {
                "offering": offering_a.id,
                "component_type": component_type,
                "weekly_hours": "2.00",
                "session_duration_hours": "1.00",
            },
            format="json",
        )
        assert response.status_code == 400

    for weekly_hours, duration in (
        ("0.00", "1.00"),
        ("-1.00", "1.00"),
        ("2.00", "0.00"),
        ("2.00", "-1.00"),
        ("1.00", "2.00"),
        ("3.00", "2.00"),
        ("2.50", "2.00"),
    ):
        response = api_client.post(
            COMPONENTS_URL,
            {
                "offering": offering_a.id,
                "component_type": TeachingComponentType.THEORY,
                "weekly_hours": weekly_hours,
                "session_duration_hours": duration,
            },
            format="json",
        )
        assert response.status_code == 400

    for url, payload in (
        (COURSES_URL, {"department": 999999, "name": "Bad", "code": "BAD"}),
        (
            OFFERINGS_URL,
            {
                "course": 999999,
                "semester": teaching_graph["semester"].id,
                "managing_department": dept_a.id,
            },
        ),
        (
            COMPONENTS_URL,
            {
                "offering": 999999,
                "component_type": TeachingComponentType.THEORY,
                "weekly_hours": "2.00",
                "session_duration_hours": "1.00",
            },
        ),
        (
            COMPONENT_GROUPS_URL,
            {
                "teaching_component": 999999,
                "student_group": teaching_graph["A"]["group"].id,
            },
        ),
    ):
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
def test_department_admin_own_resource_writes_and_escape_attempts(api_client, teaching_graph):
    dept_a = teaching_graph["departments"]["A"]
    dept_b = teaching_graph["departments"]["B"]
    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_a)
    authenticate(api_client, admin_a)

    create_course = api_client.post(
        COURSES_URL,
        {"department": dept_a.id, "name": "A New Course", "code": "NEW"},
        format="json",
    )
    assert create_course.status_code == 201
    course_id = create_course.json()["id"]

    assert api_client.patch(
        f"{COURSES_URL}{course_id}/",
        {"name": "A Updated Course"},
        format="json",
    ).status_code == 200

    escape_course = api_client.post(
        COURSES_URL,
        {"department": dept_b.id, "name": "B Escape", "code": "ESC"},
        format="json",
    )
    assert escape_course.status_code == 400

    move_course = api_client.patch(
        f"{COURSES_URL}{course_id}/",
        {"department": dept_b.id},
        format="json",
    )
    assert move_course.status_code == 400

    assert api_client.get(f"{COURSES_URL}{teaching_graph['B']['course'].id}/").status_code == 404

    valid_offering = api_client.post(
        OFFERINGS_URL,
        {
            "course": course_id,
            "semester": teaching_graph["semester"].id,
            "managing_department": dept_a.id,
            "offering_code": "MAIN",
        },
        format="json",
    )
    assert valid_offering.status_code == 201

    for payload in (
        {
            "course": teaching_graph["B"]["course"].id,
            "semester": teaching_graph["semester"].id,
            "managing_department": dept_a.id,
            "offering_code": "B1",
        },
        {
            "course": teaching_graph["A"]["course"].id,
            "semester": teaching_graph["semester"].id,
            "managing_department": dept_b.id,
            "offering_code": "B2",
        },
    ):
        response = api_client.post(OFFERINGS_URL, payload, format="json")
        assert response.status_code in (400, 403)

    component = api_client.post(
        COMPONENTS_URL,
        {
            "offering": valid_offering.json()["id"],
            "component_type": TeachingComponentType.THEORY,
            "weekly_hours": "2.00",
            "session_duration_hours": "2.00",
        },
        format="json",
    )
    assert component.status_code == 201

    link = api_client.post(
        COMPONENT_GROUPS_URL,
        {
            "teaching_component": component.json()["id"],
            "student_group": teaching_graph["A"]["group"].id,
        },
        format="json",
    )
    assert link.status_code == 201

    cross_group = api_client.post(
        COMPONENT_GROUPS_URL,
        {
            "teaching_component": component.json()["id"],
            "student_group": teaching_graph["B"]["group"].id,
        },
        format="json",
    )
    assert cross_group.status_code == 400

    assert api_client.post(
        COMPONENTS_URL,
        {
            "offering": teaching_graph["B"]["offering"].id,
            "component_type": TeachingComponentType.THEORY,
            "weekly_hours": "2.00",
            "session_duration_hours": "1.00",
        },
        format="json",
    ).status_code == 400

    assert api_client.patch(
        f"{COMPONENTS_URL}{teaching_graph['B']['component'].id}/",
        {"label": "Escape"},
        format="json",
    ).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("role", [UserRole.SCHEDULER, UserRole.VIEWER, UserRole.INSTRUCTOR])
def test_read_only_roles_can_read_own_records_but_cannot_write(api_client, teaching_graph, role):
    scoped_user = create_user(role, department=teaching_graph["departments"]["A"])
    authenticate(api_client, scoped_user)

    assert response_ids(api_client.get(COURSES_URL)) == {teaching_graph["A"]["course"].id}
    assert response_ids(api_client.get(OFFERINGS_URL)) == {teaching_graph["A"]["offering"].id}
    assert response_ids(api_client.get(COMPONENTS_URL)) == {teaching_graph["A"]["component"].id}
    assert response_ids(api_client.get(COMPONENT_GROUPS_URL)) == {
        TeachingComponentGroup.objects.get(
            teaching_component=teaching_graph["A"]["component"],
            student_group=teaching_graph["A"]["group"],
        ).id
    }

    assert api_client.post(
        COURSES_URL,
        {"department": teaching_graph["departments"]["A"].id, "name": "Denied", "code": "DEN"},
        format="json",
    ).status_code == 403
    assert api_client.patch(
        f"{COMPONENTS_URL}{teaching_graph['A']['component'].id}/",
        {"label": "Denied"},
        format="json",
    ).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER, UserRole.VIEWER, UserRole.INSTRUCTOR],
)
def test_departmentless_scoped_users_fail_closed(api_client, teaching_graph, role):
    scoped_user = create_user(role, department=None)
    authenticate(api_client, scoped_user)

    for url in PHASE3_URLS:
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.json() == []

    assert api_client.post(
        COURSES_URL,
        {
            "department": teaching_graph["departments"]["A"].id,
            "name": "No Department",
            "code": "NONE",
        },
        format="json",
    ).status_code == 403


@pytest.mark.django_db
def test_phase3_openapi_documents_routes_and_authentication(api_client, teaching_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    response = api_client.get("/api/schema/", {"format": "json"})

    assert response.status_code == 200
    paths = response.json()["paths"]
    for url in PHASE3_URLS:
        detail_path = f"{url}{{id}}/"
        assert "get" in paths[url]
        assert "post" in paths[url]
        assert "patch" in paths[detail_path]
        assert "delete" not in paths[detail_path]
        assert paths[url]["get"].get("security")
