"""Independent acceptance tests for Phase 8 CP-SAT solver."""

import pytest

from scheduling.services.solver import (
    PlacementCandidate,
    SessionDemand,
    SolverInputError,
    SolverProblem,
    solve,
)


def test_same_placement_with_different_cost_is_not_a_second_valid_choice():
    """Penalty changes preference, never physical placement identity."""
    problem = SolverProblem(
        sessions=[SessionDemand(session_id="session-1", component_id="component-1")],
        candidates=[
            PlacementCandidate(
                candidate_id="same-placement-high",
                session_id="session-1",
                day_of_week=0,
                slot_ids=(10, 11),
                room_id=7,
                instructor_ids=(5,),
                student_group_ids=(3,),
                penalty=10,
            ),
            PlacementCandidate(
                candidate_id="same-placement-low",
                session_id="session-1",
                day_of_week=0,
                slot_ids=(10, 11),
                room_id=7,
                instructor_ids=(5,),
                student_group_ids=(3,),
                penalty=2,
            ),
        ],
    )

    with pytest.raises(SolverInputError, match="duplicates an existing placement"):
        solve(problem)
