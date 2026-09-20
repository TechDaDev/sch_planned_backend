"""
Academics models.

Phase 1 introduces the minimal ``Department`` identity only. Programs, stages,
courses, instructors and other academic structure arrive in a later phase.
"""

from django.db import models


class Department(models.Model):
    """An academic department, the unit that will own schedules and resources."""

    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Short department identifier, for example BIOAI or CS.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "department"
        verbose_name_plural = "departments"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"
