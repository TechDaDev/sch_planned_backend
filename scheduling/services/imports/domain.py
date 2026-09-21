"""The semester teaching plan workbook schema and its parsed rows.

The import is deliberately narrow: one workbook prepares one department for one
semester. This module defines *what* the workbook may contain - the fixed sheet set,
each sheet's columns, and which of them are required - plus the parsed row objects the
validator consumes.

Nothing here touches the database or Django models. A row is a mapping of column name to
normalized string, with its original spreadsheet row number kept so every issue can point
a human at the exact cell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

#: Sheet names. They are part of the contract: an unknown sheet is rejected rather than
#: silently ignored, so a mistyped tab cannot hide rows.
SHEET_README = "README"
SHEET_COURSES = "Courses"
SHEET_STUDENT_GROUPS = "StudentGroups"
SHEET_OFFERINGS = "CourseOfferings"
SHEET_COMPONENTS = "TeachingComponents"
SHEET_COMPONENT_GROUPS = "ComponentGroups"
SHEET_ASSIGNMENTS = "TeachingAssignments"
SHEET_ROOM_REQUIREMENTS = "RoomRequirements"
SHEET_REQUIREMENT_CAPABILITIES = "RequirementCapabilities"

#: Sheets that carry data, in the order they are validated and reported. The order is
#: the issue ordering rule, so it must never change silently.
DATA_SHEETS = (
    SHEET_COURSES,
    SHEET_STUDENT_GROUPS,
    SHEET_OFFERINGS,
    SHEET_COMPONENTS,
    SHEET_COMPONENT_GROUPS,
    SHEET_ASSIGNMENTS,
    SHEET_ROOM_REQUIREMENTS,
    SHEET_REQUIREMENT_CAPABILITIES,
)

#: Every sheet the workbook may contain. ``README`` documents the template and is
#: ignored while parsing data.
SHEET_ORDER = (SHEET_README, *DATA_SHEETS)

#: Required columns per data sheet, in the documented order.
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    SHEET_COURSES: ("course_ref", "code", "name"),
    SHEET_STUDENT_GROUPS: (
        "group_ref",
        "program_code",
        "stage_number",
        "code",
        "name",
    ),
    SHEET_OFFERINGS: ("offering_ref", "course_ref"),
    SHEET_COMPONENTS: (
        "component_ref",
        "offering_ref",
        "component_type",
        "weekly_hours",
        "session_duration_hours",
    ),
    SHEET_COMPONENT_GROUPS: ("component_ref", "group_ref"),
    SHEET_ASSIGNMENTS: ("component_ref", "staff_code"),
    SHEET_ROOM_REQUIREMENTS: ("component_ref",),
    SHEET_REQUIREMENT_CAPABILITIES: ("component_ref", "capability_code"),
}

#: Optional columns per data sheet. A header outside both sets is an unknown header.
OPTIONAL_COLUMNS: dict[str, tuple[str, ...]] = {
    SHEET_COURSES: ("description",),
    SHEET_STUDENT_GROUPS: ("student_count", "parent_group_ref"),
    SHEET_OFFERINGS: ("offering_code",),
    SHEET_COMPONENTS: ("label",),
    SHEET_COMPONENT_GROUPS: (),
    SHEET_ASSIGNMENTS: ("assignment_role",),
    SHEET_ROOM_REQUIREMENTS: ("required_room_type_code", "minimum_capacity"),
    SHEET_REQUIREMENT_CAPABILITIES: (),
}

#: Workbook-local reference column of each sheet, used for cross-sheet validation.
REFERENCE_COLUMNS: dict[str, str] = {
    SHEET_COURSES: "course_ref",
    SHEET_STUDENT_GROUPS: "group_ref",
    SHEET_OFFERINGS: "offering_ref",
    SHEET_COMPONENTS: "component_ref",
}

#: Default used when the offering code column is present but empty.
DEFAULT_OFFERING_CODE = "MAIN"

#: Default used when the assignment role column is present but empty.
DEFAULT_ASSIGNMENT_ROLE = "PRIMARY"

#: Canonical values accepted for a teaching component type.
COMPONENT_TYPES = ("THEORY", "PRACTICAL")

#: Canonical values accepted for an assignment role.
ASSIGNMENT_ROLES = ("PRIMARY", "ASSISTANT")

#: Row number reported for an issue that concerns the workbook or a whole sheet rather
#: than one data row.
FILE_LEVEL_ROW = 0


def columns_for(sheet: str) -> tuple[str, ...]:
    """Every accepted column of one sheet, required columns first."""
    return REQUIRED_COLUMNS.get(sheet, ()) + OPTIONAL_COLUMNS.get(sheet, ())


def sheet_index(sheet: str) -> int:
    """Position of a sheet in the reporting order; unknown sheets sort last."""
    try:
        return SHEET_ORDER.index(sheet)
    except ValueError:
        return len(SHEET_ORDER)


@dataclass(frozen=True)
class PlanRow:
    """One non-empty data row of one sheet.

    ``values`` holds the normalized cell text for the columns that were present, so a
    missing optional column and an empty optional cell are the same thing to the
    validator: an empty string.
    """

    sheet: str
    row: int
    values: Mapping[str, str] = field(default_factory=dict)

    def get(self, column: str, default: str = "") -> str:
        """Normalized cell text, or ``default`` when the cell is empty."""
        value = self.values.get(column)
        if value is None or value == "":
            return default
        return value

    def as_dict(self) -> dict[str, Any]:
        return {"sheet": self.sheet, "row": self.row, "values": dict(self.values)}


@dataclass(frozen=True)
class PlanWorkbook:
    """Every parsed row of one workbook, grouped by sheet."""

    rows: Mapping[str, tuple[PlanRow, ...]] = field(default_factory=dict)

    def rows_for(self, sheet: str) -> tuple[PlanRow, ...]:
        return tuple(self.rows.get(sheet, ()))

    def row_count(self, sheet: str) -> int:
        return len(self.rows.get(sheet, ()))

    @property
    def total_rows(self) -> int:
        """Data rows across every sheet, excluding the header rows."""
        return sum(len(rows) for rows in self.rows.values())

    def is_empty(self) -> bool:
        return self.total_rows == 0


__all__ = [
    "ASSIGNMENT_ROLES",
    "COMPONENT_TYPES",
    "DATA_SHEETS",
    "DEFAULT_ASSIGNMENT_ROLE",
    "DEFAULT_OFFERING_CODE",
    "FILE_LEVEL_ROW",
    "OPTIONAL_COLUMNS",
    "PlanRow",
    "PlanWorkbook",
    "REFERENCE_COLUMNS",
    "REQUIRED_COLUMNS",
    "SHEET_ASSIGNMENTS",
    "SHEET_COMPONENT_GROUPS",
    "SHEET_COMPONENTS",
    "SHEET_COURSES",
    "SHEET_OFFERINGS",
    "SHEET_ORDER",
    "SHEET_README",
    "SHEET_REQUIREMENT_CAPABILITIES",
    "SHEET_ROOM_REQUIREMENTS",
    "SHEET_STUDENT_GROUPS",
    "columns_for",
    "sheet_index",
]
