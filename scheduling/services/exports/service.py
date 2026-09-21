"""The export service: one entry point for both representations.

The service decides *what* a document contains; the renderers decide how it looks. It
consumes the Phase 14 analytics service directly - no HTTP calls, no second copy of the
scoping rules - so an export and the analytics endpoint describe the same entry set by
construction:

* a management export uses ``ScheduleAnalyticsService.for_version`` exactly as the
  version analytics action does;
* a published export uses ``ScheduleAnalyticsService.for_published``, which reads the
  schedule's authoritative ``published_version`` pointer and narrows a department's
  entry set before aggregation, exactly as the published analytics endpoint does.

Nothing here writes. Repeated exports of one version produce the same document apart
from the generated timestamp.
"""

from __future__ import annotations

from datetime import datetime, timezone

from scheduling.services.analytics import ScheduleAnalyticsService, VersionAnalytics
from scheduling.services.exports.domain import (
    ExportDocument,
    ExportMetadata,
    timetable_rows,
)

TITLE_VERSION = "Schedule version export"
TITLE_PUBLISHED = "Published college timetable"


class ScheduleExportService:
    """Builds one :class:`ExportDocument` from one authorized source."""

    def __init__(
        self,
        *,
        version,
        department=None,
        scope: str | None = None,
        title: str,
        generated_at: datetime | None = None,
    ) -> None:
        self.analytics = ScheduleAnalyticsService(
            version=version, department=department, scope=scope
        )
        self.department = department
        self.title = title
        self.generated_at = generated_at

    @classmethod
    def for_version(cls, version, *, generated_at: datetime | None = None):
        """Export of one persisted version, scoped to its own schedule."""
        return cls(
            version=version,
            title=TITLE_VERSION,
            generated_at=generated_at,
        )

    @classmethod
    def for_published(cls, schedule, *, department=None, generated_at=None):
        """Export of the authoritative published version of one semester.

        ``department`` narrows the document to that department's official entry set,
        before any aggregation happens.
        """
        return cls(
            version=schedule.published_version,
            department=department,
            scope="DEPARTMENT" if department is not None else schedule.scope,
            title=TITLE_PUBLISHED,
            generated_at=generated_at,
        )

    def document(self) -> ExportDocument:
        """Assemble the document, loading the scoped entries exactly once."""
        facts = self.analytics.facts()
        report = self.analytics.build(facts=facts)
        return ExportDocument(
            metadata=_metadata(
                report,
                title=self.title,
                department=self.department,
                generated_at=self.generated_at or datetime.now(timezone.utc),
            ),
            report=report,
            timetable=timetable_rows(facts),
        )


def _metadata(
    report: VersionAnalytics,
    *,
    title: str,
    department,
    generated_at: datetime,
) -> ExportMetadata:
    """Document metadata, taken from the analysed version's own identity."""
    version = report.version
    published_by = version.published_by
    published_by_label = None
    if isinstance(published_by, dict):
        published_by_label = str(
            published_by.get("username") or published_by.get("id") or ""
        ) or None
    return ExportMetadata(
        title=title,
        scope=report.scope,
        semester_label=version.semester_label,
        schedule_id=version.schedule_id,
        version_number=version.version_number,
        status=version.status,
        source=version.source,
        version_created_at=version.created_at,
        published_at=version.published_at,
        published_by=published_by_label,
        department_label=(
            None
            if department is None
            else f"{department.code} — {department.name}"
        ),
        generated_at=generated_at,
    )


__all__ = [
    "TITLE_PUBLISHED",
    "TITLE_VERSION",
    "ScheduleExportService",
]
