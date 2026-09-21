"""Independent acceptance tests for Phase 5 room models."""

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
    StudentGroup,
    StudyProgram,
    StudyStage,
    StudyType,
    TeachingComponent,
    TeachingComponentGroup,
    TeachingComponentType,
    Weekday,
)
from resources.models import (
    Room,
    RoomAvailability,
    RoomCapability,
    RoomCapabilityAssignment,
    RoomDepartmentAccess,
    RoomType,
    SharingScope,
    TeachingAssignment,
    TeachingComponentCapabilityRequirement,
    TeachingComponentRoomRequirement,
)


def make_department(code):
    college, _ = College.objects.get_or_create(code="COL", defaults={"name": "College"})
    return Department.objects.create(name=f"Department {code}", code=code, college=college)


def make_semester():
    year, _ = AcademicYear.objects.get_or_create(start_year=2026, end_year=2027)
    semester, _ = Semester.objects.get_or_create(academic_year=year, number=1)
    return semester


def make_room_type(code="LECTURE"):
    return RoomType.objects.create(name=f"{code.title()} Room", code=code)


def make_capability(code="PROJECTOR"):
    return RoomCapability.objects.create(name=code.title(), code=code)


def make_room(department, **kwargs):
    defaults = {
        "owner_department": department,
        "name": f"Room {department.code}",
        "code": f"R-{department.code}-{Room.objects.count() + 1}",
        "room_type": make_room_type(f"TYPE-{Room.objects.count() + 1}"),
        "capacity": 40,
    }
    defaults.update(kwargs)
    return Room.objects.create(**defaults)


def make_component(department, *, group_counts=(25,), suffix="1"):
    semester = make_semester()
    program = StudyProgram.objects.create(
        department=department,
        name=f"Program {department.code} {suffix}",
        code=f"P{department.code}{suffix}",
        study_type=StudyType.UNDERGRADUATE,
    )
    stage = StudyStage.objects.create(program=program, number=1, name="Stage 1")
    course = Course.objects.create(
        department=department,
        name=f"Course {department.code} {suffix}",
        code=f"C{department.code}{suffix}",
    )
    offering = CourseOffering.objects.create(
        course=course,
        semester=semester,
        managing_department=department,
        offering_code=f"MAIN{suffix}",
    )
    component = TeachingComponent.objects.create(
        offering=offering,
        component_type=TeachingComponentType.THEORY,
        weekly_hours="2.00",
        session_duration_hours="2.00",
    )
    for index, count in enumerate(group_counts, start=1):
        group = StudentGroup.objects.create(
            stage=stage,
            name=f"Group {suffix}-{index}",
            code=f"G{department.code}{suffix}{index}",
            student_count=count,
        )
        TeachingComponentGroup.objects.create(
            teaching_component=component,
            student_group=group,
        )
    return component


@pytest.mark.django_db
def test_room_type_capability_and_room_core_fields_validate():
    department = make_department("A")
    room_type = make_room_type()
    capability = make_capability()
    room = make_room(
        department,
        room_type=room_type,
        name="AI Lab",
        code="AI-LAB-1",
        capacity=30,
    )

    assert str(room_type) == "Lecture Room (LECTURE)"
    assert str(capability) == "Projector (PROJECTOR)"
    assert str(room) == "AI Lab (AI-LAB-1)"
    assert room.sharing_scope == SharingScope.PRIVATE
    assert room.is_active is True

    with pytest.raises(IntegrityError), transaction.atomic():
        make_room_type("LECTURE")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_capability("PROJECTOR")
    with pytest.raises(ValidationError):
        Room(owner_department=department, room_type=room_type, name="Bad", code="BAD", capacity=0).full_clean()


@pytest.mark.django_db
def test_room_sharing_scope_and_access_semantics_fail_closed():
    department_a = make_department("A")
    department_b = make_department("B")
    inactive_department = make_department("X")
    inactive_department.is_active = False
    inactive_department.save(update_fields=["is_active"])
    room = make_room(department_a)

    assert room.can_be_used_by_department(department_a) is True
    assert room.can_be_used_by_department(department_b) is False
    assert room.can_be_used_by_department(None) is False

    access = RoomDepartmentAccess.objects.create(
        room=room,
        department=department_b,
        is_active=True,
    )
    assert room.can_be_used_by_department(department_b) is False

    room.sharing_scope = SharingScope.SELECTED_DEPARTMENTS
    room.save(update_fields=["sharing_scope"])
    assert room.can_be_used_by_department(department_b) is True

    access.is_active = False
    access.save(update_fields=["is_active"])
    assert room.can_be_used_by_department(department_b) is False

    room.sharing_scope = SharingScope.COLLEGE_WIDE
    room.save(update_fields=["sharing_scope"])
    assert room.can_be_used_by_department(department_b) is True
    assert room.can_be_used_by_department(inactive_department) is False

    room.room_type.is_active = False
    room.room_type.save(update_fields=["is_active"])
    assert room.can_be_used_by_department(department_a) is False

    with pytest.raises(ValidationError):
        RoomDepartmentAccess(room=room, department=department_a).full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        RoomDepartmentAccess.objects.create(room=room, department=department_b)
        RoomDepartmentAccess.objects.create(room=room, department=department_b)


@pytest.mark.django_db
def test_room_availability_weekday_time_and_overlap_rules():
    department = make_department("A")
    semester = make_semester()
    room = make_room(department)

    slot = RoomAvailability.objects.create(
        room=room,
        semester=semester,
        day_of_week=Weekday.SUNDAY,
        start_time=time(8, 0),
        end_time=time(10, 0),
    )
    slot.full_clean()

    adjacent = RoomAvailability(
        room=room,
        semester=semester,
        day_of_week=Weekday.SUNDAY,
        start_time=time(10, 0),
        end_time=time(12, 0),
    )
    adjacent.full_clean()

    with pytest.raises(ValidationError):
        RoomAvailability(
            room=room,
            semester=semester,
            day_of_week=Weekday.SUNDAY,
            start_time=time(9, 0),
            end_time=time(11, 0),
        ).full_clean()

    inactive_overlap = RoomAvailability(
        room=room,
        semester=semester,
        day_of_week=Weekday.SUNDAY,
        start_time=time(9, 0),
        end_time=time(11, 0),
        is_active=False,
    )
    inactive_overlap.full_clean()

    with pytest.raises(ValidationError):
        RoomAvailability(
            room=room,
            semester=semester,
            day_of_week=Weekday.MONDAY,
            start_time=time(11, 0),
            end_time=time(9, 0),
        ).full_clean()
    with pytest.raises(ValidationError):
        RoomAvailability(
            room=room,
            semester=semester,
            day_of_week=5,
            start_time=time(8, 0),
            end_time=time(9, 0),
        ).full_clean()


@pytest.mark.django_db
def test_room_requirements_derive_capacity_and_suitability_reasons():
    department = make_department("A")
    room_type = make_room_type("LAB")
    other_type = make_room_type("LECTURE")
    projector = make_capability("PROJECTOR")
    computers = make_capability("COMPUTERS")
    component = make_component(department, group_counts=(25, 30))
    requirement = TeachingComponentRoomRequirement.objects.create(
        teaching_component=component,
        required_room_type=room_type,
        minimum_capacity=60,
    )
    TeachingComponentCapabilityRequirement.objects.create(
        room_requirement=requirement,
        capability=projector,
    )
    TeachingComponentCapabilityRequirement.objects.create(
        room_requirement=requirement,
        capability=computers,
    )

    assert component.expected_student_count == 55
    assert requirement.expected_student_count == 55
    assert requirement.effective_minimum_capacity == 60

    room = make_room(department, room_type=room_type, capacity=60)
    RoomCapabilityAssignment.objects.create(room=room, capability=projector)
    assert room.meets_requirement(requirement) is False
    assert "Computers" in " ".join(room.evaluate_suitability(requirement))

    RoomCapabilityAssignment.objects.create(room=room, capability=computers)
    assert room.meets_requirement(requirement) is True
    assert room.is_suitable_for_teaching_component(component) is True

    room.room_type = other_type
    room.capacity = 59
    room.save(update_fields=["room_type", "capacity"])
    reasons = " ".join(room.evaluate_suitability(requirement))
    assert "room type" in reasons
    assert "capacity" in reasons


@pytest.mark.django_db
def test_phase5_keeps_requirements_separate_from_actual_room_assignment():
    forbidden = {"room", "classroom", "laboratory", "room_assignment"}

    assert forbidden.isdisjoint({field.name for field in TeachingComponent._meta.fields})
    assert forbidden.isdisjoint({field.name for field in CourseOffering._meta.fields})
    assert forbidden.isdisjoint({field.name for field in TeachingAssignment._meta.fields})
