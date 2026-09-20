"""Independent acceptance tests for Phase 4 instructor models."""

from datetime import time

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
    TeachingComponent,
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


def make_department(code):
    college, _ = College.objects.get_or_create(code="COL", defaults={"name": "College"})
    return Department.objects.create(name=f"Department {code}", code=code, college=college)


def make_semester():
    year, _ = AcademicYear.objects.get_or_create(start_year=2026, end_year=2027)
    semester, _ = Semester.objects.get_or_create(academic_year=year, number=1)
    return semester


def make_component(
    department,
    *,
    suffix=None,
    course_active=True,
    offering_active=True,
    component_active=True,
):
    suffix = suffix or f"{Course.objects.filter(department=department).count() + 1}"
    semester = make_semester()
    course = Course.objects.create(
        department=department,
        name=f"{department.code} Course {suffix}",
        code=f"C{department.code}{suffix}",
        is_active=course_active,
    )
    offering = CourseOffering.objects.create(
        course=course,
        semester=semester,
        managing_department=department,
        offering_code=f"MAIN{suffix}",
        is_active=offering_active,
    )
    return TeachingComponent.objects.create(
        offering=offering,
        component_type=TeachingComponentType.THEORY,
        weekly_hours="2.00",
        session_duration_hours="2.00",
        is_active=component_active,
    )


def make_instructor(department, **kwargs):
    defaults = {
        "primary_department": department,
        "full_name": f"Instructor {department.code}",
    }
    defaults.update(kwargs)
    return InstructorProfile.objects.create(**defaults)


@pytest.mark.django_db
def test_instructor_profile_fields_optional_user_staff_code_and_unique_staff_code():
    department = make_department("A")
    instructor = make_instructor(
        department,
        staff_code="STAFF-1",
        academic_title="Assistant Lecturer",
        max_weekly_hours="12.00",
        max_daily_hours="4.00",
    )

    assert instructor.user is None
    assert instructor.staff_code == "STAFF-1"
    assert instructor.sharing_scope == SharingScope.PRIVATE
    assert instructor.is_active is True
    assert instructor.created_at is not None
    assert instructor.updated_at is not None
    assert str(instructor) == instructor.full_name

    blank_staff = make_instructor(department, full_name="Blank Staff", staff_code="")
    blank_staff.refresh_from_db()
    assert blank_staff.staff_code is None

    with pytest.raises(ValidationError):
        InstructorProfile(primary_department=department, full_name="").full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_instructor(department, full_name="Duplicate", staff_code="STAFF-1")


@pytest.mark.django_db
def test_user_link_validation_accepts_only_matching_instructor_accounts():
    department_a = make_department("A")
    department_b = make_department("B")
    valid_user = User.objects.create_user(
        username="valid-instructor",
        password="secret-pass-123",
        role=UserRole.INSTRUCTOR,
        department=department_a,
    )

    InstructorProfile(
        user=valid_user,
        primary_department=department_a,
        full_name="Valid Instructor",
    ).full_clean()

    for role in (
        UserRole.COLLEGE_ADMIN,
        UserRole.DEPARTMENT_ADMIN,
        UserRole.SCHEDULER,
        UserRole.VIEWER,
    ):
        linked_user = User.objects.create_user(
            username=f"bad-{role}",
            password="secret-pass-123",
            role=role,
            department=department_a,
        )
        with pytest.raises(ValidationError):
            InstructorProfile(
                user=linked_user,
                primary_department=department_a,
                full_name=f"Bad {role}",
            ).full_clean()

    foreign_user = User.objects.create_user(
        username="foreign-instructor",
        password="secret-pass-123",
        role=UserRole.INSTRUCTOR,
        department=department_a,
    )
    with pytest.raises(ValidationError):
        InstructorProfile(
            user=foreign_user,
            primary_department=department_b,
            full_name="Foreign Department",
        ).full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("weekly", "daily", "valid"),
    [
        ("12.00", "4.00", True),
        (None, None, True),
        ("0.00", "4.00", False),
        ("-1.00", "4.00", False),
        ("12.00", "0.00", False),
        ("12.00", "-1.00", False),
        ("4.00", "5.00", False),
    ],
)
def test_workload_limits_validate_cleanly(weekly, daily, valid):
    instructor = InstructorProfile(
        primary_department=make_department("A"),
        full_name="Workload",
        max_weekly_hours=weekly,
        max_daily_hours=daily,
    )

    if valid:
        instructor.full_clean()
    else:
        with pytest.raises(ValidationError):
            instructor.full_clean()


@pytest.mark.django_db
def test_sharing_scope_and_department_access_semantics():
    department_a = make_department("A")
    department_b = make_department("B")
    inactive_department = make_department("X")
    inactive_department.is_active = False
    inactive_department.save(update_fields=["is_active"])
    instructor = make_instructor(department_a)

    assert instructor.can_teach_in_department(department_a) is True
    assert instructor.can_teach_in_department(department_b) is False

    access = InstructorDepartmentAccess.objects.create(
        instructor=instructor,
        department=department_b,
        is_active=True,
    )
    assert instructor.can_teach_in_department(department_b) is False

    instructor.sharing_scope = SharingScope.SELECTED_DEPARTMENTS
    instructor.save(update_fields=["sharing_scope"])
    assert instructor.can_teach_in_department(department_b) is True

    access.is_active = False
    access.save(update_fields=["is_active"])
    assert instructor.can_teach_in_department(department_b) is False

    instructor.sharing_scope = SharingScope.COLLEGE_WIDE
    instructor.save(update_fields=["sharing_scope"])
    assert instructor.can_teach_in_department(department_b) is True
    assert instructor.can_teach_in_department(inactive_department) is False

    instructor.is_active = False
    instructor.save(update_fields=["is_active"])
    assert instructor.can_teach_in_department(department_a) is False


@pytest.mark.django_db
def test_instructor_department_access_constraints():
    department_a = make_department("A")
    department_b = make_department("B")
    instructor = make_instructor(department_a, sharing_scope=SharingScope.SELECTED_DEPARTMENTS)

    with pytest.raises(ValidationError):
        InstructorDepartmentAccess(instructor=instructor, department=department_a).full_clean()

    InstructorDepartmentAccess.objects.create(instructor=instructor, department=department_b)
    with pytest.raises(IntegrityError), transaction.atomic():
        InstructorDepartmentAccess.objects.create(instructor=instructor, department=department_b)


@pytest.mark.django_db
def test_teaching_assignment_constraints_and_eligibility():
    department_a = make_department("A")
    department_b = make_department("B")
    component_a = make_component(department_a)
    component_b = make_component(department_b)
    inactive_component = make_component(department_a, component_active=False)
    inactive_offering_component = make_component(department_a, offering_active=False)
    inactive_course_component = make_component(department_a, course_active=False)
    instructor_a = make_instructor(department_a)
    assistant = make_instructor(department_a, full_name="Assistant")

    TeachingAssignment.objects.create(
        teaching_component=component_a,
        instructor=instructor_a,
        assignment_role=AssignmentRole.PRIMARY,
    )

    with pytest.raises(ValidationError):
        TeachingAssignment(
            teaching_component=component_a,
            instructor=assistant,
            assignment_role=AssignmentRole.PRIMARY,
        ).full_clean()

    TeachingAssignment.objects.create(
        teaching_component=component_a,
        instructor=assistant,
        assignment_role=AssignmentRole.ASSISTANT,
    )

    old_primary = TeachingAssignment.objects.get(
        teaching_component=component_a,
        instructor=instructor_a,
    )
    old_primary.is_active = False
    old_primary.save(update_fields=["is_active"])
    replacement_primary = make_instructor(department_a, full_name="Replacement Primary")
    TeachingAssignment(
        teaching_component=component_a,
        instructor=replacement_primary,
        assignment_role=AssignmentRole.PRIMARY,
    ).full_clean()

    with pytest.raises(ValidationError):
        TeachingAssignment(
            teaching_component=component_b,
            instructor=instructor_a,
            assignment_role=AssignmentRole.PRIMARY,
        ).full_clean()

    inactive_instructor = make_instructor(department_a, full_name="Inactive", is_active=False)
    for bad_component, bad_instructor in (
        (component_a, inactive_instructor),
        (inactive_component, instructor_a),
        (inactive_offering_component, instructor_a),
        (inactive_course_component, instructor_a),
    ):
        with pytest.raises(ValidationError):
            TeachingAssignment(
                teaching_component=bad_component,
                instructor=bad_instructor,
                assignment_role=AssignmentRole.ASSISTANT,
            ).full_clean()

    instructor_a.sharing_scope = SharingScope.SELECTED_DEPARTMENTS
    instructor_a.save(update_fields=["sharing_scope"])
    access = InstructorDepartmentAccess.objects.create(
        instructor=instructor_a,
        department=department_b,
        is_active=True,
    )
    TeachingAssignment(
        teaching_component=component_b,
        instructor=instructor_a,
        assignment_role=AssignmentRole.PRIMARY,
    ).full_clean()
    access.is_active = False
    access.save(update_fields=["is_active"])
    with pytest.raises(ValidationError):
        TeachingAssignment(
            teaching_component=component_b,
            instructor=instructor_a,
            assignment_role=AssignmentRole.ASSISTANT,
        ).full_clean()


@pytest.mark.django_db
def test_no_direct_user_room_or_lab_coupling_on_teaching_assignment_or_component():
    assignment_fields = {field.name for field in TeachingAssignment._meta.fields}
    component_fields = {field.name for field in TeachingComponent._meta.fields}

    assert "user" not in assignment_fields
    assert "user" not in component_fields
    assert {"room", "lab", "laboratory"}.isdisjoint(assignment_fields)
    assert {"room", "lab", "laboratory"}.isdisjoint(component_fields)
