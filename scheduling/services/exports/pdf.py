"""PDF rendering of an export document.

The PDF is generated with ReportLab and mirrors the workbook: the same scoped
timetable rows, the same Phase 14 figures, no invented score. Layout is a clear
landscape table rather than a fragile weekly grid, and the timetable is one flowable, so
ReportLab splits it across pages instead of dropping the sessions that would not fit.

Unicode is handled explicitly. ReportLab draws glyphs, it does not shape Arabic, so any
string that contains right-to-left characters is reshaped and reordered with
``arabic-reshaper`` and ``python-bidi`` before it is drawn. Because a document is only as
correct as the font behind it, the renderer also verifies that the resolved font covers
every character it is about to draw. When no usable font can be resolved - or when the
resolved font lacks a required glyph - it raises
:class:`~scheduling.services.exports.domain.ExportFontUnavailable` instead of emitting
empty boxes or a corrupt-looking document.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable
from xml.sax.saxutils import escape

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from scheduling.services.exports import tables
from scheduling.services.exports.domain import (
    ExportDocument,
    ExportFontUnavailable,
)
from scheduling.services.exports.tables import Table as TableData

#: Font candidates, most preferred first. Every entry is an open-source font that covers
#: Latin plus Arabic, including the Arabic presentation forms produced by reshaping.
FONT_REGULAR_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
)

FONT_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
)

#: Registered font names inside the generated document.
FONT_REGULAR = "ExportSans"
FONT_BOLD = "ExportSans-Bold"

#: Script ranges that need reshaping and bidirectional reordering.
_RTL_PATTERN = re.compile(
    "[\u0590-\u05ff\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]"
)

#: Column headers and widths of the PDF timetable, in points (landscape A4 minus margins).
_TIMETABLE_COLUMNS = (
    "Department",
    "Course",
    "Component",
    "Day & Time",
    "Periods",
    "Room",
    "Instructors",
    "Student Groups",
)
_TIMETABLE_WIDTHS = (72, 92, 92, 62, 46, 74, 118, 118)


@dataclass(frozen=True)
class ResolvedFont:
    """The font pair a document is drawn with."""

    regular_name: str
    bold_name: str
    regular_path: str
    bold_path: str


def resolve_font_paths() -> tuple[str, str]:
    """Resolve the regular and bold font files, most preferred candidate first.

    The paths may be overridden with the ``PDF_EXPORT_FONT_REGULAR`` and
    ``PDF_EXPORT_FONT_BOLD`` settings (environment-driven), which is how a deployment
    without the development fonts points the exporter at its own copy.
    """
    configured_regular = _setting_path("PDF_EXPORT_FONT_REGULAR")
    configured_bold = _setting_path("PDF_EXPORT_FONT_BOLD")

    regular = _first_existing((configured_regular, *FONT_REGULAR_CANDIDATES))
    if regular is None:
        raise ExportFontUnavailable()
    bold = _first_existing((configured_bold, *FONT_BOLD_CANDIDATES)) or regular
    return regular, bold


def _setting_path(name: str) -> str | None:
    value = getattr(settings, name, None)
    if not value:
        return None
    return str(value)


def _first_existing(paths: Iterable[str | None]) -> str | None:
    for path in paths:
        if path and os.path.isfile(path):
            return path
    return None


def resolve_fonts() -> ResolvedFont:
    """Register and return the font pair, or raise :class:`ExportFontUnavailable`."""
    regular_path, bold_path = resolve_font_paths()
    try:
        pdfmetrics.registerFont(TTFont(FONT_REGULAR, regular_path))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, bold_path))
    except Exception as exc:  # pragma: no cover - a broken font file is environmental
        raise ExportFontUnavailable(
            f"The configured PDF font could not be loaded: {exc}"
        ) from exc
    return ResolvedFont(
        regular_name=FONT_REGULAR,
        bold_name=FONT_BOLD,
        regular_path=regular_path,
        bold_path=bold_path,
    )


def shape_text(value: str) -> str:
    """Reshape and reorder one line so ReportLab draws connected Arabic correctly.

    Text without right-to-left characters is returned unchanged, so a Latin-only
    document is never altered by the shaping step.
    """
    if not value or not _RTL_PATTERN.search(value):
        return value

    from arabic_reshaper import reshape
    from bidi.algorithm import get_display

    return get_display(reshape(value))


def missing_glyphs(text: str, font_name: str = FONT_REGULAR) -> tuple[str, ...]:
    """Characters of ``text`` the registered font cannot draw, sorted and unique.

    Whitespace is ignored because a missing space is not a visible defect.
    """
    font = pdfmetrics.getFont(font_name)
    char_to_glyph = font.face.charToGlyph
    missing = {
        character
        for character in text
        if not character.isspace() and char_to_glyph.get(ord(character), 0) == 0
    }
    return tuple(sorted(missing))


def build_pdf(document: ExportDocument) -> bytes:
    """Render one export document as PDF bytes.

    Raises :class:`ExportFontUnavailable` when the document cannot be drawn correctly,
    so a caller never receives a document with silently missing text.
    """
    fonts = resolve_fonts()
    flow = _flow(document, fonts)

    stream = io.BytesIO()
    pdf = SimpleDocTemplate(
        stream,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=document.metadata.title,
        author="College Academic Schedule Planner",
    )
    pdf.build(flow)

    data = stream.getvalue()
    if not data.startswith(b"%PDF-"):
        raise ExportFontUnavailable("The generated document is not a valid PDF.")
    return data


def _flow(document: ExportDocument, fonts: ResolvedFont) -> list[Any]:
    """The document body, with a glyph-coverage check before anything is drawn."""
    shaped_strings = _document_strings(document)
    for text in shaped_strings:
        missing = missing_glyphs(text, fonts.regular_name)
        if missing:
            raise ExportFontUnavailable(
                "The resolved PDF font cannot draw "
                f"{', '.join(repr(character) for character in missing)}. No document "
                "was generated."
            )

    title_style = ParagraphStyle(
        "ExportTitle",
        fontName=fonts.bold_name,
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#111111"),
        alignment=TA_LEFT,
    )
    body_style = ParagraphStyle(
        "ExportBody",
        fontName=fonts.regular_name,
        fontSize=9,
        leading=12,
    )
    small_style = ParagraphStyle(
        "ExportSmall",
        fontName=fonts.regular_name,
        fontSize=7.5,
        leading=9.5,
    )
    header_style = ParagraphStyle(
        "ExportHeader",
        fontName=fonts.bold_name,
        fontSize=7.5,
        leading=9.5,
    )

    flow: list[Any] = [
        Paragraph(_paragraph_text(document.metadata.title), title_style),
        Spacer(1, 4),
    ]
    for label, value in document.metadata.as_rows():
        if not value:
            continue
        line = f"<b>{escape(label)}:</b> {escape(value)}" if label != value else value
        flow.append(Paragraph(_paragraph_text(line), body_style))
    flow.append(Spacer(1, 8))

    flow.append(Paragraph("Timetable", body_style))
    flow.append(Spacer(1, 3))
    flow.append(_timetable_table(document, header_style, small_style))
    flow.append(Spacer(1, 10))

    flow.append(
        KeepTogether(
            [
                Paragraph("Analytics summary", body_style),
                Spacer(1, 3),
                _metrics_table(
                    tables.summary_table(document.report), header_style, small_style
                ),
            ]
        )
    )
    scope = tables.department_scope_table(document.report)
    if scope.rows:
        flow.append(Spacer(1, 6))
        flow.append(
            KeepTogether(
                [
                    Paragraph("Department scope", body_style),
                    Spacer(1, 3),
                    _metrics_table(scope, header_style, small_style),
                ]
            )
        )

    flow.append(Spacer(1, 6))
    flow.append(
        KeepTogether(
            [
                Paragraph("Quality", body_style),
                Spacer(1, 3),
                _metrics_table(
                    tables.quality_table(document.report), header_style, small_style
                ),
            ]
        )
    )
    return flow


def _document_strings(document: ExportDocument) -> tuple[str, ...]:
    """Every string that will be drawn, after shaping.

    The coverage check runs against exactly these strings, so a font that cannot draw a
    name it is asked to draw fails the request rather than the document.
    """
    strings: list[str] = [shape_text(document.metadata.title)]
    for label, value in document.metadata.as_rows():
        strings.append(shape_text(str(label)))
        strings.append(shape_text(str(value)))
    for row in document.timetable:
        strings.extend(shape_text(_cell_text(value)) for value in row.as_values())
    for table in _analytics_tables(document):
        strings.append(shape_text(table.headers[0]))
        for row in table.rows:
            strings.extend(shape_text(_cell_text(value)) for value in row)
    return tuple(strings)


def _analytics_tables(document: ExportDocument) -> tuple[TableData, ...]:
    return (
        tables.summary_table(document.report),
        tables.department_scope_table(document.report),
        tables.quality_table(document.report),
    )


def _paragraph_text(value: str) -> str:
    """Shape and escape one line for a ReportLab paragraph."""
    return escape(shape_text(value))


def _timetable_table(
    document: ExportDocument, header_style: ParagraphStyle, cell_style: ParagraphStyle
) -> Table:
    """A paginated timetable table: the header repeats and no row is dropped."""
    data: list[list[Any]] = [
        [
            Paragraph(escape(shape_text(header)), header_style)
            for header in _TIMETABLE_COLUMNS
        ]
    ]
    for row in document.timetable:
        data.append(
            [
                Paragraph(_paragraph_text(row.managing_department), cell_style),
                Paragraph(
                    _paragraph_text(
                        _join(row.course_code, row.course_name)
                    ),
                    cell_style,
                ),
                Paragraph(
                    _paragraph_text(_join(row.component_type, row.component_label)),
                    cell_style,
                ),
                Paragraph(
                    _paragraph_text(
                        f"{row.weekday} {row.start}-{row.end}"
                    ),
                    cell_style,
                ),
                Paragraph(_paragraph_text(row.periods), cell_style),
                Paragraph(
                    _paragraph_text(_join(row.room_code, row.room_name)), cell_style
                ),
                Paragraph(_paragraph_text(row.instructors), cell_style),
                Paragraph(_paragraph_text(row.student_groups), cell_style),
            ]
        )
    table = Table(
        data,
        colWidths=list(_TIMETABLE_WIDTHS),
        repeatRows=1,
        splitByRow=1,
    )
    table.setStyle(_grid_style())
    return table


def _metrics_table(
    data: TableData, header_style: ParagraphStyle, cell_style: ParagraphStyle
) -> Table:
    """A small two-column metric block."""
    rows: list[list[Any]] = [
        [Paragraph(escape(shape_text(value)), header_style) for value in data.headers]
    ]
    rows.extend(
        [
            Paragraph(_paragraph_text(str(label)), cell_style),
            Paragraph(_paragraph_text(_cell_text(value)), cell_style),
        ]
        for label, value in data.rows
    )
    table = Table(rows, colWidths=(220, 240), repeatRows=1)
    table.setStyle(_grid_style())
    return table


def _grid_style() -> TableStyle:
    return TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
    )


def _cell_text(value: Any) -> str:
    """Display form of one table cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def _join(*values: str) -> str:
    """Readable combination of an optional code and a name."""
    parts = [str(value).strip() for value in values if str(value or "").strip()]
    return " — ".join(parts)


__all__ = [
    "FONT_BOLD",
    "FONT_REGULAR",
    "build_pdf",
    "missing_glyphs",
    "resolve_font_paths",
    "resolve_fonts",
    "shape_text",
]
