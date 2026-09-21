"""CP-SAT scheduling engine (Phase 8).

A reusable, database-free core that turns an already prepared discrete scheduling
problem into a conflict-free assignment. It knows nothing about Django, DRF, the
academic models or the pre-scheduling validator: callers hand it session demands,
their feasible placement candidates and any fixed occupancy to respect.

Public surface::

    from scheduling.services.solver import SolverProblem, solve

    result = solve(SolverProblem(sessions=..., candidates=...))

Typical use in later phases is ``validate -> build candidates -> call engine``,
with the adapter owning everything the engine deliberately does not decide.
"""

from scheduling.services.solver.domain import (
    DEFAULT_MAX_TIME_SECONDS,
    DEFAULT_NUM_SEARCH_WORKERS,
    DEFAULT_RANDOM_SEED,
    PlacementCandidate,
    ResourceReservation,
    SessionDemand,
    SolverOptions,
    SolverProblem,
)
from scheduling.services.solver.errors import SolverError, SolverInputError
from scheduling.services.solver.model_builder import BuiltModel, build_model
from scheduling.services.solver.result import (
    ScheduledPlacement,
    SolverResult,
    SolverStatus,
)
from scheduling.services.solver.solver import (
    STATUS_MAP,
    CpSatSchedulingEngine,
    solve,
)
from scheduling.services.solver.validator import (
    ValidatedProblem,
    validate_options,
    validate_problem,
)

__all__ = [
    "DEFAULT_MAX_TIME_SECONDS",
    "DEFAULT_NUM_SEARCH_WORKERS",
    "DEFAULT_RANDOM_SEED",
    "STATUS_MAP",
    "BuiltModel",
    "CpSatSchedulingEngine",
    "PlacementCandidate",
    "ResourceReservation",
    "ScheduledPlacement",
    "SessionDemand",
    "SolverError",
    "SolverInputError",
    "SolverOptions",
    "SolverProblem",
    "SolverResult",
    "SolverStatus",
    "ValidatedProblem",
    "build_model",
    "solve",
    "validate_options",
    "validate_problem",
]
