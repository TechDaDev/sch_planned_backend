"""Independent acceptance tests for Phase 2 academic structure."""

from datetime import date

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
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


def authenticate(api_client, user):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def user(role=UserRole.COLLEGE_ADMIN, department=None, **kwargs):
    username = kwargs.pop("username", f"{role.lower()}-{User.objects.count()}")
    return User.objects.create_user(
        username=username,
        password="secret-pass-123",
        role=role,
        department=department,
        **kwargs,
    )


def structure():
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
    Semester.objects.create(academic_year=year, number=1)
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
    stage_a = StudyStage.objects.create(program=program_a, number=1, name="Stage 1")
    stage_b = StudyStage.objects.create(program=program_b, number=1, name="Stage 1")
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
        "program_a": program_a,
        "program_b": program_b,
        "stage_a": stage_a,
        "stage_b": stage_b,
        "group_a": group_a,
        "group_b": group_b,
    }


@pytest.mark.django_db
def test_baghdad_timezone_is_configured_at_settings_and_runtime():
    assert settings.TIME_ZONE == "Asia/Baghdad"
    assert settings.USE_TZ is True
    assert timezone.get_default_timezone_name() == "Asia/Baghdad"


@pytest.mark.django_db
def test_college_model_fields_constraints_timestamps_and_string():
    college = College.objects.create(name="College of AI", code="AI")

    assert college.name == "College of AI"
    assert college.code == "AI"
    assert college.is_active is True
    assert college.created_at is not None
    assert college.updated_at is not None
    assert str(college) == "College of AI (AI)"

    blank_code = College(name="Missing Code", code="")
    with pytest.raises(ValidationError):
        blank_code.full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        College.objects.create(name="Duplicate", code="AI")


@pytest.mark.django_db
def test_department_college_is_nullable_for_legacy_rows_and_deletion_sets_null():
    college = College.objects.create(name="College of AI", code="AI")
    legacy_department = Department.objects.create(name="Legacy", code="LEG")
    department = Department.objects.create(name="Department A", code="A", college=college)

    assert legacy_department.college is None

    college.delete()
    department.refresh_from_db()
    assert department.college is None


@pytest.mark.django_db
def test_academic_year_model_and_api_validation(api_client):
    admin = user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)

    response = api_client.post(
        ACADEMIC_YEARS_URL,
        {"start_year": 2026, "end_year": 2027},
        format="json",
    )
    assert response.status_code == 201

    for end_year in (2026, 2028):
        response = api_client.post(
            ACADEMIC_YEARS_URL,
            {"start_year": 2026, "end_year": end_year},
            format="json",
        )
        assert response.status_code == 400

    response = api_client.post(
        ACADEMIC_YEARS_URL,
        {"start_year": 2027, "end_year": 2026},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.post(
        ACADEMIC_YEARS_URL,
        {"start_year": 2026, "end_year": 2027},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_semester_model_and_api_validation(api_client):
    admin = user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)

    response = api_client.post(
        SEMESTERS_URL,
        {
            "academic_year": year.id,
            "number": 1,
            "start_date": "2026-10-01",
            "end_date": "2027-01-15",
        },
        format="json",
    )
    assert response.status_code == 201

    response = api_client.post(
        SEMESTERS_URL,
        {"academic_year": year.id, "number": 1},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.post(
        SEMESTERS_URL,
        {"academic_year": year.id, "number": 3},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.post(
        SEMESTERS_URL,
        {
            "academic_year": year.id,
            "number": 2,
            "start_date": "2027-03-01",
            "end_date": "2027-02-01",
        },
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_program_stage_and_group_model_constraints_and_api_validation(api_client):
    admin = user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    data = structure()
    department_a = data["department_a"]
    department_b = data["department_b"]
    program_a = data["program_a"]
    stage_a = data["stage_a"]

    for study_type in ("DIPLOMA", "OTHER", "abc"):
        response = api_client.post(
            PROGRAMS_URL,
            {
                "department": department_a.id,
                "name": f"Invalid {study_type}",
                "code": f"I{study_type[:2]}",
                "study_type": study_type,
            },
            format="json",
        )
        assert response.status_code == 400

    response = api_client.post(
        PROGRAMS_URL,
        {
            "department": department_a.id,
            "name": "Duplicate Program",
            "code": program_a.code,
            "study_type": StudyType.MASTER,
        },
        format="json",
    )
    assert response.status_code == 400

    response = api_client.post(
        PROGRAMS_URL,
        {
            "department": department_b.id,
            "name": "Same Code Different Department",
            "code": program_a.code,
            "study_type": StudyType.MASTER,
        },
        format="json",
    )
    assert response.status_code == 201

    response = api_client.post(
        STAGES_URL,
        {"program": program_a.id, "number": 5, "name": "Stage 5"},
        format="json",
    )
    assert response.status_code == 201

    for number in (0, -1):
        response = api_client.post(
            STAGES_URL,
            {"program": program_a.id, "number": number, "name": "Invalid Stage"},
            format="json",
        )
        assert response.status_code == 400

    response = api_client.post(
        STAGES_URL,
        {"program": program_a.id, "number": stage_a.number, "name": "Duplicate Stage"},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.post(
        STUDENT_GROUPS_URL,
        {"stage": stage_a.id, "name": "Zero", "code": "Z", "student_count": 0},
        format="json",
    )
    assert response.status_code == 201

    response = api_client.post(
        STUDENT_GROUPS_URL,
        {"stage": stage_a.id, "name": "Negative", "code": "N", "student_count": -1},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.post(
        STUDENT_GROUPS_URL,
        {"stage": stage_a.id, "name": "Duplicate", "code": "A", "student_count": 1},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_student_subgroup_validation_rejects_self_parent_cross_stage_and_cycles(api_client):
    admin = user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    data = structure()
    stage_a = data["stage_a"]
    stage_b = data["stage_b"]

    group = StudentGroup.objects.create(stage=stage_a, name="Base", code="BASE")
    child = StudentGroup.objects.create(
        stage=stage_a,
        name="Child",
        code="CHILD",
        parent_group=group,
    )
    grandchild = StudentGroup.objects.create(
        stage=stage_a,
        name="Grandchild",
        code="GRAND",
        parent_group=child,
    )
    other_stage_parent = StudentGroup.objects.create(
        stage=stage_b,
        name="Other",
        code="OTHER",
    )

    response = api_client.patch(
        f"{STUDENT_GROUPS_URL}{group.id}/",
        {"parent_group": group.id},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.patch(
        f"{STUDENT_GROUPS_URL}{group.id}/",
        {"parent_group": other_stage_parent.id},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.patch(
        f"{STUDENT_GROUPS_URL}{group.id}/",
        {"parent_group": child.id},
        format="json",
    )
    assert response.status_code == 400

    response = api_client.patch(
        f"{STUDENT_GROUPS_URL}{group.id}/",
        {"parent_group": grandchild.id},
        format="json",
    )
    assert response.status_code == 400
