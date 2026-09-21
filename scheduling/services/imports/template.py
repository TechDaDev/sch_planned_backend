"""The downloadable semester teaching plan template.

The template is generated rather than stored as a binary asset, so it can never drift
from the schema the reader enforces: the sheets and headers come from the same
constants the parser uses. Generation is deterministic - no timestamp is written - so
two downloads of an unchanged backend are byte-identical.

The data sheets hold headers only. Example rows live in the README sheet as
documentation, so validating the untouched template reports zero rows and applies
nothing. That keeps "download the template, upload it back" a safe no-op and lets a human
copy the examples deliberately.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from scheduling.services.imports.domain import (
    ASSIGNMENT_ROLES,
    COMPONENT_TYPES,
    DATA_SHEETS,
    DEFAULT_ASSIGNMENT_ROLE,
    DEFAULT_OFFERING_CODE,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    SHEET_README,
    columns_for,
)

#: Fixed document timestamp and zip entry timestamp. OpenPyXL would otherwise stamp the
#: current time into the archive, which would make two downloads of an unchanged backend
#: differ byte for byte.
FIXED_TIMESTAMP = datetime(1980, 1, 1, 0, 0, 0)

#: Document author written into the template properties.
TEMPLATE_AUTHOR = "College Academic Schedule Planner"

#: Sheet names of the template, in order. The README sheet documents the workbook and is
#: ignored while parsing data.
TEMPLATE_SHEET_NAMES = (SHEET_README, *DATA_SHEETS)

_HEADER_FILL = PatternFill("solid", fgColor="DDDDDD")
_HEADER_FONT = Font(bold=True)
_TITLE_FONT = Font(bold=True, size=13)
_SECTION_FONT = Font(bold=True)
_WRAP = Alignment(wrap_text=True, vertical="top")

#: Column widths of the README sheet and of the data sheets.
_README_WIDTHS = (34, 34, 34)
_DATA_WIDTHS = (18, 20, 20, 18, 18, 18, 22, 22, 22, 22)


def build_template() -> bytes:
    """Render the semester teaching plan template as .xlsx bytes.

    Deterministic: the document properties and the zip entry timestamps are fixed, so two
    downloads of an unchanged backend are byte-identical and a test can compare them.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.created = FIXED_TIMESTAMP
    workbook.properties.modified = FIXED_TIMESTAMP
    workbook.properties.creator = TEMPLATE_AUTHOR
    workbook.properties.lastModifiedBy = TEMPLATE_AUTHOR

    _write_readme(workbook.create_sheet(SHEET_README))
    for sheet_name in DATA_SHEETS:
        _write_data_sheet(workbook.create_sheet(sheet_name), sheet_name)

    stream = io.BytesIO()
    workbook.save(stream)
    return _fix_zip_timestamps(stream.getvalue())


def _fix_zip_timestamps(data: bytes) -> bytes:
    """Rewrite the archive with a fixed timestamp on every entry."""
    source = zipfile.ZipFile(io.BytesIO(data))
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in source.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = info.compress_type
            entry.external_attr = info.external_attr
            archive.writestr(entry, source.read(info.filename))
    source.close()
    return target.getvalue()


def _write_readme(sheet) -> None:
    """Documentation sheet: purpose, rules, sheets, columns and examples."""
    rows = _readme_rows()
    for row in rows:
        sheet.append(row)

    sheet.column_dimensions["A"].width = _README_WIDTHS[0]
    sheet.column_dimensions["B"].width = _README_WIDTHS[1]
    sheet.column_dimensions["C"].width = _README_WIDTHS[2]
    for row_index, row in enumerate(rows, start=1):
        sheet.cell(row=row_index, column=1).alignment = _WRAP
        if row_index == 1:
            sheet.cell(row=row_index, column=1).font = _TITLE_FONT
        elif row and str(row[0]).endswith(":"):
            sheet.cell(row=row_index, column=1).font = _SECTION_FONT
    sheet.freeze_panes = "A2"


def _readme_rows() -> list[tuple]:
    """Every documented row of the README sheet."""
    rows: list[tuple] = [
        ("Semester Teaching Plan Import - template", "", ""),
        ("", "", ""),
        (
            "Purpose:",
            "Prepare one department for one semester. The workbook creates courses, "
            "student groups, offerings, teaching components, group links, teaching "
            "assignments and room requirements.",
            "",
        ),
        (
            "How to use it:",
            "Fill the sheets, then upload the file to "
            "POST /api/imports/semester-plan/validate/ first, fix every ERROR, and only "
            "then upload it to POST /api/imports/semester-plan/apply/ with the same "
            "department and semester. Validation writes nothing.",
            "",
        ),
        (
            "Authorization:",
            "College administrators may import for any department; department "
            "administrators only for their own. Schedulers, viewers and instructors may "
            "not import.",
            "",
        ),
        ("", "", ""),
        ("Workbook rules:", "", ""),
        ("Create-only:", "Existing courses, groups and offerings are never overwritten.", ""),
        (
            "Data only:",
            "Formulas are rejected. Replace a formula with the value it produces.",
            "",
        ),
        (
            "File type:",
            "Save as .xlsx. Macros (.xlsm), .xls, .csv and archives are refused.",
            "",
        ),
        (
            "References:",
            "A *_ref column is a label that exists only inside this workbook. Use any "
            "short unique text (C01, G01, O01, TC01). Never put database ids in a "
            "reference column.",
            "",
        ),
        (
            "Existing data:",
            "program_code, stage_number, staff_code, required_room_type_code and "
            "capability_code must already exist. This import never creates instructors, "
            "rooms, room types, capabilities, programs, stages or calendar data.",
            "",
        ),
        (
            "Not imported:",
            "Schedule versions, timetable placements, workflow status, publication, "
            "instructor or room sharing, availability and the time grid.",
            "",
        ),
        ("", "", ""),
        ("Sheets and columns:", "Required", "Optional"),
    ]

    for sheet_name in DATA_SHEETS:
        rows.append(
            (
                f"{sheet_name}:",
                ", ".join(REQUIRED_COLUMNS.get(sheet_name, ())) or "-",
                ", ".join(OPTIONAL_COLUMNS.get(sheet_name, ())) or "-",
            )
        )

    rows.extend(
        [
            ("", "", ""),
            (
                "Value notes:",
                "component_type is one of "
                f"{', '.join(COMPONENT_TYPES)}. assignment_role is one of "
                f"{', '.join(ASSIGNMENT_ROLES)} and defaults to "
                f"{DEFAULT_ASSIGNMENT_ROLE}. offering_code defaults to "
                f"{DEFAULT_OFFERING_CODE}. student_count defaults to 0 when blank. "
                "weekly_hours and session_duration_hours must be positive and the weekly "
                "hours must divide into whole sessions.",
                "",
            ),
            (
                "Row limits:",
                "Blank rows are ignored. Keep the workbook well under a few thousand rows; "
                "an oversized or over-long workbook is refused before it is scanned.",
                "",
            ),
            ("", "", ""),
            ("Example (documentation only - do not paste this block into a sheet):", "", ""),
        ]
    )

    rows.extend(_example_rows())
    return rows


def _example_rows() -> list[tuple]:
    """A small worked example, quoted sheet by sheet."""
    return [
        ("Courses", "course_ref=C01, code=BIO201, name=Molecular Biology", ""),
        ("", "course_ref=C02, code=BIO202, name=Cell Biology", ""),
        (
            "StudentGroups",
            "group_ref=G01, program_code=BIO, stage_number=1, code=BIO1A, "
            "name=Biology Stage 1 A, student_count=25",
            "",
        ),
        (
            "CourseOfferings",
            "offering_ref=O01, course_ref=C01, offering_code=MAIN",
            "",
        ),
        (
            "TeachingComponents",
            "component_ref=TC01, offering_ref=O01, component_type=THEORY, "
            "label=Lecture, weekly_hours=2, session_duration_hours=1",
            "",
        ),
        ("ComponentGroups", "component_ref=TC01, group_ref=G01", ""),
        ("TeachingAssignments", "component_ref=TC01, staff_code=I-100, assignment_role=PRIMARY", ""),
        ("RoomRequirements", "component_ref=TC01, required_room_type_code=LECT, minimum_capacity=30", ""),
        ("RequirementCapabilities", "component_ref=TC01, capability_code=PROJECTOR", ""),
    ]


def _write_data_sheet(sheet, sheet_name: str) -> None:
    """Header row plus presentation only: the sheet starts empty."""
    headers = columns_for(sheet_name)
    sheet.append(headers)
    for index, width in enumerate(_DATA_WIDTHS[: len(headers)], start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for index in range(1, len(headers) + 1):
        cell = sheet.cell(row=1, column=index)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"


__all__ = ["FIXED_TIMESTAMP", "TEMPLATE_SHEET_NAMES", "build_template"]
