"""Independent acceptance tests for Phase 3 joint-course visibility."""

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


def authenticate(api_client, user):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def create_user(role, department=None):
    return User.objects.create_user(
        username=f"{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


@pytest.fixture
def joint_graph(db):
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
        result[code] = {
            "group": StudentGroup.objects.create(
                stage=stage,
                name=f"Group {code}",
                code=f"G{code}",
            )
        }

    course = Course.objects.create(
        department=departments["A"],
        name="Joint AI",
        code="JAI",
    )
    offering = CourseOffering.objects.create(
        course=course,
        semester=semester,
        managing_department=departments["A"],
        offering_code="MAIN",
    )
    component = TeachingComponent.objects.create(
        offering=offering,
        component_type=TeachingComponentType.THEORY,
        weekly_hours="2.00",
        session_duration_hours="2.00",
    )
    result.update({"course": course, "offering": offering, "component": component})
    return result


def ids(response):
    return {item["id"] for item in response.json()}


@pytest.mark.django_db
def test_college_admin_can_establish_joint_course_across_departments(api_client, joint_graph):
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    for code in ("A", "B", "C"):
        response = api_client.post(
            COMPONENT_GROUPS_URL,
            {
                "teaching_component": joint_graph["component"].id,
                "student_group": joint_graph[code]["group"].id,
            },
            format="json",
        )
        assert response.status_code == 201


@pytest.mark.django_db
def test_joint_course_visibility_includes_participants_but_not_unrelated_department(
    api_client,
    joint_graph,
):
    TeachingComponentGroup.objects.create(
        teaching_component=joint_graph["component"],
        student_group=joint_graph["A"]["group"],
    )
    link_b = TeachingComponentGroup.objects.create(
        teaching_component=joint_graph["component"],
        student_group=joint_graph["B"]["group"],
    )
    link_c = TeachingComponentGroup.objects.create(
        teaching_component=joint_graph["component"],
        student_group=joint_graph["C"]["group"],
    )

    for code, expected_link in (("A", None), ("B", link_b), ("C", link_c)):
        scoped_user = create_user(
            UserRole.VIEWER,
            department=joint_graph["departments"][code],
        )
        authenticate(api_client, scoped_user)

        assert joint_graph["course"].id in ids(api_client.get(COURSES_URL))
        assert joint_graph["offering"].id in ids(api_client.get(OFFERINGS_URL))
        assert joint_graph["component"].id in ids(api_client.get(COMPONENTS_URL))
        group_link_ids = ids(api_client.get(COMPONENT_GROUPS_URL))
        if expected_link is not None:
            assert expected_link.id in group_link_ids
        else:
            assert group_link_ids

    unrelated = create_user(UserRole.VIEWER, department=joint_graph["departments"]["D"])
    authenticate(api_client, unrelated)
    assert joint_graph["course"].id not in ids(api_client.get(COURSES_URL))
    assert joint_graph["offering"].id not in ids(api_client.get(OFFERINGS_URL))
    assert joint_graph["component"].id not in ids(api_client.get(COMPONENTS_URL))
    assert api_client.get(f"{COURSES_URL}{joint_graph['course'].id}/").status_code == 404
    assert api_client.get(f"{OFFERINGS_URL}{joint_graph['offering'].id}/").status_code == 404
    assert api_client.get(f"{COMPONENTS_URL}{joint_graph['component'].id}/").status_code == 404


@pytest.mark.django_db
def test_participating_department_cannot_modify_joint_course(api_client, joint_graph):
    TeachingComponentGroup.objects.create(
        teaching_component=joint_graph["component"],
        student_group=joint_graph["B"]["group"],
    )
    admin_b = create_user(UserRole.DEPARTMENT_ADMIN, department=joint_graph["departments"]["B"])
    authenticate(api_client, admin_b)

    assert joint_graph["offering"].id in ids(api_client.get(OFFERINGS_URL))
    assert joint_graph["component"].id in ids(api_client.get(COMPONENTS_URL))

    assert api_client.patch(
        f"{OFFERINGS_URL}{joint_graph['offering'].id}/",
        {"offering_code": "HACK"},
        format="json",
    ).status_code == 403
    assert api_client.patch(
        f"{COMPONENTS_URL}{joint_graph['component'].id}/",
        {"label": "HACK"},
        format="json",
    ).status_code == 403

    assert api_client.post(
        COMPONENT_GROUPS_URL,
        {
            "teaching_component": joint_graph["component"].id,
            "student_group": joint_graph["C"]["group"].id,
        },
        format="json",
    ).status_code == 400
