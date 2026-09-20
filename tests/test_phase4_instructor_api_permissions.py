"""Independent acceptance tests for Phase 4 instructor API permissions."""

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
    AssignmentRole,
    InstructorAvailability,
    InstructorDepartmentAccess,
    InstructorPreference,
    InstructorProfile,
    PreferenceType,
    SharingScope,
    TeachingAssignment,
)

INSTRUCTORS_URL = "/api/instructors/"
ACCESS_URL = "/api/instructor-department-access/"
AVAILABILITY_URL = "/api/instructor-availability/"
PREFERENCES_URL = "/api/instructor-preferences/"
ASSIGNMENTS_URL = "/api/teaching-assignments/"
MY_ASSIGNMENTS_URL = "/api/me/teaching-assignments/"
PHASE4_URLS = [INSTRUCTORS_URL, ACCESS_URL, AVAILABILITY_URL, PREFERENCES_URL, ASSIGNMENTS_URL]


def authenticate(api_client, user):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def create_user(role, department=None, username=None):
    return User.objects.create_user(
        username=username or f"{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


@pytest.fixture
def phase4_graph(db):
    college = College.objects.create(name="College", code="COL")
    departments = {
        code: Department.objects.create(name=f"Department {code}", code=code, college=college)
        for code in ("A", "B", "C", "D")
    }
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    semester = Semester.objects.create(academic_year=year, number=1)
    result = {"departments": departments, "semester": semester}

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
        instructor = InstructorProfile.objects.create(
            primary_department=department,
            full_name=f"Instructor {code}",
            staff_code=f"I{code}",
        )
        InstructorAvailability.objects.create(
            instructor=instructor,
            semester=semester,
            day_of_week=Weekday.SUNDAY,
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        InstructorPreference.objects.create(
            instructor=instructor,
            semester=semester,
            day_of_week=Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(10, 0),
            preference_type=PreferenceType.PREFERRED,
        )
        result[code] = {
            "group": group,
            "course": course,
            "offering": offering,
            "component": component,
            "instructor": instructor,
        }
    return result


def ids(response):
    return {item["id"] for item in response.json()}


@pytest.mark.django_db
@pytest.mark.parametrize("url", PHASE4_URLS)
def test_phase4_endpoints_require_authentication_and_disable_delete(
    api_client,
    phase4_graph,
    url,
):
    assert api_client.get(url).status_code == 401
    assert api_client.post(url, {}, format="json").status_code == 401

    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    if url == ACCESS_URL:
        InstructorDepartmentAccess.objects.create(
            instructor=phase4_graph["A"]["instructor"],
            department=phase4_graph["departments"]["B"],
        )
    elif url == ASSIGNMENTS_URL:
        TeachingAssignment.objects.create(
            teaching_component=phase4_graph["A"]["component"],
            instructor=phase4_graph["A"]["instructor"],
            assignment_role=AssignmentRole.PRIMARY,
        )
    object_id = api_client.get(url).json()[0]["id"]
    assert api_client.delete(f"{url}{object_id}/").status_code == 405


@pytest.mark.django_db
def test_department_admin_owns_instructor_profile_and_child_resources(
    api_client,
    phase4_graph,
):
    dept_a = phase4_graph["departments"]["A"]
    dept_b = phase4_graph["departments"]["B"]
    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_a)
    authenticate(api_client, admin_a)

    created = api_client.post(
        INSTRUCTORS_URL,
        {
            "primary_department": dept_a.id,
            "full_name": "New Instructor A",
            "staff_code": "NEW-A",
            "max_weekly_hours": "12.00",
            "max_daily_hours": "4.00",
        },
        format="json",
    )
    assert created.status_code == 201
    instructor_id = created.json()["id"]

    assert api_client.patch(
        f"{INSTRUCTORS_URL}{instructor_id}/",
        {"sharing_scope": SharingScope.SELECTED_DEPARTMENTS},
        format="json",
    ).status_code == 200

    response = api_client.post(
        INSTRUCTORS_URL,
        {"primary_department": dept_b.id, "full_name": "Bad B", "staff_code": "BAD-B"},
        format="json",
    )
    assert response.status_code in (400, 403)

    linked_user = create_user(UserRole.INSTRUCTOR, department=dept_a, username="linked-a")
    role_tamper = api_client.post(
        INSTRUCTORS_URL,
        {
            "primary_department": dept_a.id,
            "full_name": "Linked Instructor",
            "user": linked_user.id,
            "role": UserRole.COLLEGE_ADMIN,
            "password": "new-password",
            "department": dept_b.id,
        },
        format="json",
    )
    assert role_tamper.status_code == 201
    linked_user.refresh_from_db()
    assert linked_user.role == UserRole.INSTRUCTOR
    assert linked_user.department_id == dept_a.id
    assert linked_user.check_password("secret-pass-123")

    assert api_client.patch(
        f"{INSTRUCTORS_URL}{instructor_id}/",
        {"primary_department": dept_b.id},
        format="json",
    ).status_code == 400

    assert api_client.patch(
        f"{INSTRUCTORS_URL}{phase4_graph['B']['instructor'].id}/",
        {"full_name": "Hack"},
        format="json",
    ).status_code == 404

    assert api_client.post(
        AVAILABILITY_URL,
        {
            "instructor": instructor_id,
            "semester": phase4_graph["semester"].id,
            "day_of_week": Weekday.TUESDAY,
            "start_time": "08:00",
            "end_time": "10:00",
        },
        format="json",
    ).status_code == 201

    assert api_client.post(
        PREFERENCES_URL,
        {
            "instructor": instructor_id,
            "semester": phase4_graph["semester"].id,
            "day_of_week": Weekday.WEDNESDAY,
            "start_time": "08:00",
            "end_time": "10:00",
            "preference_type": PreferenceType.AVOID,
        },
        format="json",
    ).status_code == 201

    assert api_client.post(
        AVAILABILITY_URL,
        {
            "instructor": phase4_graph["B"]["instructor"].id,
            "semester": phase4_graph["semester"].id,
            "day_of_week": Weekday.THURSDAY,
            "start_time": "08:00",
            "end_time": "10:00",
        },
        format="json",
    ).status_code == 400


@pytest.mark.django_db
def test_sharing_grant_security_and_consumer_read_only_behavior(api_client, phase4_graph):
    dept_a = phase4_graph["departments"]["A"]
    dept_b = phase4_graph["departments"]["B"]
    instructor_a = phase4_graph["A"]["instructor"]
    instructor_a.sharing_scope = SharingScope.SELECTED_DEPARTMENTS
    instructor_a.save(update_fields=["sharing_scope"])

    admin_b = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_b)
    authenticate(api_client, admin_b)
    self_grant = api_client.post(
        ACCESS_URL,
        {"instructor": instructor_a.id, "department": dept_b.id},
        format="json",
    )
    assert self_grant.status_code == 400

    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_a)
    authenticate(api_client, admin_a)
    grant = api_client.post(
        ACCESS_URL,
        {"instructor": instructor_a.id, "department": dept_b.id},
        format="json",
    )
    assert grant.status_code == 201

    authenticate(api_client, admin_b)
    assert instructor_a.id in ids(api_client.get(INSTRUCTORS_URL))
    assert InstructorAvailability.objects.get(instructor=instructor_a).id in ids(
        api_client.get(AVAILABILITY_URL)
    )
    assert InstructorPreference.objects.get(instructor=instructor_a).id in ids(
        api_client.get(PREFERENCES_URL)
    )

    assert api_client.patch(
        f"{INSTRUCTORS_URL}{instructor_a.id}/",
        {"full_name": "Consumer Edit"},
        format="json",
    ).status_code == 403
    assert api_client.patch(
        f"{ACCESS_URL}{grant.json()['id']}/",
        {"is_active": False},
        format="json",
    ).status_code == 403

    assignment = api_client.post(
        ASSIGNMENTS_URL,
        {
            "teaching_component": phase4_graph["B"]["component"].id,
            "instructor": instructor_a.id,
            "assignment_role": AssignmentRole.PRIMARY,
        },
        format="json",
    )
    assert assignment.status_code == 201

    authenticate(api_client, admin_a)
    deactivated = api_client.patch(
        f"{ACCESS_URL}{grant.json()['id']}/",
        {"is_active": False},
        format="json",
    )
    assert deactivated.status_code == 200

    authenticate(api_client, admin_b)
    rejected = api_client.post(
        ASSIGNMENTS_URL,
        {
            "teaching_component": phase4_graph["B"]["component"].id,
            "instructor": instructor_a.id,
            "assignment_role": AssignmentRole.ASSISTANT,
        },
        format="json",
    )
    assert rejected.status_code == 400


@pytest.mark.django_db
def test_assignment_eligibility_and_write_ownership(api_client, phase4_graph):
    dept_a = phase4_graph["departments"]["A"]
    dept_b = phase4_graph["departments"]["B"]
    instructor_a = phase4_graph["A"]["instructor"]
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    private_cross_dept = api_client.post(
        ASSIGNMENTS_URL,
        {
            "teaching_component": phase4_graph["B"]["component"].id,
            "instructor": instructor_a.id,
            "assignment_role": AssignmentRole.PRIMARY,
        },
        format="json",
    )
    assert private_cross_dept.status_code == 400

    instructor_a.sharing_scope = SharingScope.COLLEGE_WIDE
    instructor_a.save(update_fields=["sharing_scope"])
    college_wide = api_client.post(
        ASSIGNMENTS_URL,
        {
            "teaching_component": phase4_graph["B"]["component"].id,
            "instructor": instructor_a.id,
            "assignment_role": AssignmentRole.PRIMARY,
        },
        format="json",
    )
    assert college_wide.status_code == 201

    admin_b = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_b)
    authenticate(api_client, admin_b)
    assert api_client.patch(
        f"{ASSIGNMENTS_URL}{college_wide.json()['id']}/",
        {"assignment_role": AssignmentRole.ASSISTANT},
        format="json",
    ).status_code == 200

    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, department=dept_a)
    authenticate(api_client, admin_a)
    assert api_client.patch(
        f"{ASSIGNMENTS_URL}{college_wide.json()['id']}/",
        {"assignment_role": AssignmentRole.PRIMARY},
        format="json",
    ).status_code in (403, 404)


@pytest.mark.django_db
def test_joint_course_assignment_visibility_without_availability_privacy_leak(
    api_client,
    phase4_graph,
):
    dept_a = phase4_graph["departments"]["A"]
    dept_b = phase4_graph["departments"]["B"]
    instructor_a = phase4_graph["A"]["instructor"]
    TeachingComponentGroup.objects.create(
        teaching_component=phase4_graph["A"]["component"],
        student_group=phase4_graph["B"]["group"],
    )
    assignment = TeachingAssignment.objects.create(
        teaching_component=phase4_graph["A"]["component"],
        instructor=instructor_a,
        assignment_role=AssignmentRole.PRIMARY,
    )

    viewer_b = create_user(UserRole.VIEWER, department=dept_b)
    authenticate(api_client, viewer_b)

    assert assignment.id in ids(api_client.get(ASSIGNMENTS_URL))
    assert instructor_a.id in ids(api_client.get(INSTRUCTORS_URL))
    assert InstructorAvailability.objects.get(instructor=instructor_a).id not in ids(
        api_client.get(AVAILABILITY_URL)
    )
    assert InstructorPreference.objects.get(instructor=instructor_a).id not in ids(
        api_client.get(PREFERENCES_URL)
    )

    assert api_client.post(
        ASSIGNMENTS_URL,
        {
            "teaching_component": phase4_graph["B"]["component"].id,
            "instructor": instructor_a.id,
            "assignment_role": AssignmentRole.ASSISTANT,
        },
        format="json",
    ).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("role", [UserRole.SCHEDULER, UserRole.VIEWER, UserRole.INSTRUCTOR])
def test_read_only_roles_can_read_visible_resources_but_not_write(
    api_client,
    phase4_graph,
    role,
):
    scoped_user = create_user(role, department=phase4_graph["departments"]["A"])
    authenticate(api_client, scoped_user)

    assert phase4_graph["A"]["instructor"].id in ids(api_client.get(INSTRUCTORS_URL))
    assert InstructorAvailability.objects.get(instructor=phase4_graph["A"]["instructor"]).id in ids(
        api_client.get(AVAILABILITY_URL)
    )

    assert api_client.post(
        INSTRUCTORS_URL,
        {
            "primary_department": phase4_graph["departments"]["A"].id,
            "full_name": "Denied",
        },
        format="json",
    ).status_code == 403
    assert api_client.patch(
        f"{INSTRUCTORS_URL}{phase4_graph['A']['instructor'].id}/",
        {"full_name": "Denied"},
        format="json",
    ).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER, UserRole.VIEWER, UserRole.INSTRUCTOR],
)
def test_departmentless_scoped_users_fail_closed(api_client, phase4_graph, role):
    scoped_user = create_user(role, department=None)
    authenticate(api_client, scoped_user)

    for url in PHASE4_URLS:
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.django_db
def test_my_teaching_assignments_endpoint(api_client, phase4_graph):
    instructor_user = create_user(
        UserRole.INSTRUCTOR,
        department=phase4_graph["departments"]["A"],
        username="teacher-a",
    )
    profile = phase4_graph["A"]["instructor"]
    profile.user = instructor_user
    profile.save(update_fields=["user"])
    own_assignment = TeachingAssignment.objects.create(
        teaching_component=phase4_graph["A"]["component"],
        instructor=profile,
        assignment_role=AssignmentRole.PRIMARY,
    )
    other_assignment = TeachingAssignment.objects.create(
        teaching_component=phase4_graph["B"]["component"],
        instructor=phase4_graph["B"]["instructor"],
        assignment_role=AssignmentRole.PRIMARY,
    )

    assert api_client.get(MY_ASSIGNMENTS_URL).status_code == 401
    authenticate(api_client, instructor_user)
    response = api_client.get(MY_ASSIGNMENTS_URL)
    assert response.status_code == 200
    assert ids(response) == {own_assignment.id}

    unlinked = create_user(UserRole.INSTRUCTOR, department=phase4_graph["departments"]["A"])
    authenticate(api_client, unlinked)
    response = api_client.get(MY_ASSIGNMENTS_URL)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.django_db
def test_payload_tampering_returns_controlled_errors(api_client, phase4_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    for url, payload in (
        (INSTRUCTORS_URL, {"primary_department": 999999, "full_name": "Bad"}),
        (ACCESS_URL, {"instructor": 999999, "department": phase4_graph["departments"]["A"].id}),
        (
            AVAILABILITY_URL,
            {
                "instructor": phase4_graph["A"]["instructor"].id,
                "semester": 999999,
                "day_of_week": Weekday.SUNDAY,
                "start_time": "08:00",
                "end_time": "10:00",
            },
        ),
        (
            PREFERENCES_URL,
            {
                "instructor": phase4_graph["A"]["instructor"].id,
                "semester": phase4_graph["semester"].id,
                "day_of_week": 999,
                "start_time": "08:00",
                "end_time": "10:00",
                "preference_type": PreferenceType.AVOID,
            },
        ),
        (
            ASSIGNMENTS_URL,
            {
                "teaching_component": 999999,
                "instructor": phase4_graph["A"]["instructor"].id,
                "assignment_role": AssignmentRole.PRIMARY,
            },
        ),
    ):
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
def test_phase4_openapi_documents_routes(api_client, phase4_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    response = api_client.get("/api/schema/", {"format": "json"})

    assert response.status_code == 200
    paths = response.json()["paths"]
    for url in (*PHASE4_URLS, MY_ASSIGNMENTS_URL):
        assert "get" in paths[url]
        assert paths[url]["get"].get("security")
    for url in PHASE4_URLS:
        assert "post" in paths[url]
        assert "delete" not in paths[f"{url}{{id}}/"]
