"""Independent acceptance tests for Phase 4 availability and preferences."""

from datetime import time

import pytest
from django.core.exceptions import ValidationError

from academics.models import AcademicYear, College, Department, Semester, Weekday
from resources.models import (
    InstructorAvailability,
    InstructorPreference,
    InstructorProfile,
    PreferenceType,
)


def make_department():
    college = College.objects.create(name="College", code="COL")
    return Department.objects.create(name="Department A", code="A", college=college)


def make_semester():
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    return Semester.objects.create(academic_year=year, number=1)


def make_instructor():
    return InstructorProfile.objects.create(
        primary_department=make_department(),
        full_name="Instructor A",
    )


@pytest.mark.django_db
def test_availability_weekdays_time_order_and_overlap_rules():
    instructor = make_instructor()
    semester = make_semester()

    InstructorAvailability(
        instructor=instructor,
        semester=semester,
        day_of_week=Weekday.SUNDAY,
        start_time=time(8, 0),
        end_time=time(10, 0),
    ).full_clean()

    for bad_day in (-1, 5, 6):
        with pytest.raises(ValidationError):
            InstructorAvailability(
                instructor=instructor,
                semester=semester,
                day_of_week=bad_day,
                start_time=time(8, 0),
                end_time=time(10, 0),
            ).full_clean()

    for start, end in ((time(10, 0), time(10, 0)), (time(12, 0), time(10, 0))):
        with pytest.raises(ValidationError):
            InstructorAvailability(
                instructor=instructor,
                semester=semester,
                day_of_week=Weekday.MONDAY,
                start_time=start,
                end_time=end,
            ).full_clean()

    InstructorAvailability.objects.create(
        instructor=instructor,
        semester=semester,
        day_of_week=Weekday.TUESDAY,
        start_time=time(8, 0),
        end_time=time(11, 0),
    )
    InstructorAvailability(
        instructor=instructor,
        semester=semester,
        day_of_week=Weekday.TUESDAY,
        start_time=time(11, 0),
        end_time=time(12, 0),
    ).full_clean()
    with pytest.raises(ValidationError):
        InstructorAvailability(
            instructor=instructor,
            semester=semester,
            day_of_week=Weekday.TUESDAY,
            start_time=time(10, 0),
            end_time=time(12, 0),
        ).full_clean()
    InstructorAvailability(
        instructor=instructor,
        semester=semester,
        day_of_week=Weekday.TUESDAY,
        start_time=time(10, 0),
        end_time=time(12, 0),
        is_active=False,
    ).full_clean()


@pytest.mark.django_db
def test_preferences_type_time_order_and_overlap_rules():
    instructor = make_instructor()
    semester = make_semester()

    for preference_type in (PreferenceType.PREFERRED, PreferenceType.AVOID):
        InstructorPreference(
            instructor=instructor,
            semester=semester,
            day_of_week=Weekday.SUNDAY,
            start_time=time(8, 0),
            end_time=time(9, 0),
            preference_type=preference_type,
        ).full_clean()

    with pytest.raises(ValidationError):
        InstructorPreference(
            instructor=instructor,
            semester=semester,
            day_of_week=Weekday.SUNDAY,
            start_time=time(8, 0),
            end_time=time(9, 0),
            preference_type="HARD_BLOCK",
        ).full_clean()

    with pytest.raises(ValidationError):
        InstructorPreference(
            instructor=instructor,
            semester=semester,
            day_of_week=Weekday.MONDAY,
            start_time=time(10, 0),
            end_time=time(10, 0),
            preference_type=PreferenceType.AVOID,
        ).full_clean()

    InstructorPreference.objects.create(
        instructor=instructor,
        semester=semester,
        day_of_week=Weekday.WEDNESDAY,
        start_time=time(8, 0),
        end_time=time(11, 0),
        preference_type=PreferenceType.PREFERRED,
    )
    with pytest.raises(ValidationError):
        InstructorPreference(
            instructor=instructor,
            semester=semester,
            day_of_week=Weekday.WEDNESDAY,
            start_time=time(10, 0),
            end_time=time(12, 0),
            preference_type=PreferenceType.AVOID,
        ).full_clean()
    InstructorPreference(
        instructor=instructor,
        semester=semester,
        day_of_week=Weekday.WEDNESDAY,
        start_time=time(10, 0),
        end_time=time(12, 0),
        preference_type=PreferenceType.AVOID,
        is_active=False,
    ).full_clean()
