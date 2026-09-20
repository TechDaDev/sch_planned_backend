"""Independent Phase 2 API permission and scoping tests."""

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from academics.models import (
    AcademicYear,
    College,
    Department,
    Semester,
    StudentGroup,
    StudyProgram,
    StudyStage,
    StudyType,
)
from accounts.models import User, UserRole

COLLEGES_URL = "/api/colleges/"
DEPARTMENTS_URL = "/api/departments/"
ACADEMIC_YEARS_URL = "/api/academic-years/"
SEMESTERS_URL = "/api/semesters/"
PROGRAMS_URL = "/api/programs/"
STAGES_URL = "/api/stages/"
STUDENT_GROUPS_URL = "/api/student-groups/"

ACADEMIC_COLLECTIONS = [
    COLLEGES_URL,
    DEPARTMENTS_URL,
    ACADEMIC_YEARS_URL,
    SEMESTERS_URL,
    PROGRAMS_URL,
    STAGES_URL,
    STUDENT_GROUPS_URL,
]

DEPARTMENT_SCOPED_COLLECTIONS = [
    DEPARTMENTS_URL,
    PROGRAMS_URL,
    STAGES_URL,
    STUDENT_GROUPS_URL,
]


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
def academic_graph(db):
    college = College.objects.create(name="College of AI", code="AI")
    department_a = Department.objects.create(
        name="Department A",
        code="A",
        college=college,
    )
    department_b = Department.objects.create(
        name="Department B",
        code="B",
        college=college,
    )
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    semester = Semester.objects.create(academic_year=year, number=1)
    program_a = StudyProgram.objects.create(
        department=department_a,
        name="Program A",
        code="PA",
        study_type=StudyType.UNDERGRADUATE,
    )
    program_b = StudyProgram.objects.create(
        department=department_b,
        name="Program B",
        code="PB",
        study_type=StudyType.UNDERGRADUATE,
    )
    stage_a = StudyStage.objects.create(program=program_a, number=1, name="Stage A")
    stage_b = StudyStage.objects.create(program=program_b, number=1, name="Stage B")
    group_a = StudentGroup.objects.create(
        stage=stage_a,
        name="Group A",
        code="A",
        student_count=20,
    )
    group_b = StudentGroup.objects.create(
        stage=stage_b,
        name="Group B",
        code="B",
        student_count=20,
    )
    return {
        "college": college,
        "department_a": department_a,
        "department_b": department_b,
        "year": year,
        "semester": semester,
        "program_a": program_a,
        "program_b": program_b,
        "stage_a": stage_a,
        "stage_b": stage_b,
        "group_a": group_a,
        "group_b": group_b,
    }


def ids(response):
    return {item["id"] for item in response.json()}


@pytest.mark.django_db
@pytest.mark.parametrize("url", ACADEMIC_COLLECTIONS)
def test_anonymous_users_cannot_access_academic_endpoints(api_client, url):
    response = api_client.get(url)

    assert response.status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("url", ACADEMIC_COLLECTIONS)
def test_delete_is_not_exposed(api_client, academic_graph, url):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    object_id = api_client.get(url).json()[0]["id"]

    response = api_client.delete(f"{url}{object_id}/")

    assert response.status_code == 405


@pytest.mark.django_db
def test_college_admin_and_superuser_can_manage_phase2_resources(api_client, academic_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    assert ids(api_client.get(DEPARTMENTS_URL)) == {
        academic_graph["department_a"].id,
        academic_graph["department_b"].id,
    }
    assert ids(api_client.get(PROGRAMS_URL)) == {
        academic_graph["program_a"].id,
        academic_graph["program_b"].id,
    }

    response = api_client.patch(
        f"{COLLEGES_URL}{academic_graph['college'].id}/",
        {"name": "Updated College"},
        format="json",
    )
    assert response.status_code == 200

    response = api_client.post(
        DEPARTMENTS_URL,
        {"college": academic_graph["college"].id, "name": "Department C", "code": "C"},
        format="json",
    )
    assert response.status_code == 201

    superuser = User.objects.create_superuser(
        username="operator",
        password="secret-pass-123",
        role=UserRole.VIEWER,
    )
    authenticate(api_client, superuser)
    response = api_client.patch(
        f"{ACADEMIC_YEARS_URL}{academic_graph['year'].id}/",
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_department_admin_is_scoped_for_reads_writes_and_detail_access(
    api_client,
    academic_graph,
):
    department_a = academic_graph["department_a"]
    department_b = academic_graph["department_b"]
    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=department_a)
    authenticate(api_client, admin_a)

    assert ids(api_client.get(DEPARTMENTS_URL)) == {department_a.id}
    assert ids(api_client.get(PROGRAMS_URL)) == {academic_graph["program_a"].id}
    assert ids(api_client.get(STAGES_URL)) == {academic_graph["stage_a"].id}
    assert ids(api_client.get(STUDENT_GROUPS_URL)) == {academic_graph["group_a"].id}

    for url, object_id in (
        (DEPARTMENTS_URL, department_b.id),
        (PROGRAMS_URL, academic_graph["program_b"].id),
        (STAGES_URL, academic_graph["stage_b"].id),
        (STUDENT_GROUPS_URL, academic_graph["group_b"].id),
    ):
        response = api_client.get(f"{url}{object_id}/")
        assert response.status_code == 404

    response = api_client.patch(
        f"{DEPARTMENTS_URL}{department_a.id}/",
        {"name": "Department A Updated"},
        format="json",
    )
    assert response.status_code == 200

    response = api_client.patch(
        f"{DEPARTMENTS_URL}{department_b.id}/",
        {"name": "Department B Escape"},
        format="json",
    )
    assert response.status_code == 404

    response = api_client.post(
        PROGRAMS_URL,
        {
            "department": department_a.id,
            "name": "Program A2",
            "code": "PA2",
            "study_type": StudyType.MASTER,
        },
        format="json",
    )
    assert response.status_code == 201

    for url, payload in (
        (COLLEGES_URL, {"name": "Nope", "code": "NO"}),
        (ACADEMIC_YEARS_URL, {"start_year": 2028, "end_year": 2029}),
        (SEMESTERS_URL, {"academic_year": academic_graph["year"].id, "number": 2}),
    ):
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 403


@pytest.mark.django_db
def test_department_admin_cross_department_payloads_are_rejected(
    api_client,
    academic_graph,
):
    department_a = academic_graph["department_a"]
    department_b = academic_graph["department_b"]
    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=department_a)
    authenticate(api_client, admin_a)

    response = api_client.post(
        PROGRAMS_URL,
        {
            "department": department_b.id,
            "name": "Escape Program",
            "code": "ESC",
            "study_type": StudyType.MASTER,
        },
        format="json",
    )
    assert response.status_code == 400

    response = api_client.patch(
        f"{PROGRAMS_URL}{academic_graph['program_a'].id}/",
        {"department": department_b.id},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.post(
        STAGES_URL,
        {"program": academic_graph["program_b"].id, "number": 2, "name": "Escape"},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.patch(
        f"{STAGES_URL}{academic_graph['stage_a'].id}/",
        {"program": academic_graph["program_b"].id},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.post(
        STUDENT_GROUPS_URL,
        {
            "stage": academic_graph["stage_b"].id,
            "name": "Escape Group",
            "code": "ESC",
            "student_count": 1,
        },
        format="json",
    )
    assert response.status_code == 400

    response = api_client.patch(
        f"{STUDENT_GROUPS_URL}{academic_graph['group_a'].id}/",
        {"stage": academic_graph["stage_b"].id},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.patch(
        f"{STUDENT_GROUPS_URL}{academic_graph['group_a'].id}/",
        {"parent_group": academic_graph["group_b"].id},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [
        UserRole.DEPARTMENT_ADMIN,
        UserRole.SCHEDULER,
        UserRole.VIEWER,
        UserRole.INSTRUCTOR,
    ],
)
def test_departmentless_scoped_users_fail_closed(api_client, academic_graph, role):
    scoped_user = create_user(role, department=None)
    authenticate(api_client, scoped_user)

    for url in DEPARTMENT_SCOPED_COLLECTIONS:
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.json() == []

    response = api_client.post(
        PROGRAMS_URL,
        {
            "department": academic_graph["department_a"].id,
            "name": "No Department",
            "code": "NONE",
            "study_type": StudyType.MASTER,
        },
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("role", [UserRole.SCHEDULER, UserRole.VIEWER, UserRole.INSTRUCTOR])
def test_read_only_department_roles_can_read_own_scope_but_not_write(
    api_client,
    academic_graph,
    role,
):
    scoped_user = create_user(role, department=academic_graph["department_a"])
    authenticate(api_client, scoped_user)

    assert ids(api_client.get(DEPARTMENTS_URL)) == {academic_graph["department_a"].id}
    assert ids(api_client.get(PROGRAMS_URL)) == {academic_graph["program_a"].id}
    assert ids(api_client.get(STAGES_URL)) == {academic_graph["stage_a"].id}
    assert ids(api_client.get(STUDENT_GROUPS_URL)) == {academic_graph["group_a"].id}

    response = api_client.post(
        PROGRAMS_URL,
        {
            "department": academic_graph["department_a"].id,
            "name": f"{role} Program",
            "code": role[:4],
            "study_type": StudyType.MASTER,
        },
        format="json",
    )
    assert response.status_code == 403

    response = api_client.patch(
        f"{PROGRAMS_URL}{academic_graph['program_a'].id}/",
        {"name": "Blocked"},
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_college_wide_read_objects_are_readable_but_not_writable_by_scoped_users(
    api_client,
    academic_graph,
):
    scoped_user = create_user(UserRole.VIEWER, department=academic_graph["department_a"])
    authenticate(api_client, scoped_user)

    assert api_client.get(COLLEGES_URL).status_code == 200
    assert api_client.get(ACADEMIC_YEARS_URL).status_code == 200
    assert api_client.get(SEMESTERS_URL).status_code == 200

    for url, object_id in (
        (COLLEGES_URL, academic_graph["college"].id),
        (ACADEMIC_YEARS_URL, academic_graph["year"].id),
        (SEMESTERS_URL, academic_graph["semester"].id),
    ):
        response = api_client.patch(f"{url}{object_id}/", {"is_active": False}, format="json")
        assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url", "payload"),
    [
        (DEPARTMENTS_URL, {"college": 999999, "name": "Bad", "code": "BAD"}),
        (
            PROGRAMS_URL,
            {
                "department": 999999,
                "name": "Bad",
                "code": "BAD",
                "study_type": StudyType.MASTER,
            },
        ),
        (STAGES_URL, {"program": 999999, "number": 1, "name": "Bad"}),
        (
            STUDENT_GROUPS_URL,
            {"stage": 999999, "name": "Bad", "code": "BAD", "student_count": 1},
        ),
        (
            STUDENT_GROUPS_URL,
            {
                "stage": 999999,
                "name": "Bad",
                "code": "BAD2",
                "student_count": 1,
                "parent_group": 999999,
            },
        ),
    ],
)
def test_malformed_foreign_keys_return_clean_400(api_client, academic_graph, url, payload):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_phase2_openapi_documents_routes_and_authentication(api_client, academic_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    response = api_client.get("/api/schema/", {"format": "json"})

    assert response.status_code == 200
    paths = response.json()["paths"]
    for url in ACADEMIC_COLLECTIONS:
        path = url[:-1] + "/"
        detail_path = path + "{id}/"
        assert "get" in paths[path]
        assert "post" in paths[path]
        assert "delete" not in paths[detail_path]
        assert paths[path]["get"].get("security")
