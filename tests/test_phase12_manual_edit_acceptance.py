"""Independent acceptance coverage for Phase 12 manual schedule editing."""

from datetime import time

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User, UserRole
from resources.models import InstructorAvailability, RoomAvailability
from scheduling.models import (
    ScheduleEntry,
    ScheduleEntryTimeSlot,
    ScheduleVersion,
    ScheduleVersionSource,
    TimeSlot,
)
from tests.test_phase7_validator_acceptance import ready_graph as phase7_ready_graph


DRAFT_URL = "/api/schedules/generate-department-draft/"


def authenticate(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")


def make_user(role, department=None):
    return User.objects.create_user(
        username=f"phase12-{role.lower()}-{User.objects.count()}",
        password="secret-pass-123",
        role=role,
        department=department,
    )


@pytest.fixture
def ready_graph(db):
    return phase7_ready_graph.__wrapped__(db)


def draft_payload(graph):
    return {
        "semester": graph["semester"].pk,
        "department": graph["departments"]["A"].pk,
    }


def extend_grid_for_move(graph):
    day = graph["day"]
    day.end_time = time(11)
    day.save(update_fields=["end_time"])
    slots = [
        TimeSlot.objects.create(
            working_day=day, sequence=3, start_time=time(9, 30), end_time=time(10, 15)
        ),
        TimeSlot.objects.create(
            working_day=day, sequence=4, start_time=time(10, 15), end_time=time(11),
        ),
    ]
    InstructorAvailability.objects.create(
        instructor=graph["instructor"], semester=graph["semester"],
        day_of_week=day.day_of_week, start_time=time(9, 30), end_time=time(11),
    )
    RoomAvailability.objects.create(
        room=graph["room"], semester=graph["semester"],
        day_of_week=day.day_of_week, start_time=time(9, 30), end_time=time(11),
    )
    return slots


def test_manual_validate_has_no_writes_and_apply_creates_copy_on_write_version(
    api_client, ready_graph
):
    graph = ready_graph
    user = make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"])
    authenticate(api_client, user)
    assert api_client.post(DRAFT_URL, draft_payload(graph), format="json").status_code == 200
    base = ScheduleVersion.objects.get(version_number=1)
    base_entry = ScheduleEntry.objects.get(schedule_version=base)
    base_slot_ids = list(
        ScheduleEntryTimeSlot.objects.filter(schedule_entry=base_entry)
        .order_by("position").values_list("time_slot_id", flat=True)
    )
    target_slots = extend_grid_for_move(graph)
    payload = {
        "changes": [{"entry_id": base_entry.pk, "time_slot_ids": [slot.pk for slot in target_slots]}]
    }
    validate_url = f"/api/schedule-versions/{base.pk}/validate-manual-edit/"
    apply_url = f"/api/schedule-versions/{base.pk}/manual-edit/"
    before_counts = (ScheduleVersion.objects.count(), ScheduleEntry.objects.count())
    validation = api_client.post(validate_url, payload, format="json")
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert (ScheduleVersion.objects.count(), ScheduleEntry.objects.count()) == before_counts

    applied = api_client.post(apply_url, payload, format="json")
    assert applied.status_code == 200
    assert applied.json()["persisted"] is True
    manual = ScheduleVersion.objects.get(version_number=2)
    assert manual.source == ScheduleVersionSource.MANUAL_EDIT
    assert manual.parent_version_id == base.pk
    assert manual.solver_status in (None, "")
    new_entry = ScheduleEntry.objects.get(schedule_version=manual, session_id=base_entry.session_id)
    assert new_entry.candidate_id != base_entry.candidate_id
    assert list(
        ScheduleEntryTimeSlot.objects.filter(schedule_entry=new_entry)
        .order_by("position").values_list("time_slot_id", flat=True)
    ) == [slot.pk for slot in target_slots]
    assert list(
        ScheduleEntryTimeSlot.objects.filter(schedule_entry=base_entry)
        .order_by("position").values_list("time_slot_id", flat=True)
    ) == base_slot_ids

    stale = api_client.post(apply_url, payload, format="json")
    assert stale.status_code == 409
    assert stale.json()["reason"] == "STALE_BASE_VERSION"


def test_manual_edit_rejects_empty_noop_and_client_control_fields(api_client, ready_graph):
    graph = ready_graph
    authenticate(
        api_client,
        make_user(UserRole.DEPARTMENT_ADMIN, graph["departments"]["A"]),
    )
    assert api_client.post(DRAFT_URL, draft_payload(graph), format="json").status_code == 200
    version = ScheduleVersion.objects.get(version_number=1)
    entry = ScheduleEntry.objects.get(schedule_version=version)
    url = f"/api/schedule-versions/{version.pk}/validate-manual-edit/"
    assert api_client.post(url, {"changes": []}, format="json").status_code == 400
    assert api_client.post(
        url, {"changes": [{"entry_id": entry.pk}]}, format="json"
    ).status_code == 400
    for field, value in (
        ("status", "PUBLISHED"),
        ("source", "MANUAL_EDIT"),
        ("version_number", 99),
        ("parent_version", version.pk),
        ("candidate_id", "forged"),
        ("penalty", 0),
        ("instructor_ids", []),
        ("student_group_ids", []),
    ):
        response = api_client.post(
            url,
            {"changes": [{"entry_id": entry.pk, "room_id": entry.room_id, field: value}]},
            format="json",
        )
        assert response.status_code == 400, (field, response.content)

    invalid = {"changes": [{"entry_id": entry.pk, "time_slot_ids": [
        ScheduleEntryTimeSlot.objects.get(schedule_entry=entry, position=1).time_slot_id
    ]}]}
    before = (ScheduleVersion.objects.count(), ScheduleEntry.objects.count())
    validation = api_client.post(url, invalid, format="json")
    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    apply_url = f"/api/schedule-versions/{version.pk}/manual-edit/"
    applied = api_client.post(apply_url, invalid, format="json")
    assert applied.status_code == 409
    assert applied.json()["persisted"] is False
    assert (ScheduleVersion.objects.count(), ScheduleEntry.objects.count()) == before
