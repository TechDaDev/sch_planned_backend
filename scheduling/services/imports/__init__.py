"""Phase 15 semester teaching plan import.

The package is layered so each decision has one home:

``domain``
    the workbook schema - sheet names, columns and parsed rows.
``issues``
    the row-level issue contract and its deterministic ordering.
``workbook``
    defensive reading of an untrusted upload: file type, macros, sheet and header
    checks, row limits, formula rejection.
``template``
    the generated, always-in-sync template workbook.
``validator``
    semantic validation against current database state, reusing the model rules.
``applier``
    the dependency-ordered writes of an already validated plan.
``service``
    the entry point both endpoints call.

What the import may touch is deliberately narrow: the academic teaching plan of one
department for one semester. It never writes a schedule, a version, a placement, a
workflow status, a publication, a sharing grant, a room, an instructor profile, a
calendar entry or a user.
"""

from scheduling.services.imports.applier import write_plan
from scheduling.services.imports.domain import DATA_SHEETS, SHEET_ORDER, PlanWorkbook
from scheduling.services.imports.issues import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    ImportIssue,
    IssueCollector,
)
from scheduling.services.imports.service import (
    SemesterPlanApplication,
    SemesterPlanImportService,
    SemesterPlanValidation,
)
from scheduling.services.imports.template import TEMPLATE_SHEET_NAMES, build_template
from scheduling.services.imports.validator import ValidatedPlan, validate_plan
from scheduling.services.imports.workbook import read_workbook

__all__ = [
    "DATA_SHEETS",
    "SHEET_ORDER",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "TEMPLATE_SHEET_NAMES",
    "ImportIssue",
    "IssueCollector",
    "PlanWorkbook",
    "SemesterPlanApplication",
    "SemesterPlanImportService",
    "SemesterPlanValidation",
    "ValidatedPlan",
    "build_template",
    "read_workbook",
    "validate_plan",
    "write_plan",
]
