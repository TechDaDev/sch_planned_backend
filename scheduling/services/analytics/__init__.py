"""Read-only schedule analytics (Phase 14).

* ``domain`` - the value objects: entry facts, snapshot references and the report
  objects, all of which serialize to plain JSON.
* ``summary`` - headline counts, department load, department-scoped managed versus
  participating sessions, and student-group load.
* ``workload`` - instructor workload, merged per person across departments.
* ``rooms`` - snapshot room usage plus the *current-configuration* denominator used
  for utilization.
* ``quality`` - preference penalty, gap totals, weekday distribution and daily
  concentration, with no invented composite score.
* ``gaps`` - the shared gap arithmetic.
* ``service`` - ``ScheduleAnalyticsService``: load a version, aggregate, return.

Two things never happen here: writing to the database, and replacing a snapshot value
with a live one. Analytics describe the version they were asked about.
"""

from scheduling.services.analytics.domain import (
    UTILIZATION_BASIS,
    DepartmentLoad,
    DepartmentScope,
    EntryFacts,
    GroupFact,
    InstructorFact,
    InstructorWorkload,
    QualityMetrics,
    RoomUsage,
    SnapshotRef,
    StudentGroupLoad,
    SummaryMetrics,
    VersionAnalytics,
    VersionRef,
)
from scheduling.services.analytics.gaps import GapTotals, gap_totals
from scheduling.services.analytics.service import (
    ScheduleAnalyticsService,
    analytics_for_version,
)

__all__ = [
    "UTILIZATION_BASIS",
    "DepartmentLoad",
    "DepartmentScope",
    "EntryFacts",
    "GapTotals",
    "GroupFact",
    "InstructorFact",
    "InstructorWorkload",
    "QualityMetrics",
    "RoomUsage",
    "ScheduleAnalyticsService",
    "SnapshotRef",
    "StudentGroupLoad",
    "SummaryMetrics",
    "VersionAnalytics",
    "VersionRef",
    "analytics_for_version",
    "gap_totals",
]