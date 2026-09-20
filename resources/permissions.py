"""Phase 4 visibility rules for instructor resources.

Instructors are department-owned resources with explicit sharing, so what a
department may **read** is broader than what it may **write**:

* the primary department always sees its own instructors;
* ``SELECTED_DEPARTMENTS`` instructors are visible to departments holding an
  active access grant;
* ``COLLEGE_WIDE`` instructors are visible college-wide (active departments);
* instructors actively assigned to a component the department can already see
  through Phase 3 joint teaching are visible **read-only**. That read rule never
  makes them eligible for unrelated assignments - eligibility is decided by
  ``InstructorProfile.can_teach_in_department``.

Availability and preferences deliberately use the narrower ownership/sharing
rule: seeing an instructor on one joint course must not expose their full weekly
availability, because a scheduler only needs availability for instructors it can
actually schedule.

Writes are gated by ``IsDepartmentScopedManager`` in the views, which resolves
ownership through each viewset's ``management_department_lookups``.
"""

from django.db import models

from resources.models import SharingScope


def _never(prefix: str) -> models.Q:
    """A ``Q`` object that never matches, honouring a relation prefix."""
    return models.Q(**{f"{prefix}pk__in": []})


def _instructor_sharing_q(prefix: str, department) -> models.Q:
    """Instructors effectively shared *with* ``department``.

    ``prefix`` is the relation path to the instructor (``""`` when the queryset
    already is the instructor table, ``"instructor__"`` for its child rows).
    """
    if department is None:
        return _never(prefix)
    college_wide = (
        models.Q(**{f"{prefix}sharing_scope": SharingScope.COLLEGE_WIDE})
        if department.is_active
        else _never(prefix)
    )
    return (
        models.Q(**{f"{prefix}primary_department_id": department.pk})
        | college_wide
        | models.Q(
            **{
                f"{prefix}sharing_scope": SharingScope.SELECTED_DEPARTMENTS,
                f"{prefix}department_access__department_id": department.pk,
                f"{prefix}department_access__is_active": True,
            }
        )
    )


def visible_instructors_filter(user) -> models.Q:
    """Instructors a department-scoped user may read, including joint teaching."""
    department = user.department
    if department is None:
        return _never("")
    department_id = department.pk
    return (
        _instructor_sharing_q("", department)
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
    return _instructor_sharing_q("instructor__", user.department)


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


__all__ = [
    "visible_assignments_filter",
    "visible_availability_filter",
    "visible_instructor_access_filter",
    "visible_instructor_windows_filter",
    "visible_instructors_filter",
    "visible_preferences_filter",
]
