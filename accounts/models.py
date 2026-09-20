"""
Accounts models.

Phase 0 established the custom user model before the initial schema migration.
Phase 1 adds the application role and the optional department assignment.
Academic-year, program, stage and course relationships belong to later phases.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
    """Application roles.

    ``VIEWER`` is the least-privilege default assigned to new accounts.
    """

    COLLEGE_ADMIN = "COLLEGE_ADMIN", "College Administrator"
    DEPARTMENT_ADMIN = "DEPARTMENT_ADMIN", "Department Administrator"
    SCHEDULER = "SCHEDULER", "Scheduler"
    VIEWER = "VIEWER", "Viewer"
    INSTRUCTOR = "INSTRUCTOR", "Instructor"


class User(AbstractUser):
    """Custom user model for the College Academic Schedule Planner."""

    #: Roles that grant college-wide administrative access.
    ADMIN_ROLES = frozenset({UserRole.COLLEGE_ADMIN, UserRole.DEPARTMENT_ADMIN})

    role = models.CharField(
        max_length=32,
        choices=UserRole.choices,
        default=UserRole.VIEWER,
        help_text="Application role; least privilege ('Viewer') by default.",
    )
    department = models.ForeignKey(
        "academics.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        help_text="Owning department; a college administrator may have none.",
    )

    @property
    def is_college_admin(self) -> bool:
        return self.role == UserRole.COLLEGE_ADMIN

    @property
    def is_department_admin(self) -> bool:
        return self.role == UserRole.DEPARTMENT_ADMIN

    @property
    def is_scheduler(self) -> bool:
        return self.role == UserRole.SCHEDULER

    @property
    def is_viewer(self) -> bool:
        return self.role == UserRole.VIEWER

    @property
    def is_instructor(self) -> bool:
        return self.role == UserRole.INSTRUCTOR

    @property
    def has_admin_role(self) -> bool:
        """True when the user holds a college- or department-level admin role."""
        return self.role in self.ADMIN_ROLES

    @property
    def has_cross_department_access(self) -> bool:
        """True for Django superusers and college administrators (all departments)."""
        return self.is_superuser or self.is_college_admin
