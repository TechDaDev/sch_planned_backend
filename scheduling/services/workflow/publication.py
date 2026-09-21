"""Reading the officially published timetable.

Publication is the first thing in this project that is meant to be consumed *outside*
schedule management. It therefore needs its own visibility rule, stricter than the
draft APIs and simpler than an authorization model:

* a college administrator sees every entry of the published version;
* a department's users see the entries that concern their department — the ones the
  department manages, and the joint sessions foreign departments manage but their own
  student groups attend;
* an instructor sees the sessions they actually teach, taken from the persisted
  instructor rows, which is the safe foundation for the later instructor app;
* everybody else sees nothing at all.

The rendering side is equally deliberate: a published response shows the *stored*
snapshot values, because the official timetable is the approved version, not a live
view of today's names.
"""

from __future__ import annotations

from django.db import models

from accounts.models import UserRole
from academics.models import Department
from resources.models import InstructorProfile
from scheduling.models import ScheduleEntry

#: Roles that may read published entries for their own department.
PUBLISHED_DEPARTMENT_ROLES = frozenset(
    {UserRole.DEPARTMENT_ADMIN, UserRole.SCHEDULER, UserRole.VIEWER}
)


def published_entry_filter(user) -> models.Q:
    """Which published entries a user may see, as a queryset filter.

    Returns a filter that matches nothing for a caller with no published visibility,
    so the rule fails closed without the caller having to check a flag first.
    """
    if user.has_cross_department_access:
        return models.Q()

    instructor_profile_id = (
        InstructorProfile.objects.filter(user=user)
        .values_list("pk", flat=True)
        .first()
    )
    if instructor_profile_id is not None:
        return models.Q(instructors__instructor_id=instructor_profile_id)

    if user.department_id is None or user.role not in PUBLISHED_DEPARTMENT_ROLES:
        return models.Q(pk__in=[])

    department_id = user.department_id
    return models.Q(managing_department_id=department_id) | models.Q(
        student_groups__department_id_snapshot=department_id
    )


def published_entries(*, version, user):
    """The published entries of ``version`` that ``user`` may read.

    Children are prefetched, and the join used by the department rule is collapsed
    with ``distinct``, so an entry is returned once however it matched.
    """
    return (
        ScheduleEntry.objects.filter(schedule_version=version)
        .filter(published_entry_filter(user))
        .select_related("teaching_component", "managing_department", "room")
        .prefetch_related("time_slots", "instructors", "student_groups")
        .distinct()
        .order_by("day_of_week", "start_time", "id")
    )


def current_published_college_schedule(*, semester):
    """The college schedule of ``semester`` that currently has a published version.

    The authoritative publication is the pointer on the schedule, never a
    ``status=PUBLISHED`` query: several historical versions may carry that status, and
    only one of them is current.
    """
    from scheduling.models import Schedule, ScheduleScope

    return (
        Schedule.objects.filter(
            semester=semester,
            scope=ScheduleScope.COLLEGE,
            published_version__isnull=False,
        )
        .select_related("semester", "semester__academic_year", "published_version")
        .first()
    )


def department_for_user(user):
    """The user's department instance, or None when the account has none."""
    if user.department_id is None:
        return None
    return Department.objects.filter(pk=user.department_id).first()


__all__ = [
    "PUBLISHED_DEPARTMENT_ROLES",
    "current_published_college_schedule",
    "department_for_user",
    "published_entries",
    "published_entry_filter",
]
