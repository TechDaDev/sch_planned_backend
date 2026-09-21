"""Strict, defensive reading of a semester teaching plan workbook.

The reader is the boundary between an untrusted upload and the rest of the import. It
decides whether a file may be parsed at all, and it never evaluates anything the file
contains:

* only ``.xlsx`` is accepted, verified by both extension and content signature;
* macro-enabled workbooks are rejected outright;
* the sheet set, headers and limits are checked before any row is interpreted;
* formulas are rejected as values instead of being evaluated;
* external links are not resolved, and nothing is written anywhere.

Every refusal is reported as an issue rather than an exception, so a malformed workbook
answers with a list of problems. The only exceptions that can escape are programming
errors.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any, Iterable

from django.conf import settings
from openpyxl import load_workbook

from scheduling.services.imports.domain import (
    DATA_SHEETS,
    FILE_LEVEL_ROW,
    REQUIRED_COLUMNS,
    SHEET_ORDER,
    PlanRow,
    PlanWorkbook,
    columns_for,
)
from scheduling.services.imports.issues import ImportIssue, IssueCollector

#: Defaults, overridable through settings so a deployment can tighten them.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_SHEET_ROWS = 2000
DEFAULT_MAX_TOTAL_ROWS = 10000
DEFAULT_MAX_SCANNED_ROWS = 20000

#: Zip signature of every .xlsx and .xlsm file.
_ZIP_SIGNATURE = b"PK\x03\x04"

#: Members that mark a workbook as macro-enabled.
_MACRO_MEMBERS = ("xl/vbaProject.bin",)

_ACCEPTED_EXTENSIONS = (".xlsx",)
_REJECTED_EXTENSIONS = (".xls", ".xlsm", ".xltx", ".xltm", ".csv", ".zip")


def max_upload_bytes() -> int:
    """Largest accepted upload, from settings or the built-in default."""
    return int(getattr(settings, "SEMESTER_PLAN_IMPORT_MAX_BYTES", DEFAULT_MAX_BYTES))


def max_sheet_rows() -> int:
    """Largest accepted number of data rows in one sheet."""
    return int(
        getattr(settings, "SEMESTER_PLAN_IMPORT_MAX_SHEET_ROWS", DEFAULT_MAX_SHEET_ROWS)
    )


def max_total_rows() -> int:
    """Largest accepted number of data rows in one workbook."""
    return int(
        getattr(settings, "SEMESTER_PLAN_IMPORT_MAX_TOTAL_ROWS", DEFAULT_MAX_TOTAL_ROWS)
    )


def max_scanned_rows() -> int:
    """Largest accepted number of spreadsheet rows scanned per sheet.

    This bounds the work a single sheet can request before the row content is even
    considered; a sheet formatted far past its data cannot make the reader walk it.
    """
    return int(
        getattr(settings, "SEMESTER_PLAN_IMPORT_MAX_SCANNED_ROWS", DEFAULT_MAX_SCANNED_ROWS)
    )


def read_workbook(
    data: bytes, *, filename: str = ""
) -> tuple[PlanWorkbook, tuple[ImportIssue, ...]]:
    """Parse a workbook into rows, or report why it cannot be parsed.

    A rejected workbook comes back with an empty :class:`PlanWorkbook` and at least one
    blocking issue, so a caller never has to distinguish "no rows" from "not parsed".
    """
    collector = IssueCollector()
    if not _check_file(data, filename, collector):
        return PlanWorkbook(), collector.issues

    try:
        workbook = load_workbook(
            io.BytesIO(data),
            read_only=True,
            data_only=False,
            keep_links=False,
        )
    except Exception as exc:
        collector.file_level(
            "UNREADABLE_WORKBOOK",
            f"The workbook could not be read as an .xlsx file: {exc}",
        )
        return PlanWorkbook(), collector.issues

    try:
        return _parse_workbook(workbook, collector)
    finally:
        close = getattr(workbook, "close", None)
        if callable(close):
            close()


def _check_file(data: bytes, filename: str, collector: IssueCollector) -> bool:
    """Refuse a file that is not an accepted, non-macro .xlsx. Returns True to continue."""
    length = len(data)
    if length == 0:
        collector.file_level("NOT_A_WORKBOOK", "The uploaded file is empty.")
        return False
    if length > max_upload_bytes():
        collector.file_level(
            "FILE_TOO_LARGE",
            f"The workbook is {length} bytes; the limit is {max_upload_bytes()} bytes.",
        )
        return False

    lowered = str(filename or "").strip().lower()
    if any(lowered.endswith(extension) for extension in _REJECTED_EXTENSIONS):
        collector.file_level(
            "UNSUPPORTED_FILE_TYPE",
            "Only .xlsx workbooks are accepted; .xls, .xlsm, .csv and archives are not.",
        )
        return False
    if lowered and not any(
        lowered.endswith(extension) for extension in _ACCEPTED_EXTENSIONS
    ):
        collector.file_level(
            "UNSUPPORTED_FILE_TYPE",
            "Only .xlsx workbooks are accepted.",
        )
        return False

    if not data.startswith(_ZIP_SIGNATURE):
        collector.file_level(
            "NOT_A_WORKBOOK",
            "The uploaded content is not an .xlsx workbook.",
        )
        return False

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = set(archive.namelist())
    except zipfile.BadZipFile:
        collector.file_level(
            "NOT_A_WORKBOOK", "The uploaded content is not a readable archive."
        )
        return False

    if any(member in members for member in _MACRO_MEMBERS):
        collector.file_level(
            "MACRO_ENABLED_WORKBOOK",
            "Macro-enabled workbooks are not accepted; save the file as .xlsx.",
        )
        return False
    return True


def _parse_workbook(
    workbook: Any, collector: IssueCollector
) -> tuple[PlanWorkbook, tuple[ImportIssue, ...]]:
    """Check the sheet set and read the data sheets."""
    present = [str(name).strip() for name in getattr(workbook, "sheetnames", []) or []]
    present_set = set(present)

    for name in present:
        if name not in SHEET_ORDER:
            collector.add(
                sheet=name,
                row=FILE_LEVEL_ROW,
                code="UNEXPECTED_SHEET",
                message=(
                    f"Sheet '{name}' is not part of the semester teaching plan template."
                ),
            )
    for name in DATA_SHEETS:
        if name not in present_set:
            collector.add(
                sheet=name,
                row=FILE_LEVEL_ROW,
                code="MISSING_SHEET",
                message=f"Sheet '{name}' is missing from the workbook.",
            )

    if collector.error_count:
        # The structure is unusable, so no row is interpreted: reporting row issues
        # against a workbook whose sheets or headers are wrong would be noise.
        return PlanWorkbook(), collector.issues

    rows: dict[str, tuple[PlanRow, ...]] = {}
    scanned_total = 0
    data_total = 0
    for name in DATA_SHEETS:
        sheet_rows, scanned = _read_sheet(workbook[name], name, collector)
        scanned_total += scanned
        data_total += len(sheet_rows)
        if len(sheet_rows) > max_sheet_rows():
            collector.add(
                sheet=name,
                row=FILE_LEVEL_ROW,
                code="SHEET_ROW_LIMIT_EXCEEDED",
                message=(
                    f"Sheet '{name}' has {len(sheet_rows)} data rows; the limit is "
                    f"{max_sheet_rows()}."
                ),
            )
        rows[name] = tuple(sheet_rows)

    if data_total > max_total_rows():
        collector.file_level(
            "TOTAL_ROW_LIMIT_EXCEEDED",
            f"The workbook has {data_total} data rows; the limit is {max_total_rows()}.",
        )
    if collector.error_count:
        return PlanWorkbook(), collector.issues
    return PlanWorkbook(rows=rows), collector.issues


def _read_sheet(
    worksheet: Any, sheet_name: str, collector: IssueCollector
) -> tuple[list[PlanRow], int]:
    """Read one data sheet: header check first, then the rows.

    Returns the parsed rows and the number of spreadsheet rows scanned.
    """
    iterator = worksheet.iter_rows()
    header_row, header_cells = _next_content_row(iterator)
    scanned = 1 if header_cells is not None else 0
    if header_cells is None:
        collector.add(
            sheet=sheet_name,
            row=FILE_LEVEL_ROW,
            code="MISSING_HEADER",
            message=f"Sheet '{sheet_name}' has no header row.",
        )
        return [], scanned

    headers = [_cell_text(cell) for cell in header_cells]
    accepted = columns_for(sheet_name)
    seen: set[str] = set()
    indexed: dict[int, str] = {}
    for position, header in enumerate(headers):
        if not header:
            continue
        if header in seen:
            collector.add(
                sheet=sheet_name,
                row=header_row,
                code="DUPLICATE_HEADER",
                message=f"Column '{header}' appears more than once.",
                column=header,
            )
            continue
        seen.add(header)
        if header not in accepted:
            collector.add(
                sheet=sheet_name,
                row=header_row,
                code="UNKNOWN_HEADER",
                message=(
                    f"Column '{header}' is not part of sheet '{sheet_name}'. Expected: "
                    f"{', '.join(accepted)}."
                ),
                column=header,
            )
            continue
        indexed[position] = header

    for required in REQUIRED_COLUMNS.get(sheet_name, ()):
        if required not in seen:
            collector.add(
                sheet=sheet_name,
                row=header_row,
                code="MISSING_HEADER",
                message=f"Column '{required}' is required on sheet '{sheet_name}'.",
                column=required,
            )

    if any(issue.sheet == sheet_name and issue.is_error for issue in collector.issues):
        return [], scanned

    rows: list[PlanRow] = []
    scanned_limit = max_scanned_rows()
    for row_number, cells in _iter_rows(iterator):
        scanned += 1
        if scanned > scanned_limit:
            collector.add(
                sheet=sheet_name,
                row=row_number,
                code="SCANNED_ROW_LIMIT_EXCEEDED",
                message=(
                    f"Sheet '{sheet_name}' has more than {scanned_limit} rows; "
                    "the sheet is refused rather than scanned further."
                ),
            )
            break
        values: dict[str, str] = {}
        empty = True
        for position, cell in enumerate(cells):
            column = indexed.get(position)
            if column is None:
                continue
            if getattr(cell, "data_type", None) == "f":
                collector.add(
                    sheet=sheet_name,
                    row=row_number,
                    code="FORMULA_NOT_ALLOWED",
                    message=(
                        f"Cell {column} contains a formula. The import reads data only; "
                        "replace it with its value."
                    ),
                    column=column,
                )
                continue
            text = _cell_text(cell)
            if text:
                empty = False
            values[column] = text
        if empty:
            # A completely empty row - including one that only carries formatting - is
            # not data and is ignored, as are the trailing rows after it.
            continue
        rows.append(PlanRow(sheet=sheet_name, row=row_number, values=values))
    return rows, scanned


def _next_content_row(iterator: Iterable[Any]):
    """First row that has content, as ``(row number, cells)``, or ``(0, None)``."""
    for cells in iterator:
        cells = tuple(cells)
        if any(_cell_text(cell) for cell in cells):
            return _row_number(cells, fallback=0), cells
    return 0, None


def _iter_rows(iterator: Iterable[Any]):
    """Yield ``(row number, cells)`` for the remaining rows of a sheet."""
    fallback = 0
    for cells in iterator:
        cells = tuple(cells)
        fallback += 1
        yield _row_number(cells, fallback=fallback), cells


def _row_number(cells: tuple[Any, ...], *, fallback: int) -> int:
    """Spreadsheet row number of a row of cells, when the cells carry one."""
    for cell in cells:
        number = getattr(cell, "row", None)
        if isinstance(number, int):
            return number
    return fallback


def _cell_text(cell: Any) -> str:
    """Normalized text of one cell.

    Surrounding whitespace is trimmed - that is the whole of the documented
    normalization - and integral numbers lose their trailing ``.0`` so ``5`` and ``5.0``
    mean the same thing to the validator.
    """
    value = getattr(cell, "value", cell)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_SCANNED_ROWS",
    "DEFAULT_MAX_SHEET_ROWS",
    "DEFAULT_MAX_TOTAL_ROWS",
    "max_scanned_rows",
    "max_sheet_rows",
    "max_total_rows",
    "max_upload_bytes",
    "read_workbook",
]
