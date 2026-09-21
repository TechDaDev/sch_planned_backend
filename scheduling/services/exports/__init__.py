"""Phase 15 exports: Excel and PDF representations of a persisted schedule version.

The package splits cleanly:

``domain``
    value objects - the timetable row, the document metadata and the export document -
    and the controlled export errors.
``tables``
    pure projections of a Phase 14 report into rows of primitives.
``excel``
    OpenPyXL rendering, including the spreadsheet formula-injection guard.
``pdf``
    ReportLab rendering, including font resolution, Arabic shaping and glyph coverage.
``filenames``
    safe, deterministic download filenames and media types.
``service``
    the entry point that resolves a source into a document.

Views only authorize a source, ask the service for a document and turn the rendered
bytes into a response.
"""

from scheduling.services.exports.domain import (
    ExportDocument,
    ExportError,
    ExportFontUnavailable,
    ExportMetadata,
    TimetableRow,
    timetable_rows,
)
from scheduling.services.exports.excel import build_workbook, sanitize_cell
from scheduling.services.exports.filenames import (
    PDF_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    content_disposition,
    manage_version_filename,
    published_filename,
    sanitize_component,
    template_filename,
)
from scheduling.services.exports.pdf import build_pdf
from scheduling.services.exports.service import (
    ScheduleExportService,
    TITLE_PUBLISHED,
    TITLE_VERSION,
)

__all__ = [
    "PDF_MEDIA_TYPE",
    "TITLE_PUBLISHED",
    "TITLE_VERSION",
    "XLSX_MEDIA_TYPE",
    "ExportDocument",
    "ExportError",
    "ExportFontUnavailable",
    "ExportMetadata",
    "ScheduleExportService",
    "TimetableRow",
    "build_pdf",
    "build_workbook",
    "content_disposition",
    "manage_version_filename",
    "published_filename",
    "sanitize_cell",
    "sanitize_component",
    "template_filename",
    "timetable_rows",
]
