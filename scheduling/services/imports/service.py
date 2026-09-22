"""The semester teaching plan import service.

One entry point, two endpoints: ``validate`` reports what is wrong and writes nothing,
``apply`` runs exactly the same reading and validation and then stores the plan in a
single transaction. Because ``apply`` re-reads and re-validates the upload it was given,
a validate response from an earlier request is never trusted - there is no token to hand
back, and nothing can be applied against stale database state.

The service also owns the scope decision: the department and semester come from the
authorized request, never from the workbook, so no spreadsheet can choose to import into
another department or another semester.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from scheduling.services.audit import record_semester_plan_import
from scheduling.services.imports.applier import write_plan
from scheduling.services.imports.domain import DATA_SHEETS, PlanWorkbook
from scheduling.services.imports.issues import IssueCollector
from scheduling.services.imports.validator import ValidatedPlan, validate_plan
from scheduling.services.imports.workbook import max_upload_bytes, read_workbook


#: Count keys of an apply response, in the documented order. A refused apply reports
#: every key as zero rather than omitting the block.
CREATED_KEYS = (
    "courses",
    "student_groups",
    "offerings",
    "components",
    "component_group_links",
    "teaching_assignments",
    "room_requirements",
    "requirement_capabilities",
)


@dataclass(frozen=True)
class SemesterPlanValidation:
    """Outcome of one reading plus validation pass."""

    workbook: PlanWorkbook
    collector: IssueCollector
    plan: ValidatedPlan | None

    @property
    def valid(self) -> bool:
        """True when the workbook may be applied: no blocking issue."""
        return self.plan is not None and self.collector.valid

    @property
    def rows(self) -> int:
        return self.workbook.total_rows

    def summary(self) -> dict[str, int]:
        """Counts a human needs before reading the issue list."""
        sheets = sum(1 for sheet in DATA_SHEETS if sheet in self.workbook.rows)
        return {
            "sheets": sheets,
            "rows": self.rows,
            "errors": self.collector.error_count,
            "warnings": self.collector.warning_count,
        }

    def as_dict(self) -> dict[str, Any]:
        """The validate response body."""
        return {
            "valid": self.valid,
            "summary": self.summary(),
            "issues": [
                issue.as_dict() for issue in self.collector.issues
            ],
        }


@dataclass(frozen=True)
class SemesterPlanApplication:
    """Outcome of one apply request: the validation, plus what was written."""

    validation: SemesterPlanValidation
    created: dict[str, int]

    @property
    def applied(self) -> bool:
        return self.validation.valid

    def as_dict(self, *, department=None, semester=None) -> dict[str, Any]:
        """The apply response body: scope, counts and any warnings.

        The counts keep the documented shape even when nothing was written, so a client
        can read the same keys whether the apply succeeded or was refused.
        """
        body: dict[str, Any] = {
            "applied": self.applied,
            "created": {
                key: int(self.created.get(key, 0)) for key in CREATED_KEYS
            },
            "warnings": [
                issue.as_dict() for issue in self.validation.collector.warnings
            ],
        }
        if department is not None:
            body["department"] = {
                "id": department.pk,
                "code": department.code,
                "name": department.name,
            }
        if semester is not None:
            body["semester"] = {
                "id": semester.pk,
                "number": semester.number,
                "academic_year": str(semester.academic_year),
            }
        if not self.applied:
            # An apply that wrote nothing still owes the caller the reasons.
            body["summary"] = self.validation.summary()
            body["issues"] = [
                issue.as_dict() for issue in self.validation.collector.errors
            ]
        return body


class SemesterPlanImportService:
    """Reads, validates and optionally applies one semester teaching plan workbook."""

    def __init__(self, *, user, department, semester, upload) -> None:
        self.user = user
        self.department = department
        self.semester = semester
        self.upload = upload
        self._data: bytes | None = None
        self._filename = ""
        self._oversized: int | None = None

    @property
    def cross_department(self) -> bool:
        """Whether the caller may touch another department's programs and students."""
        return bool(self.user.has_cross_department_access)

    # --- reading ----------------------------------------------------------

    def _read_bytes(self) -> bytes:
        """Buffer the upload once, so validate and apply see the same content.

        The declared size is checked before the file is buffered, so an oversized upload
        is refused without ever being read into memory.
        """
        if self._data is None:
            size = getattr(self.upload, "size", None)
            if size is not None and int(size) > max_upload_bytes():
                self._oversized = int(size)
                self._filename = str(getattr(self.upload, "name", "") or "")
                self._data = b""
                return self._data
            data = self.upload.read()
            self._data = data if isinstance(data, bytes) else bytes(data)
            self._filename = str(getattr(self.upload, "name", "") or "")
        return self._data

    def read(self) -> tuple[PlanWorkbook, IssueCollector]:
        """Parse the upload into rows, or into the issues that prevent parsing."""
        collector = IssueCollector()
        data = self._read_bytes()
        if self._oversized is not None:
            collector.file_level(
                "FILE_TOO_LARGE",
                (
                    f"The workbook is {self._oversized} bytes; the limit is "
                    f"{max_upload_bytes()} bytes."
                ),
            )
            return PlanWorkbook(), collector
        workbook, issues = read_workbook(data, filename=self._filename)
        collector.extend(issues)
        if not isinstance(workbook, PlanWorkbook):
            workbook = PlanWorkbook()
        return workbook, collector

    def validate(self) -> SemesterPlanValidation:
        """Full validation against current database state. Writes nothing."""
        workbook, collector = self.read()
        if collector.error_count:
            return SemesterPlanValidation(
                workbook=workbook, collector=collector, plan=None
            )
        plan, plan_collector = validate_plan(
            workbook=workbook,
            department=self.department,
            semester=self.semester,
            cross_department=self.cross_department,
        )
        return SemesterPlanValidation(
            workbook=workbook, collector=plan_collector, plan=plan
        )

    # --- applying ---------------------------------------------------------

    def apply(self) -> SemesterPlanApplication:
        """Validate and, only if nothing blocks, write the whole plan atomically.

        The transaction covers validation *and* the writes, so the uniqueness decisions
        are taken against the same database state that is then modified. Any failure -
        including one raised by a database constraint - rolls back every row this import
        created.
        """
        with transaction.atomic():
            validation = self.validate()
            if not validation.valid:
                return SemesterPlanApplication(validation=validation, created={})
            created = write_plan(validation.plan)
            # Inside the same transaction as the created rows: a refused import records
            # nothing, and an applied import cannot go unaudited.
            record_semester_plan_import(
                actor=self.user,
                department=self.department,
                semester=self.semester,
                created=created,
                warning_count=validation.collector.warning_count,
            )
        return SemesterPlanApplication(validation=validation, created=created)


__all__ = [
    "CREATED_KEYS",
    "SemesterPlanApplication",
    "SemesterPlanImportService",
    "SemesterPlanValidation",
]
