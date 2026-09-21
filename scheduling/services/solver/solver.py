"""The CP-SAT solve entry point.

``CpSatSchedulingEngine.solve`` is the whole public behaviour of Phase 8: take a
prepared discrete problem, build the model, solve it, and return plain data.

Statuses pass through unchanged, so a caller can always tell the difference
between "proven best", "good enough within the time limit", "impossible" and
"we ran out of time". With the default options (one worker, fixed seed) repeated
runs of the same problem return the same placements in the same order.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from scheduling.services.solver.domain import SolverOptions, SolverProblem
from scheduling.services.solver.model_builder import BuiltModel, build_model
from scheduling.services.solver.result import (
    ScheduledPlacement,
    SolverResult,
    SolverStatus,
)
from scheduling.services.solver.validator import (
    ValidatedProblem,
    validate_options,
    validate_problem,
)

#: OR-Tools states mapped to stable application values. Anything unexpected is
#: reported as UNKNOWN rather than guessed at.
STATUS_MAP: dict = {
    cp_model.OPTIMAL: SolverStatus.OPTIMAL,
    cp_model.FEASIBLE: SolverStatus.FEASIBLE,
    cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
    cp_model.MODEL_INVALID: SolverStatus.MODEL_INVALID,
    cp_model.UNKNOWN: SolverStatus.UNKNOWN,
}


class CpSatSchedulingEngine:
    """Conflict-free assignment of prepared session demands to placements."""

    def solve(
        self,
        problem: SolverProblem,
        options: SolverOptions | None = None,
    ) -> SolverResult:
        """Solve ``problem`` and return the outcome as plain data.

        Raises :class:`~scheduling.services.solver.errors.SolverInputError` when the
        problem or the options are not valid engine input. A problem that is valid
        but unsatisfiable returns ``INFEASIBLE`` instead of raising.
        """
        validated = validate_problem(problem)
        resolved_options = validate_options(options)
        built = build_model(validated)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = resolved_options.max_time_seconds
        solver.parameters.random_seed = resolved_options.random_seed
        solver.parameters.num_search_workers = resolved_options.num_search_workers
        solver.parameters.log_search_progress = resolved_options.log_search_progress

        raw_status = solver.Solve(built.model)
        status = STATUS_MAP.get(raw_status, SolverStatus.UNKNOWN)

        placements: tuple[ScheduledPlacement, ...] = ()
        objective_value: int | None = None
        if status.has_placements:
            placements = self._extract_placements(validated, built, solver)
            objective_value = (
                int(round(solver.ObjectiveValue())) if built.has_objective else 0
            )

        return SolverResult(
            status=status,
            placements=placements,
            objective_value=objective_value,
            wall_time_seconds=solver.WallTime(),
            num_conflicts=solver.NumConflicts(),
            num_branches=solver.NumBranches(),
            message=self._message(status, built),
        )

    @staticmethod
    def _extract_placements(
        validated: ValidatedProblem,
        built: BuiltModel,
        solver: cp_model.CpSolver,
    ) -> tuple[ScheduledPlacement, ...]:
        """Read the chosen candidates back as plain, deterministically ordered data.

        Iteration follows the validated candidate order, not OR-Tools variable
        order, and the result is sorted by the documented placement key.
        """
        placements: list[ScheduledPlacement] = []
        for candidate in validated.candidates:
            if solver.Value(built.variables[candidate.candidate_id]) != 1:
                continue
            placements.append(
                ScheduledPlacement(
                    session_id=candidate.session_id,
                    component_id=validated.component_by_session[candidate.session_id],
                    candidate_id=candidate.candidate_id,
                    day_of_week=candidate.day_of_week,
                    slot_ids=candidate.slot_ids,
                    room_id=candidate.room_id,
                    instructor_ids=candidate.instructor_ids,
                    student_group_ids=candidate.student_group_ids,
                    penalty=candidate.penalty,
                    metadata=candidate.metadata,
                )
            )
        placements.sort(key=lambda placement: placement.sort_key)
        return tuple(placements)

    @staticmethod
    def _message(status: SolverStatus, built: BuiltModel) -> str:
        """Short, deterministic explanation of the outcome."""
        if status is SolverStatus.OPTIMAL:
            message = "Optimal conflict-free assignment found."
        elif status is SolverStatus.FEASIBLE:
            message = (
                "Feasible assignment found within the time limit; optimality was "
                "not proven."
            )
        elif status is SolverStatus.INFEASIBLE:
            message = "No conflict-free assignment exists for this problem."
        elif status is SolverStatus.MODEL_INVALID:
            message = (
                "The solver rejected the constructed model. This points at an "
                "engine defect rather than at invalid application input."
            )
        else:
            message = (
                "The solver stopped without a proven answer, most likely because "
                "the time limit was reached."
            )
        if built.unplaceable_sessions:
            message += (
                " Sessions with no candidate placements: "
                + ", ".join(built.unplaceable_sessions)
                + "."
            )
        return message


def solve(
    problem: SolverProblem,
    options: SolverOptions | None = None,
) -> SolverResult:
    """Convenience wrapper around :meth:`CpSatSchedulingEngine.solve`."""
    return CpSatSchedulingEngine().solve(problem, options)


__all__ = ["STATUS_MAP", "CpSatSchedulingEngine", "solve"]
