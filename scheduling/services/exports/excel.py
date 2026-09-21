"""Excel (.xlsx) rendering of an export document.

The workbook is built with OpenPyXL from the shared tables module, so every workbook
cell that carries an analytics figure is copied straight from the Phase 14 report and
every descriptive cell comes from the persisted snapshot columns.

Two properties matter as much as the content:

* **no formula execution** - every model- or user-derived string is written as data,
  and a string that starts with a spreadsheet formula prefix is neutralized first;
* **no recalculation** - the sheets are projections, not new analysis. A workbook can
  therefore never disagree with the analytics endpoint it was exported from.

Presentation stays deliberately simple: bold headers, a frozen header row, an
auto-filter, readable column widths and wrapped long text. No formulas and no macros
are written, so the file is equally usable in Microsoft Excel, LibreOffice and Google
Sheets.
"""

from __future__ import annotations

import io
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from scheduling.services.exports import tables
from scheduling.services.exports.domain import ExportDocument, TIMETABLE_COLUMNS
from scheduling.services.exports.tables import Table

#: Characters that make a spreadsheet treat a cell value as a formula or a command.
#: A leading tab or carriage return is included because both can hide a formula from a
#: naive prefix check while still being interpreted by the spreadsheet.
DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

#: Neutralizing prefix. The spreadsheet then shows the original text as data instead of
#: evaluating it.
SAFE_PREFIX = "'"

#: Sheet names of a Phase 15 workbook, in order. Kept as constants so tests can assert
#: the documented names without restating them.
SHEET_TIMETABLE = "Timetable"
SHEET_SUMMARY = "Analytics Summary"
SHEET_DEPARTMENT_LOAD = "Department Load"
SHEET_INSTRUCTOR_WORKLOAD = "Instructor Workload"
SHEET_ROOM_UTILIZATION = "Room Utilization"
SHEET_STUDENT_GROUPS = "Student Group Load"
SHEET_QUALITY = "Quality"

SHEET_NAMES = (
    SHEET_TIMETABLE,
    SHEET_SUMMARY,
    SHEET_DEPARTMENT_LOAD,
    SHEET_INSTRUCTOR_WORKLOAD,
    SHEET_ROOM_UTILIZATION,
    SHEET_STUDENT_GROUPS,
    SHEET_QUALITY,
)

#: Column widths per sheet, by column position. Long descriptive columns are wider and
#: wrapped; numeric columns stay narrow.
_HEADER_FILL = PatternFill("solid", fgColor="DDDDDD")
_HEADER_FONT = Font(bold=True)
_WRAP = Alignment(wrap_text=True, vertical="top")
_TOP = Alignment(vertical="top")

_TIMETABLE_WIDTHS = (24, 14, 30, 10, 14, 22, 26, 11, 8, 8, 14, 12, 24, 28, 30, 9)
_TIMETABLE_WRAPPED = (0, 2, 5, 6, 12, 13, 14)
_TWO_COLUMN_WIDTHS = (34, 30)
_LOAD_WIDTHS = (30, 12, 10, 18, 16, 10, 12, 10, 14, 14)
_WORKLOAD_WIDTHS = (26, 10, 10, 10, 18, 16, 12, 16, 15, 24, 18, 15, 22)
_WORKLOAD_WRAPPED = (0, 9)
_ROOM_WIDTHS = (28, 10, 18, 16, 16, 12, 28, 18, 16, 18, 22)
_ROOM_WRAPPED = (0, 6)
_GROUP_WIDTHS = (26, 30, 10, 18, 16, 12, 20, 18, 15, 22)
_GROUP_WRAPPED = (0, 1)

#: 1-based column indexes (0-based from the width tuples) that hold hour values, so a
#: reader sees a consistent two-decimal format.
_HOUR_FORMATS = {
    SHEET_DEPARTMENT_LOAD: {"E": "0.00"},
    SHEET_INSTRUCTOR_WORKLOAD: {"F": "0.00", "I": "0.00"},
    SHEET_ROOM_UTILIZATION: {"D": "0.00", "I": "0.00", "J": "0.00"},
    SHEET_STUDENT_GROUPS: {"E": "0.00"},
}


def sanitize_cell(value: Any) -> Any:
    """Return ``value`` in a form a spreadsheet can never execute.

    Strings that start with a formula or command prefix (``=``, ``+``, ``-``, ``@``, tab
    or carriage return) are prefixed with an apostrophe, which makes the spreadsheet
    treat them as text. Numbers, booleans, dates and ``None`` pass through unchanged, so
    genuine numeric data is never turned into a string.
    """
    if not isinstance(value, str):
        return value
    if value.startswith(DANGEROUS_PREFIXES):
        return f"{SAFE_PREFIX}{value}"
    return value


def sanitize_row(values: Iterable[Any]) -> tuple[Any, ...]:
    """Apply :func:`sanitize_cell` to every cell of one row."""
    return tuple(sanitize_cell(value) for value in values)


def build_workbook(document: ExportDocument) -> bytes:
    """Render one export document as an .xlsx byte string.

    The same seven sheets are produced for every caller. A department-scoped document
    carries only that department's scoped entries and figures, because the document was
    assembled from an already-narrowed report rather than filtered afterwards.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)

    _write_timetable(workbook.create_sheet(SHEET_TIMETABLE), document)
    _write_summary(workbook.create_sheet(SHEET_SUMMARY), document)
    _write_table_sheet(
        workbook.create_sheet(SHEET_DEPARTMENT_LOAD),
        tables.department_load_table(document.report),
        _LOAD_WIDTHS,
        SHEET_DEPARTMENT_LOAD,
        wrapped=(0,),
    )
    _write_table_sheet(
        workbook.create_sheet(SHEET_INSTRUCTOR_WORKLOAD),
        tables.instructor_workload_table(document.report),
        _WORKLOAD_WIDTHS,
        SHEET_INSTRUCTOR_WORKLOAD,
        wrapped=_WORKLOAD_WRAPPED,
    )
    _write_table_sheet(
        workbook.create_sheet(SHEET_ROOM_UTILIZATION),
        tables.room_utilization_table(document.report),
        _ROOM_WIDTHS,
        SHEET_ROOM_UTILIZATION,
        wrapped=_ROOM_WRAPPED,
    )
    _write_table_sheet(
        workbook.create_sheet(SHEET_STUDENT_GROUPS),
        tables.student_group_load_table(document.report),
        _GROUP_WIDTHS,
        SHEET_STUDENT_GROUPS,
        wrapped=_GROUP_WRAPPED,
    )
    _write_table_sheet(
        workbook.create_sheet(SHEET_QUALITY),
        tables.quality_table(document.report),
        _TWO_COLUMN_WIDTHS,
        SHEET_QUALITY,
        wrapped=(0,),
    )

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _write_timetable(sheet: Worksheet, document: ExportDocument) -> None:
    """The timetable sheet: one row per persisted entry, in chronological order."""
    _write_header(sheet, TIMETABLE_COLUMNS)
    for row in document.timetable:
        sheet.append(sanitize_row(row.as_values()))
    _apply_widths(sheet, _TIMETABLE_WIDTHS)
    _apply_wrapped(sheet, _TIMETABLE_WRAPPED, len(TIMETABLE_COLUMNS))
    _freeze_and_filter(sheet, len(TIMETABLE_COLUMNS))


def _write_summary(sheet: Worksheet, document: ExportDocument) -> None:
    """Document metadata, then the headline counts, then the department split."""
    sheet.append(sanitize_row(("Field", "Value")))
    _style_header(sheet, 1, 2)
    for label, value in document.metadata.as_rows():
        sheet.append(sanitize_row((label, value)))
    sheet.append(())
    summary = tables.summary_table(document.report)
    _append_block(sheet, summary, title="Summary")
    scope = tables.department_scope_table(document.report)
    if scope.rows:
        sheet.append(())
        _append_block(sheet, scope, title="Department Scope")
    _apply_widths(sheet, _TWO_COLUMN_WIDTHS)
    _apply_wrapped(sheet, (1,), 2)
    sheet.freeze_panes = "A2"


def _append_block(sheet: Worksheet, table: Table, *, title: str) -> None:
    """A titled two-column block, used on the summary sheet."""
    sheet.append(sanitize_row((title, "")))
    _style_header(sheet, sheet.max_row, len(table.headers))
    sheet.append(sanitize_row(table.headers))
    _style_header(sheet, sheet.max_row, len(table.headers))
    for row in table.rows:
        sheet.append(sanitize_row(row))


def _write_table_sheet(
    sheet: Worksheet,
    table: Table,
    widths: tuple[int, ...],
    sheet_name: str,
    *,
    wrapped: tuple[int, ...],
) -> None:
    """One analytics sheet: header row, data rows, formatting."""
    _write_header(sheet, table.headers)
    for row in table.rows:
        sheet.append(sanitize_row(row))
    _apply_widths(sheet, widths)
    _apply_wrapped(sheet, wrapped, len(table.headers))
    _apply_number_formats(sheet, sheet_name, len(table.headers))
    _freeze_and_filter(sheet, len(table.headers))


def _write_header(sheet: Worksheet, headers: Iterable[str]) -> None:
    headers = tuple(headers)
    sheet.append(headers)
    _style_header(sheet, 1, len(headers))


def _style_header(sheet: Worksheet, row_index: int, column_count: int) -> None:
    for column in range(1, column_count + 1):
        cell = sheet.cell(row=row_index, column=column)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL


def _apply_widths(sheet: Worksheet, widths: tuple[int, ...]) -> None:
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _apply_wrapped(
    sheet: Worksheet, columns: tuple[int, ...], column_count: int
) -> None:
    alignment = {column + 1: _WRAP for column in columns}
    for row in sheet.iter_rows(min_row=2, max_col=column_count):
        for cell in row:
            cell.alignment = alignment.get(cell.column, _TOP)


def _apply_number_formats(
    sheet: Worksheet, sheet_name: str, column_count: int
) -> None:
    formats = _HOUR_FORMATS.get(sheet_name)
    if not formats:
        return
    for row in sheet.iter_rows(min_row=2, max_col=column_count):
        for cell in row:
            number_format = formats.get(get_column_letter(cell.column))
            if number_format and isinstance(cell.value, (int, float)):
                cell.number_format = number_format


def _freeze_and_filter(sheet: Worksheet, column_count: int) -> None:
    """Freeze the header row and add an auto-filter over the written range."""
    sheet.freeze_panes = "A2"
    if sheet.max_row >= 2:
        sheet.auto_filter.ref = (
            f"A1:{get_column_letter(column_count)}{sheet.max_row}"
        )
    else:
        sheet.auto_filter.ref = f"A1:{get_column_letter(column_count)}1"


__all__ = [
    "DANGEROUS_PREFIXES",
    "SAFE_PREFIX",
    "SHEET_NAMES",
    "build_workbook",
    "sanitize_cell",
    "sanitize_row",
]
