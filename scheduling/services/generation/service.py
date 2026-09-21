"""Department schedule generation orchestration.

The pipeline is deliberately linear and each step is owned by one module:

1. **Gate** - the Phase 7 validator decides whether this semester and department
   are ready at all. An unready scope stops here; OR-Tools is never called.
2. **Build** - the Django adapter expands sessions and generates candidates.
   Sessions that received no candidate stop here too, because the engine cannot
   be asked a question that has no answer.
3. **Solve** - the pure CP-SAT engine chooses a globally conflict-free set.
4. **Preview** - placements are mapped to flat, readable rows.

Nothing is written at any point: a preview exists only in the response.
"""

from __future__ import annotations

from scheduling.services.generation.candidates import DepartmentProblemBuilder
from scheduling.services.generation.domain import (
    GenerationOutcome,
    GenerationSummary,
    ProblemBundle,
)
from scheduling.services.generation.issues import (
    REASON_CANDIDATE_BUILD_FAILED,
    REASON_VALIDATION_FAILED,
    GenerationIssueCode,
)
from scheduling.services.generation.preview import PreviewBuilder
from scheduling.services.solver import (
    DEFAULT_NUM_SEARCH_WORKERS,
    DEFAULT_RANDOM_SEED,
    CpSatSchedulingEngine,
    SolverOptions,
    SolverResult,
    SolverStatus,
)
from scheduling.services.validation.issues import EntityType, Severity, ValidationIssue
from scheduling.services.validation.validator import (
    PreSchedulingValidator,
    ValidationScope,
)

#: Failure statuses mapped to a stable issue code.
_SOLVER_STATUS_CODES: dict[SolverStatus, str] = {
    SolverStatus.INFEASIBLE: GenerationIssueCode.SOLVER_INFEASIBLE,
    SolverStatus.UNKNOWN: GenerationIssueCode.SOLVER_UNKNOWN,
    SolverStatus.MODEL_INVALID: GenerationIssueCode.SOLVER_MODEL_INVALID,
}

_SOLVER_STATUS_MESSAGES: dict[SolverStatus, str] = {
    SolverStatus.INFEASIBLE: "No globally conflict-free timetable could be found.",
    SolverStatus.UNKNOWN: (
        "No feasible timetable was returned within the solver limits."
    ),
    SolverStatus.MODEL_INVALID: (
        "The solver rejected the constructed model, which points at an engine "
        "defect rather than at this request."
    ),
}


class DepartmentScheduleGenerator:
    """Generates one department's weekly timetable preview for one semester."""

    def __init__(self, *, semester, department, max_time_seconds: float) -> None:
        self.semester = semester
        self.department = department
        self.max_time_seconds = max_time_seconds

    def generate(self) -> GenerationOutcome:
        """Run the whole pipeline and return the outcome.

        Every early exit is a normal, structured outcome: the caller never sees an
        exception for a request that was valid but cannot be scheduled.
        """
        validation = PreSchedulingValidator(
            semester=self.semester,
            scope=ValidationScope.DEPARTMENT,
            department=self.department,
        ).run()

        if not validation.ready:
            return self._outcome(
                validation=validation,
                rejected=True,
                reason=REASON_VALIDATION_FAILED,
                message=(
                    "Pre-scheduling validation reported blocking issues for this "
                    "department and semester, so no timetable was generated."
                ),
                generation_issues=(
                    ValidationIssue(
                        code=GenerationIssueCode.VALIDATION_FAILED,
                        severity=Severity.ERROR,
                        message=(
                            "The pre-scheduling validator is not ready for this "
                            "department and semester."
                        ),
                        entity_type=EntityType.SEMESTER,
                        entity_id=self.semester.pk,
                        details={
                            "department_id": self.department.pk,
                            "error_count": validation.summary.errors,
                            "warning_count": validation.summary.warnings,
                        },
                    ),
                ),
            )

        bundle = DepartmentProblemBuilder(
            semester=self.semester, department=self.department
        ).build()

        if not bundle.is_buildable:
            return self._outcome(
                validation=validation,
                rejected=True,
                reason=REASON_CANDIDATE_BUILD_FAILED,
                message=(
                    "No valid placement candidate could be built for every session, "
                    "so the solver was not invoked."
                ),
                diagnostics=bundle.diagnostics,
                generation_issues=self._sorted(bundle.issues),
            )

        solver_result = self._solve(bundle)

        if solver_result.status.has_placements:
            placements = PreviewBuilder(bundle).build(solver_result.placements)
            return self._outcome(
                validation=validation,
                solver=solver_result,
                generated=True,
                message="A conflict-free timetable preview was generated.",
                summary=GenerationSummary(
                    components=bundle.diagnostics.components,
                    sessions=bundle.diagnostics.sessions,
                    candidates=bundle.diagnostics.candidates,
                    placements=len(placements),
                ),
                placements=placements,
                diagnostics=bundle.diagnostics,
            )

        status = solver_result.status
        return self._outcome(
            validation=validation,
            solver=solver_result,
            message=_SOLVER_STATUS_MESSAGES.get(status, solver_result.message),
            diagnostics=bundle.diagnostics,
            generation_issues=(
                ValidationIssue(
                    code=_SOLVER_STATUS_CODES.get(
                        status, GenerationIssueCode.SOLVER_UNKNOWN
                    ),
                    severity=Severity.ERROR,
                    message=_SOLVER_STATUS_MESSAGES.get(status, solver_result.message),
                    entity_type=EntityType.SEMESTER,
                    entity_id=self.semester.pk,
                    details={
                        "department_id": self.department.pk,
                        "solver_status": status.value,
                    },
                ),
            ),
        )

    def _solve(self, bundle: ProblemBundle) -> SolverResult:
        """Run the pure engine with deterministic options.

        Callers control the time limit and nothing else: the seed, the single
        search worker and the quiet log are fixed here so two identical requests
        produce the same preview.
        """
        return CpSatSchedulingEngine().solve(
            bundle.solver_problem,
            SolverOptions(
                max_time_seconds=self.max_time_seconds,
                random_seed=DEFAULT_RANDOM_SEED,
                num_search_workers=DEFAULT_NUM_SEARCH_WORKERS,
                log_search_progress=False,
            ),
        )

    def _outcome(self, validation, **kwargs) -> GenerationOutcome:
        """Build an outcome with the request scope always attached."""
        return GenerationOutcome(
            semester=self.semester,
            department=self.department,
            validation=validation,
            **kwargs,
        )

    @staticmethod
    def _sorted(issues) -> tuple[ValidationIssue, ...]:
        """Deterministic issue order, matching the Phase 7 ordering rule."""
        return tuple(sorted(issues, key=lambda issue: issue.sort_key))


__all__ = ["DepartmentScheduleGenerator"]
