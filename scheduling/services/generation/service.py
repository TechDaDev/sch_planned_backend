"""Schedule generation orchestration.

The pipeline is deliberately linear and each step is owned by one module:

1. **Gate** - the Phase 7 validator decides whether this semester and scope are
   ready at all. An unready scope stops here; OR-Tools is never called.
2. **Build** - the Django adapter expands sessions and generates candidates.
   Sessions that received no candidate stop here too, because the engine cannot
   be asked a question that has no answer.
3. **Solve** - the pure CP-SAT engine chooses a globally conflict-free set.
4. **Preview** - placements are mapped to flat, readable rows.

Two scopes share that pipeline. :class:`DepartmentScheduleGenerator` covers one
department and is what the Phase 9 endpoint calls. :class:`CollegeScheduleGenerator`
covers every department of the semester in *one* problem, so a shared instructor,
a shared room or a joint student group cannot be double-booked across departments.

Nothing is written at any point: a preview exists only in the response.
"""

from __future__ import annotations

from scheduling.services.generation.candidates import (
    CollegeProblemBuilder,
    DepartmentProblemBuilder,
)
from scheduling.services.generation.domain import (
    CollegeGenerationSummary,
    DepartmentGenerationSummary,
    GenerationOutcome,
    GenerationSummary,
    ProblemBundle,
)
from scheduling.services.generation.issues import (
    REASON_CANDIDATE_BUILD_FAILED,
    REASON_VALIDATION_FAILED,
    GenerationIssueCode,
)
from scheduling.services.generation.preview import (
    CollegePreviewBuilder,
    PreviewBuilder,
)
from scheduling.services.solver import (
    DEFAULT_NUM_SEARCH_WORKERS,
    DEFAULT_RANDOM_SEED,
    CpSatSchedulingEngine,
    SolverOptions,
    SolverResult,
    SolverStatus,
)
from scheduling.services.validation import ValidationScope
from scheduling.services.validation.issues import EntityType, Severity, ValidationIssue
from scheduling.services.validation.validator import PreSchedulingValidator

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


class ScheduleGenerationPipeline:
    """The validate, build, solve, preview pipeline shared by both scopes.

    Subclasses decide the validation scope, the problem builder, the preview
    builder and the summary shape; the sequence of steps and the shape of every
    early exit stay identical for department and college generation.
    """

    #: Validation scope this generator runs the Phase 7 gate under.
    scope: str = ValidationScope.DEPARTMENT

    #: How the scope is named in human-readable messages.
    scope_description: str = "this department"

    def __init__(self, *, semester, max_time_seconds: float, department=None) -> None:
        self.semester = semester
        self.department = department
        self.max_time_seconds = max_time_seconds

    # --- subclass hooks ----------------------------------------------------

    def _build_bundle(self) -> ProblemBundle:
        raise NotImplementedError

    def _preview_builder(self, bundle: ProblemBundle) -> PreviewBuilder:
        return PreviewBuilder(bundle)

    def _summary(self, bundle: ProblemBundle, placement_count: int):
        raise NotImplementedError

    def _scope_details(self) -> dict:
        """Scope identity added to issue details, empty for college-wide runs."""
        raise NotImplementedError

    def _outcome_scope(self) -> str | None:
        """``scope`` field of the outcome, ``None`` when the API has no such field."""
        raise NotImplementedError

    def _department_summaries(self, bundle: ProblemBundle, placements) -> tuple:
        return ()

    # --- entry point -------------------------------------------------------

    def generate(self) -> GenerationOutcome:
        """Run the whole pipeline and return the outcome.

        Every early exit is a normal, structured outcome: the caller never sees an
        exception for a request that was valid but cannot be scheduled.
        """
        validation = PreSchedulingValidator(
            semester=self.semester,
            scope=self.scope,
            department=self.department,
        ).run()

        if not validation.ready:
            return self._outcome(
                validation=validation,
                rejected=True,
                reason=REASON_VALIDATION_FAILED,
                message=(
                    "Pre-scheduling validation reported blocking issues for "
                    f"{self.scope_description} and semester, so no timetable was "
                    "generated."
                ),
                generation_issues=(
                    ValidationIssue(
                        code=GenerationIssueCode.VALIDATION_FAILED,
                        severity=Severity.ERROR,
                        message=(
                            "The pre-scheduling validator is not ready for "
                            f"{self.scope_description} and semester."
                        ),
                        entity_type=EntityType.SEMESTER,
                        entity_id=self.semester.pk,
                        details={
                            **self._scope_details(),
                            "error_count": validation.summary.errors,
                            "warning_count": validation.summary.warnings,
                        },
                    ),
                ),
            )

        bundle = self._build_bundle()

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
            placements = self._preview_builder(bundle).build(solver_result.placements)
            return self._outcome(
                validation=validation,
                solver=solver_result,
                generated=True,
                message="A conflict-free timetable preview was generated.",
                summary=self._summary(bundle, len(placements)),
                placements=placements,
                department_summaries=self._department_summaries(bundle, placements),
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
                        **self._scope_details(),
                        "solver_status": status.value,
                    },
                ),
            ),
        )

    def _solve(self, bundle: ProblemBundle) -> SolverResult:
        """Run the pure engine with deterministic options.

        Callers control the time limit and nothing else: the seed, the single
        search worker and the quiet log are fixed here so two identical requests
        produce the same preview. Determinism matters even more college-wide, where
        a shared instructor or room can otherwise move between runs.
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
        """Build an outcome with the request identity always attached."""
        return GenerationOutcome(
            semester=self.semester,
            department=self.department,
            scope=self._outcome_scope(),
            validation=validation,
            **kwargs,
        )

    @staticmethod
    def _sorted(issues) -> tuple[ValidationIssue, ...]:
        """Deterministic issue order, matching the Phase 7 ordering rule."""
        return tuple(sorted(issues, key=lambda issue: issue.sort_key))


class DepartmentScheduleGenerator(ScheduleGenerationPipeline):
    """Generates one department's weekly timetable preview for one semester."""

    scope = ValidationScope.DEPARTMENT
    scope_description = "this department"

    def __init__(self, *, semester, department, max_time_seconds: float) -> None:
        super().__init__(
            semester=semester,
            department=department,
            max_time_seconds=max_time_seconds,
        )

    def _build_bundle(self) -> ProblemBundle:
        return DepartmentProblemBuilder(
            semester=self.semester, department=self.department
        ).build()

    def _summary(self, bundle: ProblemBundle, placement_count: int) -> GenerationSummary:
        return GenerationSummary(
            components=bundle.diagnostics.components,
            sessions=bundle.diagnostics.sessions,
            candidates=bundle.diagnostics.candidates,
            placements=placement_count,
        )

    def _scope_details(self) -> dict:
        return {"department_id": self.department.pk}

    def _outcome_scope(self) -> str | None:
        """The Phase 9 response has no scope field, so it stays unset."""
        return None


class CollegeScheduleGenerator(ScheduleGenerationPipeline):
    """Generates a college-wide weekly timetable preview for one semester.

    Every active component of the semester is part of one problem, so the engine
    resolves shared-instructor, shared-room and joint-group collisions globally.
    Solving each department separately and merging the answers cannot do that, and
    is deliberately not what happens here.

    The Phase 7 gate runs with ``COLLEGE`` scope, which is the check that covers
    all managing departments at once.
    """

    scope = ValidationScope.COLLEGE
    scope_description = "the whole college"

    def __init__(self, *, semester, max_time_seconds: float) -> None:
        super().__init__(
            semester=semester, department=None, max_time_seconds=max_time_seconds
        )

    def _build_bundle(self) -> ProblemBundle:
        return CollegeProblemBuilder(semester=self.semester).build()

    def _preview_builder(self, bundle: ProblemBundle) -> PreviewBuilder:
        return CollegePreviewBuilder(bundle)

    def _summary(
        self, bundle: ProblemBundle, placement_count: int
    ) -> CollegeGenerationSummary:
        return CollegeGenerationSummary(
            departments=bundle.diagnostics.departments,
            components=bundle.diagnostics.components,
            sessions=bundle.diagnostics.sessions,
            candidates=bundle.diagnostics.candidates,
            placements=placement_count,
        )

    def _scope_details(self) -> dict:
        """A college-wide run has no single department to name."""
        return {}

    def _outcome_scope(self) -> str | None:
        return ValidationScope.COLLEGE

    def _department_summaries(self, bundle: ProblemBundle, placements) -> tuple:
        """Per-department counts of the finished college-wide run.

        Build counts come from the adapter's per-department counters and placement
        counts from the preview rows, so a joint component that serves foreign
        student groups is still counted once, for the department that manages it.
        The rows keep the adapter's documented order: department code, then id.
        """
        placements_per_department: dict[int, int] = {}
        for preview in placements:
            department = preview.managing_department
            if department is None:
                continue
            placements_per_department[department.id] = (
                placements_per_department.get(department.id, 0) + 1
            )

        return tuple(
            DepartmentGenerationSummary(
                department=row.department,
                components=row.components,
                sessions=row.sessions,
                candidates=row.candidates,
                placements=placements_per_department.get(row.department.id, 0),
            )
            for row in bundle.diagnostics.department_breakdown
        )


__all__ = [
    "CollegeScheduleGenerator",
    "DepartmentScheduleGenerator",
    "ScheduleGenerationPipeline",
]
