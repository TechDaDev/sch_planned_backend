"""Independent acceptance tests for Phase 3 course and teaching models."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

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


def make_department(code):
    college, _ = College.objects.get_or_create(code="AI", defaults={"name": "AI"})
    return Department.objects.create(name=f"Department {code}", code=code, college=college)


def make_semester():
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    return Semester.objects.create(academic_year=year, number=1)


def make_course(department, code="ML301"):
    return Course.objects.create(
        department=department,
        name=f"{department.code} Machine Learning",
        code=code,
        description="Catalog-only course",
    )


def make_group(department, code="A", parent_group=None):
    program = StudyProgram.objects.create(
        department=department,
        name=f"Program {department.code} {code}",
        code=f"P{department.code}{code}",
        study_type=StudyType.UNDERGRADUATE,
    )
    stage = StudyStage.objects.create(program=program, number=1, name="Stage 1")
    return StudentGroup.objects.create(
        stage=stage,
        name=f"Group {code}",
        code=code,
        student_count=10,
        parent_group=parent_group,
    )


def make_offering(course, semester=None, offering_code="MAIN"):
    return CourseOffering.objects.create(
        course=course,
        semester=semester or make_semester(),
        managing_department=course.department,
        offering_code=offering_code,
    )


def make_component(offering, component_type=TeachingComponentType.THEORY):
    return TeachingComponent.objects.create(
        offering=offering,
        component_type=component_type,
        label=component_type,
        weekly_hours="2.00",
        session_duration_hours="2.00",
    )


@pytest.mark.django_db
def test_course_model_is_catalog_only_and_unique_per_department():
    department_a = make_department("A")
    department_b = make_department("B")
    course = make_course(department_a)

    assert str(course) == "A Machine Learning (ML301)"
    assert course.description == "Catalog-only course"
    assert course.created_at is not None
    assert course.updated_at is not None

    forbidden_fields = {
        "instructor",
        "professor",
        "teacher",
        "lecturer",
        "room",
        "lab",
        "student_group",
        "weekly_hours",
        "session_duration_hours",
        "academic_year",
        "semester",
    }
    assert forbidden_fields.isdisjoint({field.name for field in Course._meta.fields})

    with pytest.raises(IntegrityError), transaction.atomic():
        make_course(department_a)

    assert make_course(department_b).pk is not None


@pytest.mark.django_db
def test_course_offering_model_validation_and_uniqueness():
    department_a = make_department("A")
    department_b = make_department("B")
    semester = make_semester()
    course_a = make_course(department_a)
    offering = make_offering(course_a, semester=semester)

    assert offering.total_weekly_hours == 0
    assert not any(field.name == "academic_year" for field in CourseOffering._meta.fields)

    invalid = CourseOffering(
        course=course_a,
        semester=semester,
        managing_department=department_b,
        offering_code="BAD",
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_offering(course_a, semester=semester)

    assert make_offering(course_a, semester=semester, offering_code="EVENING").pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("weekly_hours", "duration", "sessions"),
    [
        ("2.00", "2.00", 1),
        ("4.00", "2.00", 2),
        ("3.00", "1.50", 2),
        ("4.50", "1.50", 3),
    ],
)
def test_teaching_component_valid_hours_derive_sessions(
    weekly_hours,
    duration,
    sessions,
):
    component = TeachingComponent(
        offering=make_offering(make_course(make_department("A"))),
        component_type=TeachingComponentType.THEORY,
        weekly_hours=weekly_hours,
        session_duration_hours=duration,
    )

    component.full_clean()

    assert component.sessions_per_week == sessions


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("weekly_hours", "duration"),
    [
        ("0.00", "1.00"),
        ("-1.00", "1.00"),
        ("2.00", "0.00"),
        ("2.00", "-1.00"),
        ("1.00", "2.00"),
        ("3.00", "2.00"),
        ("2.50", "2.00"),
    ],
)
def test_teaching_component_invalid_hours_are_rejected_cleanly(weekly_hours, duration):
    component = TeachingComponent(
        offering=make_offering(make_course(make_department("A"))),
        component_type=TeachingComponentType.THEORY,
        weekly_hours=weekly_hours,
        session_duration_hours=duration,
    )

    with pytest.raises(ValidationError):
        component.full_clean()


@pytest.mark.django_db
def test_total_weekly_hours_counts_only_active_components():
    offering = make_offering(make_course(make_department("A")))
    TeachingComponent.objects.create(
        offering=offering,
        component_type=TeachingComponentType.THEORY,
        weekly_hours="2.00",
        session_duration_hours="2.00",
    )
    TeachingComponent.objects.create(
        offering=offering,
        component_type=TeachingComponentType.PRACTICAL,
        weekly_hours="2.00",
        session_duration_hours="1.00",
    )
    TeachingComponent.objects.create(
        offering=offering,
        component_type=TeachingComponentType.PRACTICAL,
        weekly_hours="3.00",
        session_duration_hours="1.00",
        is_active=False,
    )

    assert offering.total_weekly_hours == 4


@pytest.mark.django_db
def test_component_group_uniqueness_and_overlap_rules():
    department = make_department("A")
    offering = make_offering(make_course(department))
    component = make_component(offering)
    group_a = make_group(department, "A")
    group_b = make_group(department, "B")
    subgroup_a1 = StudentGroup.objects.create(
        stage=group_a.stage,
        name="A1",
        code="A1",
        parent_group=group_a,
    )
    subgroup_a2 = StudentGroup.objects.create(
        stage=group_a.stage,
        name="A2",
        code="A2",
        parent_group=group_a,
    )
    subgroup_a1a = StudentGroup.objects.create(
        stage=group_a.stage,
        name="A1a",
        code="A1a",
        parent_group=subgroup_a1,
    )

    TeachingComponentGroup.objects.create(teaching_component=component, student_group=group_a)
    with pytest.raises(ValidationError):
        TeachingComponentGroup(
            teaching_component=component,
            student_group=subgroup_a1,
        ).full_clean()
    with pytest.raises(ValidationError):
        TeachingComponentGroup(
            teaching_component=component,
            student_group=subgroup_a1a,
        ).full_clean()

    sibling_component = make_component(offering, TeachingComponentType.PRACTICAL)
    TeachingComponentGroup.objects.create(
        teaching_component=sibling_component,
        student_group=subgroup_a1,
    )
    assert TeachingComponentGroup.objects.create(
        teaching_component=sibling_component,
        student_group=subgroup_a2,
    ).pk

    combined_component = TeachingComponent.objects.create(
        offering=offering,
        component_type=TeachingComponentType.THEORY,
        label="Combined",
        weekly_hours="2.00",
        session_duration_hours="2.00",
    )
    assert TeachingComponentGroup.objects.create(
        teaching_component=combined_component,
        student_group=group_a,
    ).pk
    assert TeachingComponentGroup.objects.create(
        teaching_component=combined_component,
        student_group=group_b,
    ).pk
