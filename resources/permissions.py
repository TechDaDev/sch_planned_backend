"""Phase 4 and Phase 5 visibility rules for resource-owned data.

Resources (instructors and rooms) are department-owned with explicit sharing, so
what a department may **read** is broader than what it may **write**:

* the owner (primary) department always sees its own resources;
* ``SELECTED_DEPARTMENTS`` resources are visible to departments holding an
  active access grant;
* ``COLLEGE_WIDE`` resources are visible college-wide (active departments);
* instructors actively assigned to a component the department can already see
  through Phase 3 joint teaching are visible **read-only**. That read rule never
  makes them eligible for unrelated assignments - eligibility is decided by
  ``InstructorProfile.can_teach_in_department``.

Availability-type windows use the narrower ownership/sharing rule: seeing a
resource on one joint course must not expose its full weekly availability, since
a scheduler only needs availability for resources it can actually schedule.
Room availability follows the room-sharing rule instead, because any department
allowed to use a room must be able to read its windows.

Writes are gated by ``IsDepartmentScopedManager`` in the views, which resolves
ownership through each viewset's ``management_department_lookups``.
"""

from django.db import models

from resources.models import SharingScope


def _never(prefix: str) -> models.Q:
    """A ``Q`` object that never matches, honouring a relation prefix."""
    return models.Q(**{f"{prefix}pk__in": []})


def _owner_sharing_q(
    prefix: str,
    department,
    *,
    owner_field: str,
    access_relation: str = "department_access",
) -> models.Q:
    """Resources effectively shared *with* ``department``.

    ``prefix`` is the relation path to the resource (``""`` when the queryset
    already is the resource table, ``"instructor__"``/``"room__"`` for child
    rows). ``owner_field`` names the ownership foreign key (``"primary_department"``
    for instructors, ``"owner_department"`` for rooms) and ``access_relation``
    the related name of the explicit sharing grants.
    """
    if department is None:
        return _never(prefix)
    college_wide = (
        models.Q(**{f"{prefix}sharing_scope": SharingScope.COLLEGE_WIDE})
        if department.is_active
        else _never(prefix)
    )
    return (
        models.Q(**{f"{prefix}{owner_field}_id": department.pk})
        | college_wide
        | models.Q(
            **{
                f"{prefix}sharing_scope": SharingScope.SELECTED_DEPARTMENTS,
                f"{prefix}{access_relation}__department_id": department.pk,
                f"{prefix}{access_relation}__is_active": True,
            }
        )
    )


def instructor_sharing_q(prefix: str, department) -> models.Q:
    """Instructors effectively shared with ``department``."""
    return _owner_sharing_q(
        prefix, department, owner_field="primary_department"
    )


def room_sharing_q(prefix: str, department) -> models.Q:
    """Rooms effectively shared with ``department``."""
    return _owner_sharing_q(prefix, department, owner_field="owner_department")


def visible_instructors_filter(user) -> models.Q:
    """Instructors a department-scoped user may read, including joint teaching."""
    department = user.department
    if department is None:
        return _never("")
    department_id = department.pk
    return (
        instructor_sharing_q("", department)
        | models.Q(
            teaching_assignments__is_active=True,
            teaching_assignments__teaching_component__offering__managing_department_id=department_id,
        )
        | models.Q(
            teaching_assignments__is_active=True,
            teaching_assignments__teaching_component__group_links__student_group__stage__program__department_id=department_id,
        )
    )


def visible_instructor_access_filter(user) -> models.Q:
    """Access grants the user may read.

    The owning (primary) department sees all grants for its instructors; a
    consuming department sees only the active grants made out to itself.
    """
    department = user.department
    if department is None:
        return _never("")
    return models.Q(instructor__primary_department_id=department.pk) | models.Q(
        department_id=department.pk, is_active=True
    )


def visible_instructor_windows_filter(user) -> models.Q:
    """Availability/preference rows of instructors the department may schedule."""
    return instructor_sharing_q("instructor__", user.department)


def visible_availability_filter(user) -> models.Q:
    """Visibility for ``InstructorAvailability`` rows."""
    return visible_instructor_windows_filter(user)


def visible_preferences_filter(user) -> models.Q:
    """Preferences follow exactly the same visibility rule as availability."""
    return visible_instructor_windows_filter(user)


def visible_assignments_filter(user) -> models.Q:
    """Assignments follow Phase 3 teaching-component visibility."""
    department = user.department
    if department is None:
        return _never("")
    department_id = department.pk
    return models.Q(
        teaching_component__offering__managing_department_id=department_id
    ) | models.Q(
        teaching_component__group_links__student_group__stage__program__department_id=department_id
    )


def visible_rooms_filter(user) -> models.Q:
    """Rooms the user's department owns or may use."""
    return room_sharing_q("", user.department)


def visible_room_access_filter(user) -> models.Q:
    """Room sharing grants the user may read.

    The owning department sees all grants for its rooms; a consuming department
    sees only the active grants made out to itself.
    """
    department = user.department
    if department is None:
        return _never("")
    return models.Q(room__owner_department_id=department.pk) | models.Q(
        department_id=department.pk, is_active=True
    )


def visible_room_capability_assignments_filter(user) -> models.Q:
    """Capability assignments on rooms the department owns or may use."""
    return room_sharing_q("room__", user.department)


def visible_room_availability_filter(user) -> models.Q:
    """Availability of rooms the department owns or may use."""
    return room_sharing_q("room__", user.department)


def visible_room_requirements_filter(user) -> models.Q:
    """Room requirements follow Phase 3 teaching-component visibility."""
    department = user.department
    if department is None:
        return _never("")
    department_id = department.pk
    return models.Q(
        teaching_component__offering__managing_department_id=department_id
    ) | models.Q(
        teaching_component__group_links__student_group__stage__program__department_id=department_id
    )


def visible_capability_requirements_filter(user) -> models.Q:
    """Capability requirements follow their teaching component's visibility."""
    department = user.department
    if department is None:
        return _never("")
    department_id = department.pk
    return models.Q(
        room_requirement__teaching_component__offering__managing_department_id=department_id
    ) | models.Q(
        room_requirement__teaching_component__group_links__student_group__stage__program__department_id=department_id
    )


__all__ = [
    "instructor_sharing_q",
    "room_sharing_q",
    "visible_assignments_filter",
    "visible_availability_filter",
    "visible_capability_requirements_filter",
    "visible_instructor_access_filter",
    "visible_instructor_windows_filter",
    "visible_instructors_filter",
    "visible_preferences_filter",
    "visible_room_access_filter",
    "visible_room_availability_filter",
    "visible_room_capability_assignments_filter",
    "visible_room_requirements_filter",
    "visible_rooms_filter",
]
