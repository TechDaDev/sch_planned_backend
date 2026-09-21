"""Independent acceptance tests for Phase 6 calendar/time API and access."""

from datetime import date, time

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from academics.models import (
    AcademicYear, College, Department, Semester, StudyProgram, StudyStage,
    StudyType, StudentGroup, Weekday,
)
from accounts.models import User, UserRole
from resources.models import (
    InstructorDepartmentAccess, InstructorProfile, Room, RoomDepartmentAccess,
    RoomType, SharingScope,
)
from scheduling.models import (
    BreakPeriod, CalendarException, ExceptionScope, ExceptionType, TimeSlot,
    WorkingDay,
)

WORKING_DAYS_URL = "/api/working-days/"
TIME_SLOTS_URL = "/api/time-slots/"
BREAKS_URL = "/api/break-periods/"
EXCEPTIONS_URL = "/api/calendar-exceptions/"
PHASE6_URLS = (WORKING_DAYS_URL, TIME_SLOTS_URL, BREAKS_URL, EXCEPTIONS_URL)


def authenticate(api_client, user):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def create_user(role, department=None):
    return User.objects.create_user(
        username=f"{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


def response_ids(response):
    return {item["id"] for item in response.json()}


@pytest.fixture
def phase6_graph(db):
    college = College.objects.create(name="College", code="COL")
    departments = {
        code: Department.objects.create(name=f"Department {code}", code=code, college=college)
        for code in ("A", "B", "C")
    }
    year = AcademicYear.objects.create(start_year=2026, end_year=2027)
    semester = Semester.objects.create(
        academic_year=year, number=1, start_date=date(2026, 9, 1), end_date=date(2027, 1, 31)
    )
    program = StudyProgram.objects.create(
        department=departments["A"], name="Program A", code="PA", study_type=StudyType.UNDERGRADUATE
    )
    stage = StudyStage.objects.create(program=program, number=1, name="Stage 1")
    group = StudentGroup.objects.create(stage=stage, name="Group A", code="GA", student_count=20)
    instructor = InstructorProfile.objects.create(
        primary_department=departments["A"], full_name="Ada Lovelace", staff_code="I-A",
        sharing_scope=SharingScope.SELECTED_DEPARTMENTS,
    )
    InstructorDepartmentAccess.objects.create(instructor=instructor, department=departments["B"])
    room_type = RoomType.objects.create(name="Lecture", code="LECT")
    room = Room.objects.create(
        owner_department=departments["A"], name="Room A", code="RA", room_type=room_type,
        capacity=30, sharing_scope=SharingScope.SELECTED_DEPARTMENTS,
    )
    RoomDepartmentAccess.objects.create(room=room, department=departments["B"])
    day = WorkingDay.objects.create(
        semester=semester, day_of_week=Weekday.MONDAY, start_time=time(8), end_time=time(16)
    )
    slot = TimeSlot.objects.create(
        working_day=day, sequence=1, label="One", start_time=time(8), end_time=time(9)
    )
    break_period = BreakPeriod.objects.create(
        working_day=day, name="Lunch", start_time=time(12), end_time=time(13)
    )
    exceptions = {
        "college": CalendarException.objects.create(
            semester=semester, date=date(2026, 10, 1), exception_type=ExceptionType.HOLIDAY,
            scope_type=ExceptionScope.COLLEGE, title="College holiday",
        ),
        "department": CalendarException.objects.create(
            semester=semester, date=date(2026, 10, 2), exception_type=ExceptionType.EVENT,
            scope_type=ExceptionScope.DEPARTMENT, department=departments["A"], title="Department event",
        ),
        "instructor": CalendarException.objects.create(
            semester=semester, date=date(2026, 10, 3), exception_type=ExceptionType.INSTRUCTOR_ABSENCE,
            scope_type=ExceptionScope.INSTRUCTOR, instructor=instructor, title="Instructor leave",
        ),
        "room": CalendarException.objects.create(
            semester=semester, date=date(2026, 10, 4), exception_type=ExceptionType.ROOM_CLOSURE,
            scope_type=ExceptionScope.ROOM, room=room, title="Room repair",
        ),
        "group": CalendarException.objects.create(
            semester=semester, date=date(2026, 10, 5), exception_type=ExceptionType.EVENT,
            scope_type=ExceptionScope.STUDENT_GROUP, student_group=group, title="Group event",
        ),
    }
    return {"departments": departments, "semester": semester, "group": group, "instructor": instructor,
            "room": room, "day": day, "slot": slot, "break": break_period, "exceptions": exceptions}


@pytest.mark.django_db
@pytest.mark.parametrize("url", PHASE6_URLS)
def test_phase6_endpoints_require_authentication_and_disable_delete(api_client, phase6_graph, url):
    assert api_client.get(url).status_code == 401
    assert api_client.post(url, {}, format="json").status_code == 401
    admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, admin)
    object_id = api_client.get(url).json()[0]["id"]
    assert api_client.delete(f"{url}{object_id}/").status_code == 405


@pytest.mark.django_db
def test_grid_is_college_admin_writable_and_returns_read_shape(api_client, phase6_graph):
    dept_admin = create_user(UserRole.DEPARTMENT_ADMIN, phase6_graph["departments"]["A"])
    authenticate(api_client, dept_admin)
    assert api_client.get(WORKING_DAYS_URL).status_code == 200
    assert api_client.post(
        WORKING_DAYS_URL,
        {"semester": phase6_graph["semester"].id, "day_of_week": Weekday.TUESDAY,
         "start_time": "08:00", "end_time": "16:00"}, format="json",
    ).status_code == 403

    college_admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, college_admin)
    created = api_client.post(
        WORKING_DAYS_URL,
        {"semester": phase6_graph["semester"].id, "day_of_week": Weekday.TUESDAY,
         "start_time": "08:00", "end_time": "16:00"}, format="json",
    )
    assert created.status_code == 201
    assert created.json()["semester"]["id"] == phase6_graph["semester"].id
    assert created.json()["day_of_week_code"] == "TUESDAY"
    created_slot = api_client.post(
        TIME_SLOTS_URL,
        {"working_day": created.json()["id"], "sequence": 1, "start_time": "08:00", "end_time": "09:30"},
        format="json",
    )
    assert created_slot.status_code == 201
    assert created_slot.json()["duration_minutes"] == 90
    assert api_client.post(
        BREAKS_URL,
        {"working_day": created.json()["id"], "name": "Overlap", "start_time": "09:00", "end_time": "10:00"},
        format="json",
    ).status_code == 400


@pytest.mark.django_db
def test_exception_visibility_scopes_and_departmentless_fail_closed(api_client, phase6_graph):
    graph = phase6_graph
    admin_b = create_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["B"])
    authenticate(api_client, admin_b)
    visible_b = response_ids(api_client.get(EXCEPTIONS_URL))
    assert visible_b == {
        graph["exceptions"]["college"].id,
        graph["exceptions"]["instructor"].id,
        graph["exceptions"]["room"].id,
    }

    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"])
    authenticate(api_client, admin_a)
    assert response_ids(api_client.get(EXCEPTIONS_URL)) == {item.id for item in graph["exceptions"].values()}

    departmentless = create_user(UserRole.SCHEDULER)
    authenticate(api_client, departmentless)
    assert response_ids(api_client.get(EXCEPTIONS_URL)) == {
        graph["exceptions"]["college"].id,
    }


@pytest.mark.django_db
def test_exception_write_scope_and_validation_are_enforced(api_client, phase6_graph):
    graph = phase6_graph
    admin_a = create_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"])
    authenticate(api_client, admin_a)
    created = api_client.post(
        EXCEPTIONS_URL,
        {"semester": graph["semester"].id, "date": "2026-10-10", "exception_type": ExceptionType.EVENT,
         "scope_type": ExceptionScope.DEPARTMENT, "department": graph["departments"]["A"].id,
         "title": "Own event", "start_time": "09:00", "end_time": "10:00"},
        format="json",
    )
    assert created.status_code == 201
    assert created.json()["target"]["id"] == graph["departments"]["A"].id
    assert created.json()["is_full_day"] is False

    for payload in (
        {"semester": graph["semester"].id, "date": "2026-10-10", "exception_type": ExceptionType.HOLIDAY,
         "scope_type": ExceptionScope.COLLEGE, "title": "Too broad"},
        {"semester": graph["semester"].id, "date": "2026-10-10", "exception_type": ExceptionType.EVENT,
         "scope_type": ExceptionScope.DEPARTMENT, "department": graph["departments"]["B"].id, "title": "Foreign"},
        {"semester": graph["semester"].id, "date": "2026-10-10", "exception_type": ExceptionType.ROOM_CLOSURE,
         "scope_type": ExceptionScope.INSTRUCTOR, "instructor": graph["instructor"].id, "title": "Wrong type"},
    ):
        assert api_client.post(EXCEPTIONS_URL, payload, format="json").status_code == 400

    foreign = graph["exceptions"]["department"]
    assert api_client.patch(
        f"{EXCEPTIONS_URL}{foreign.id}/", {"title": "Changed"}, format="json"
    ).status_code == 200
    assert api_client.patch(
        f"{EXCEPTIONS_URL}{graph['exceptions']['college'].id}/", {"title": "Nope"}, format="json"
    ).status_code == 403


@pytest.mark.django_db
def test_exception_filters_read_only_roles_and_schema(api_client, phase6_graph):
    graph = phase6_graph
    viewer = create_user(UserRole.VIEWER, graph["departments"]["A"])
    authenticate(api_client, viewer)
    assert api_client.post(EXCEPTIONS_URL, {}, format="json").status_code == 403
    filtered = api_client.get(EXCEPTIONS_URL, {"scope_type": ExceptionScope.ROOM})
    assert response_ids(filtered) == {graph["exceptions"]["room"].id}
    assert api_client.get(EXCEPTIONS_URL, {"is_active": "not-bool"}).status_code == 400

    college_admin = create_user(UserRole.COLLEGE_ADMIN)
    authenticate(api_client, college_admin)
    response = api_client.get("/api/schema/", {"format": "json"})
    assert response.status_code == 200
    paths = response.json()["paths"]
    for url in PHASE6_URLS:
        assert "get" in paths[url]
        assert "post" in paths[url]
        assert "delete" not in paths[f"{url}{{id}}/"]
