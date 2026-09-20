"""
Accounts models.

Phase 0 establishes the custom user model before the initial schema migration,
because swapping ``AUTH_USER_MODEL`` after migrations exist is unnecessarily
painful. Roles (college admin, department admin, scheduler, viewer, instructor)
and department/instructor relations are added in a later phase.
"""

from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Custom user model for the College Academic Schedule Planner."""

    # Phase 0 intentionally adds no fields on top of AbstractUser.
    pass
