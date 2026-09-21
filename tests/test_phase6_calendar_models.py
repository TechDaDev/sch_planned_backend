"""Independent acceptance tests for Phase 6 calendar/time models."""

from datetime import date, time

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from academics.models import (
    AcademicYear,
    College,
    Department,
    Semester,
    StudyProgram,
    StudyStage,
    StudyType,
    StudentGroup,
    Weekday,
)
from resources.models import InstructorProfile, Room, RoomType
from scheduling.models import (
    BreakPeriod,
    CalendarException,
    ExceptionScope,
    ExceptionType,
    TimeSlot,
    WorkingDay,
)


@pytest.fixture
def calendar_graph(db):
    college = College.objects.create(name="College", code="COL")
    department_a = Department.objects.create(name="Department A", code="A", college=college)
    department_b = Department.objects.create(name="Department B", code="B", college=college)
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    semester = Semester.objects.create(
        academic_year=year,
        number=1,
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 31),
    )
    program = StudyProgram.objects.create(
        department=department_a,
        name="Program A",
        code="PA",
        study_type=StudyType.UNDERGRADUATE,
    )
    stage = StudyStage.objects.create(program=program, number=1, name="Stage 1")
    group = StudentGroup.objects.create(
        stage=stage, name="Group A", code="GA", student_count=20
    )
    instructor = InstructorProfile.objects.create(
        primary_department=department_a,
        full_name="Ada Lovelace",
        staff_code="I-A",
    )
    room_type = RoomType.objects.create(name="Lecture", code="LECT")
    room = Room.objects.create(
        owner_department=department_a,
        name="Room A",
        code="RA",
        room_type=room_type,
        capacity=30,
    )
    return {
        "semester": semester,
        "department_a": department_a,
        "department_b": department_b,
        "group": group,
        "instructor": instructor,
        "room": room,
    }


def test_working_day_constraints_and_active_children_stay_in_bounds(calendar_graph):
    semester = calendar_graph["semester"]
    day = WorkingDay.objects.create(
        semester=semester,
        day_of_week=Weekday.MONDAY,
        start_time=time(8),
        end_time=time(16),
    )
    TimeSlot.objects.create(
        working_day=day,
        sequence=1,
        start_time=time(9),
        end_time=time(10),
    )
    BreakPeriod.objects.create(
        working_day=day,
        name="Lunch",
        start_time=time(12),
        end_time=time(13),
    )

    assert str(day)
    with pytest.raises(ValidationError):
        WorkingDay(
            semester=semester,
            day_of_week=Weekday.TUESDAY,
            start_time=time(16),
            end_time=time(8),
        ).full_clean()
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            WorkingDay.objects.create(
                semester=semester,
                day_of_week=Weekday.MONDAY,
                start_time=time(8),
                end_time=time(16),
            )

    day.start_time = time(9, 30)
    with pytest.raises(ValidationError, match="Existing active"):
        day.full_clean()
    day.time_slots.update(is_active=False)
    day.start_time = time(10)
    day.full_clean()


def test_grid_window_sequence_and_bidirectional_overlap_rules(calendar_graph):
    day = WorkingDay.objects.create(
        semester=calendar_graph["semester"],
        day_of_week=Weekday.MONDAY,
        start_time=time(8),
        end_time=time(16),
    )
    slot = TimeSlot.objects.create(
        working_day=day,
        sequence=1,
        start_time=time(8),
        end_time=time(9),
    )
    assert slot.duration_minutes == 60

    for invalid in (
        TimeSlot(working_day=day, sequence=0, start_time=time(10), end_time=time(11)),
        TimeSlot(working_day=day, sequence=2, start_time=time(7), end_time=time(8)),
        TimeSlot(working_day=day, sequence=2, start_time=time(11), end_time=time(10)),
        BreakPeriod(working_day=day, name="Bad", start_time=time(15), end_time=time(17)),
    ):
        with pytest.raises(ValidationError):
            invalid.full_clean()

    with pytest.raises(ValidationError, match="overlaps"):
        BreakPeriod(
            working_day=day, name="Overlap slot", start_time=time(8, 30), end_time=time(9, 30)
        ).full_clean()

    lunch = BreakPeriod.objects.create(
        working_day=day, name="Lunch", start_time=time(12), end_time=time(13)
    )
    with pytest.raises(ValidationError, match="overlaps"):
        TimeSlot(
            working_day=day, sequence=2, start_time=time(12, 30), end_time=time(13, 30)
        ).full_clean()
    with pytest.raises(ValidationError, match="overlaps"):
        BreakPeriod(
            working_day=day, name="Second", start_time=time(12, 30), end_time=time(13, 30)
        ).full_clean()

    TimeSlot(
        working_day=day, sequence=2, start_time=time(9), end_time=time(10)
    ).full_clean()
    TimeSlot(
        working_day=day, sequence=3, start_time=time(12, 30), end_time=time(13, 30), is_active=False
    ).full_clean()
    assert lunch.name == "Lunch"


def test_calendar_exception_scope_time_type_and_semester_rules(calendar_graph):
    graph = calendar_graph
    valid = CalendarException(
        semester=graph["semester"],
        date=date(2026, 10, 1),
        exception_type=ExceptionType.HOLIDAY,
        scope_type=ExceptionScope.COLLEGE,
        title="Holiday",
    )
    valid.full_clean()
    assert valid.is_full_day is True
    assert valid.scope_target_field is None

    partial = CalendarException(
        semester=graph["semester"],
        date=date(2026, 10, 1),
        exception_type=ExceptionType.EVENT,
        scope_type=ExceptionScope.DEPARTMENT,
        department=graph["department_a"],
        title="Event",
        start_time=time(9),
        end_time=time(10, 30),
    )
    partial.full_clean()
    assert partial.is_full_day is False
    assert partial.owning_department_id == graph["department_a"].id

    invalid = (
        CalendarException(
            semester=graph["semester"], date=date(2026, 10, 1),
            exception_type=ExceptionType.HOLIDAY, scope_type=ExceptionScope.COLLEGE,
            department=graph["department_a"], title="Extra target",
        ),
        CalendarException(
            semester=graph["semester"], date=date(2026, 10, 1),
            exception_type=ExceptionType.HOLIDAY, scope_type=ExceptionScope.ROOM,
            title="Missing target",
        ),
        CalendarException(
            semester=graph["semester"], date=date(2026, 10, 1),
            exception_type=ExceptionType.HOLIDAY, scope_type=ExceptionScope.DEPARTMENT,
            department=graph["department_a"], title="Half", start_time=time(9),
        ),
        CalendarException(
            semester=graph["semester"], date=date(2026, 10, 1),
            exception_type=ExceptionType.INSTRUCTOR_ABSENCE, scope_type=ExceptionScope.ROOM,
            room=graph["room"], title="Wrong scope",
        ),
        CalendarException(
            semester=graph["semester"], date=date(2026, 8, 31),
            exception_type=ExceptionType.HOLIDAY, scope_type=ExceptionScope.COLLEGE,
            title="Outside semester",
        ),
    )
    for exception in invalid:
        with pytest.raises(ValidationError):
            exception.full_clean()

    CalendarException(
        semester=graph["semester"], date=date(2026, 10, 1),
        exception_type=ExceptionType.INSTRUCTOR_ABSENCE,
        scope_type=ExceptionScope.INSTRUCTOR, instructor=graph["instructor"],
        title="Leave",
    ).full_clean()
    CalendarException(
        semester=graph["semester"], date=date(2026, 10, 1),
        exception_type=ExceptionType.ROOM_CLOSURE,
        scope_type=ExceptionScope.ROOM, room=graph["room"], title="Repair",
    ).full_clean()
