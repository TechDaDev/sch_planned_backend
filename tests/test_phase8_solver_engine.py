"""Unit tests for the Phase 8 CP-SAT scheduling engine.

These tests exercise the engine as a library: in-memory problems, no database, no
ORM, no API. The engine's own contract is what is under test here, including the
architectural rule that the solver package must stay importable without Django.

Planter's regression suite for phases 0-7 is separate; these tests were written by
the engine's implementer and are not independent acceptance evidence.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import sys

import pytest

from scheduling.services.solver import (
    DEFAULT_MAX_TIME_SECONDS,
    DEFAULT_NUM_SEARCH_WORKERS,
    DEFAULT_RANDOM_SEED,
    CpSatSchedulingEngine,
    PlacementCandidate,
    ResourceReservation,
    SessionDemand,
    SolverInputError,
    SolverOptions,
    SolverProblem,
    SolverStatus,
    solve,
)

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOLVER_PACKAGE_DIR = REPOSITORY_ROOT / "scheduling" / "services" / "solver"


# --- helpers ---------------------------------------------------------------


def session(session_id: str, component_id: str, ordinal: int = 1, **kwargs):
    return SessionDemand(
        session_id=session_id, component_id=component_id, ordinal=ordinal, **kwargs
    )


def candidate(
    candidate_id: str,
    session_id: str,
    *,
    day: int = 0,
    slots: tuple[int, ...] = (1,),
    room: int | None = None,
    instructors: tuple[int, ...] = (),
    groups: tuple[int, ...] = (),
    penalty: int = 0,
):
    return PlacementCandidate(
        candidate_id=candidate_id,
        session_id=session_id,
        day_of_week=day,
        slot_ids=slots,
        room_id=room,
        instructor_ids=instructors,
        student_group_ids=groups,
        penalty=penalty,
    )


def chosen(result) -> dict[str, tuple[int, ...]]:
    """Map session id to the slot ids the solver chose for it."""
    return {
        placement.session_id: tuple(placement.slot_ids)
        for placement in result.placements
    }


def no_shared_resource(result, resource: str) -> bool:
    """True when no (resource id, slot id) pair is used by two placements."""
    seen: set[tuple[int, int]] = set()
    for placement in result.placements:
        ids = getattr(placement, resource)
        if not isinstance(ids, tuple):
            ids = (ids,) if ids is not None else ()
        for slot_id in placement.slot_ids:
            for resource_id in ids:
                pair = (resource_id, slot_id)
                if pair in seen:
                    return False
                seen.add(pair)
    return True


# --- basic solving ---------------------------------------------------------


def test_one_session_one_candidate():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[candidate("k1", "s1", day=0, slots=(1,), room=5)],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placement_count == 1
    placement = result.placements[0]
    assert placement.session_id == "s1"
    assert placement.component_id == "c1"
    assert placement.candidate_id == "k1"
    assert placement.slot_ids == (1,)
    assert placement.room_id == 5
    assert result.objective_value == 0
    assert result.message


def test_one_session_several_candidates_picks_lowest_penalty():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            candidate("expensive", "s1", slots=(1,), penalty=5),
            candidate("cheap", "s1", slots=(2,), penalty=1),
            candidate("free", "s1", slots=(3,), penalty=0),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placements[0].candidate_id == "free"
    assert result.objective_value == 0


def test_lower_penalty_preferred_when_only_two_options():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            candidate("high", "s1", slots=(1,), penalty=9),
            candidate("low", "s1", slots=(2,), penalty=2),
        ],
    )
    result = solve(problem)
    assert result.placements[0].candidate_id == "low"
    assert result.objective_value == 2


def test_two_non_conflicting_sessions_are_both_placed():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("k1", "s1", slots=(1,), room=1, instructors=(1,), groups=(1,)),
            candidate("k2", "s2", slots=(1,), room=2, instructors=(2,), groups=(2,)),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placement_count == 2
    assert set(chosen(result)) == {"s1", "s2"}


def test_feasibility_only_problem_with_zero_penalties():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("k1", "s1", slots=(1,)),
            candidate("k2", "s2", slots=(2,)),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placement_count == 2
    assert result.objective_value == 0


# --- hard conflicts --------------------------------------------------------


def test_instructor_conflict_prevented():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("a1", "s1", slots=(1,), instructors=(7,), groups=(1,)),
            candidate("a2", "s1", slots=(2,), instructors=(7,), groups=(1,)),
            candidate("b1", "s2", slots=(1,), instructors=(7,), groups=(2,)),
            candidate("b2", "s2", slots=(2,), instructors=(7,), groups=(2,)),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placement_count == 2
    assert no_shared_resource(result, "instructor_ids")
    # The instructor is the only shared resource, so one session must move.
    assert len(set(chosen(result).values())) == 2


def test_assistant_instructor_also_conflicts():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            # Instructor 9 assists on the first session and also teaches the second.
            candidate("a1", "s1", slots=(1,), instructors=(1, 9), groups=(1,)),
            candidate("b1", "s2", slots=(1,), instructors=(9,), groups=(2,)),
            candidate("b2", "s2", slots=(2,), instructors=(9,), groups=(2,)),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    # The first session has a single option in slot 1, so the assistant forces the
    # second session to move.
    assert chosen(result) == {"s1": (1,), "s2": (2,)}


def test_group_conflict_prevented():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("a1", "s1", slots=(1,), groups=(3,)),
            candidate("a2", "s1", slots=(2,), groups=(3,)),
            candidate("b1", "s2", slots=(1,), groups=(3,)),
            candidate("b2", "s2", slots=(2,), groups=(3,)),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placement_count == 2
    assert no_shared_resource(result, "student_group_ids")


def test_multiple_groups_on_one_candidate_all_conflict():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("a1", "s1", slots=(1,), groups=(1, 2)),
            candidate("b1", "s2", slots=(1,), groups=(2,)),
            candidate("b2", "s2", slots=(2,), groups=(2,)),
        ],
    )
    result = solve(problem)
    assert chosen(result)["s1"] == (1,)
    assert chosen(result)["s2"] == (2,)


def test_room_conflict_prevented():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("a1", "s1", slots=(1,), room=4),
            candidate("a2", "s1", slots=(2,), room=4),
            candidate("b1", "s2", slots=(1,), room=4),
            candidate("b2", "s2", slots=(2,), room=4),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placement_count == 2
    assert no_shared_resource(result, "room_id")


def test_multi_slot_candidate_conflicts_on_any_overlapping_slot():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("a1", "s1", slots=(10, 11), instructors=(1,)),
            candidate("b1", "s2", slots=(11, 12), instructors=(1,)),
            candidate("b2", "s2", slots=(12, 13), instructors=(1,)),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    # (11, 12) overlaps slot 11, so the engine must take the later option.
    assert chosen(result) == {"s1": (10, 11), "s2": (12, 13)}
    assert result.placements[0].session_id == "s1"


def test_multi_slot_session_occupies_every_slot():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("a1", "s1", slots=(10, 11), room=1),
            candidate("b1", "s2", slots=(11,), room=1),
            candidate("b2", "s2", slots=(12,), room=1),
        ],
    )
    result = solve(problem)
    assert chosen(result) == {"s1": (10, 11), "s2": (12,)}


def test_component_self_conflict_is_enforced_as_invariant():
    # Nothing is shared except the component, so only the defensive component rule
    # can prevent the overlap; with a single option each the problem is infeasible.
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c1")],
        candidates=[
            candidate("a1", "s1", slots=(1,), instructors=(1,), groups=(1,), room=1),
            candidate("b1", "s2", slots=(1,), instructors=(2,), groups=(2,), room=2),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.placements == ()


# --- reservations ----------------------------------------------------------


def test_reservation_forces_candidate_off():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            candidate("blocked", "s1", slots=(5,), room=7),
            candidate("free", "s1", slots=(5,), room=8),
        ],
        reservations=[
            ResourceReservation(reservation_id="r1", slot_ids=(5,), room_ids=(7,))
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placements[0].candidate_id == "free"


def test_reservation_without_resources_closes_slots_entirely():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            candidate("slot5", "s1", slots=(5,), room=1),
            candidate("slot6", "s1", slots=(6,), room=1),
        ],
        reservations=[ResourceReservation(reservation_id="r1", slot_ids=(5,))],
    )
    result = solve(problem)
    assert result.placements[0].candidate_id == "slot6"


def test_multi_slot_reservation_blocks_any_overlap():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            candidate("overlaps", "s1", slots=(10,), instructors=(3,)),
            candidate("clear", "s1", slots=(20,), instructors=(3,)),
        ],
        reservations=[
            ResourceReservation(
                reservation_id="r1", slot_ids=(10, 11), instructor_ids=(3,)
            )
        ],
    )
    result = solve(problem)
    assert result.placements[0].candidate_id == "clear"


def test_reservation_can_make_problem_infeasible():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[candidate("only", "s1", slots=(5,), room=1)],
        reservations=[ResourceReservation(reservation_id="r1", slot_ids=(5,))],
    )
    result = solve(problem)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.placements == ()
    assert result.objective_value is None


# --- infeasible and empty problems ----------------------------------------


def test_infeasible_problem_reports_infeasible():
    # Two sessions, each with a single option, both needing instructor 1 in slot 1.
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("k1", "s1", slots=(1,), instructors=(1,), room=1),
            candidate("k2", "s2", slots=(1,), instructors=(1,), room=2),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.placements == ()
    assert result.objective_value is None
    assert "no conflict-free assignment" in result.message.lower()


def test_alternatives_for_one_session_never_conflict_with_each_other():
    # Both alternatives use the same instructor in the same slot, which is fine:
    # exactly one of them is ever selected, so they cannot collide.
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            candidate("k1", "s1", slots=(1,), instructors=(1,), room=1),
            candidate("k2", "s1", slots=(1,), instructors=(1,), room=2),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placement_count == 1


def test_empty_problem_solves_optimally_with_no_placements():
    result = solve(SolverProblem())
    assert result.status is SolverStatus.OPTIMAL
    assert result.placements == ()
    assert result.objective_value == 0
    assert result.placement_count == 0


def test_session_without_candidates_is_infeasible_and_named():
    problem = SolverProblem(
        sessions=[session("lonely", "c1")],
        candidates=[],
    )
    result = solve(problem)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.placements == ()
    assert "lonely" in result.message


# --- determinism and output shape -----------------------------------------


def test_repeated_runs_are_deterministic():
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2"), session("s3", "c3")],
        candidates=[
            candidate("a1", "s1", slots=(1,), instructors=(1,), penalty=3),
            candidate("a2", "s1", slots=(2,), instructors=(1,), penalty=0),
            candidate("b1", "s2", slots=(1,), instructors=(2,), penalty=1),
            candidate("b2", "s2", slots=(3,), instructors=(2,), penalty=4),
            candidate("c1", "s3", slots=(2,), instructors=(3,), penalty=2),
            candidate("c2", "s3", slots=(4,), instructors=(3,), penalty=2),
        ],
    )
    options = SolverOptions()
    snapshots = []
    for _ in range(5):
        result = CpSatSchedulingEngine().solve(problem, options)
        snapshots.append(
            json.dumps(
                {
                    "status": result.status.value,
                    "objective": result.objective_value,
                    "placements": [
                        placement.as_dict() for placement in result.placements
                    ],
                },
                sort_keys=True,
            )
        )
    assert len(set(snapshots)) == 1


def test_placements_are_sorted_deterministically():
    problem = SolverProblem(
        sessions=[
            session("s-late", "c-b", ordinal=2),
            session("s-early", "c-a", ordinal=1),
            session("s-late-2", "c-b", ordinal=1),
        ],
        candidates=[
            candidate("k-late", "s-late", day=3, slots=(30,)),
            candidate("k-early", "s-early", day=0, slots=(5,)),
            candidate("k-mid", "s-late-2", day=1, slots=(40,)),
        ],
    )
    result = solve(problem)
    keys = [
        (p.day_of_week, p.first_slot_id, p.component_id, p.session_id, p.candidate_id)
        for p in result.placements
    ]
    assert keys == sorted(keys)
    assert [p.candidate_id for p in result.placements] == ["k-early", "k-mid", "k-late"]


def test_result_is_json_serializable():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            PlacementCandidate(
                candidate_id="k1",
                session_id="s1",
                day_of_week=0,
                slot_ids=(1, 2),
                room_id=3,
                instructor_ids=(4,),
                student_group_ids=(5, 6),
                penalty=7,
                metadata={"source": "unit-test"},
            )
        ],
    )
    result = solve(problem)
    payload = json.dumps(result.as_dict())
    restored = json.loads(payload)["placements"][0]
    assert restored["session_id"] == "s1"
    assert restored["slot_ids"] == [1, 2]
    assert restored["room_id"] == 3
    assert restored["instructor_ids"] == [4]
    assert restored["student_group_ids"] == [5, 6]
    assert restored["penalty"] == 7
    assert restored["metadata"] == {"source": "unit-test"}


def test_default_options_are_reproducible():
    assert DEFAULT_MAX_TIME_SECONDS == 30.0
    assert DEFAULT_RANDOM_SEED == 0
    assert DEFAULT_NUM_SEARCH_WORKERS == 1
    options = SolverOptions()
    assert options.log_search_progress is False
    assert options.num_search_workers == 1


def test_time_limit_is_respected():
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[candidate("k1", "s1", slots=(1,))],
    )
    result = CpSatSchedulingEngine().solve(
        problem, SolverOptions(max_time_seconds=5.0, num_search_workers=1)
    )
    assert result.status is SolverStatus.OPTIMAL
    assert result.wall_time_seconds < 5.0


# --- input validation ------------------------------------------------------


@pytest.mark.parametrize(
    ("problem", "fragment"),
    [
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("k1", "missing")],
            ),
            "unknown session",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("", "s1")],
            ),
            "candidate_id must be a non-empty string",
        ),
        (
            SolverProblem(
                sessions=[SessionDemand(session_id="", component_id="c1")],
                candidates=[],
            ),
            "session_id must be a non-empty string",
        ),
        (
            SolverProblem(
                sessions=[SessionDemand(session_id="s1", component_id="")],
                candidates=[],
            ),
            "component_id must be a non-empty string",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1"), session("s1", "c1")],
                candidates=[candidate("k1", "s1")],
            ),
            "duplicate session_id",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("k1", "s1"), candidate("k1", "s1", slots=(2,))],
            ),
            "duplicate candidate_id",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("k1", "s1", slots=())],
            ),
            "at least one slot",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("k1", "s1", slots=(2, 2))],
            ),
            "repeats a slot id",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("k1", "s1", penalty=-1)],
            ),
            "must not be negative",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("k1", "s1", instructors=(1, 1))],
            ),
            "repeats an instructor id",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[
                    candidate("k1", "s1", slots=(1,)),
                    candidate("k2", "s1", slots=(1,)),
                ],
            ),
            "duplicates an existing placement",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1", candidate_ids=("k1", "other"))],
                candidates=[candidate("k1", "s1")],
            ),
            "declares candidate ids that do not match",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("k1", "s1")],
                reservations=[
                    ResourceReservation(reservation_id="r1", slot_ids=())
                ],
            ),
            "must cover at least one slot",
        ),
        (
            SolverProblem(
                sessions=[session("s1", "c1")],
                candidates=[candidate("k1", "s1", day=-1)],
            ),
            "day_of_week",
        ),
    ],
)
def test_invalid_input_is_rejected_with_clear_message(problem, fragment):
    with pytest.raises(SolverInputError) as error:
        solve(problem)
    assert fragment in str(error.value)


@pytest.mark.parametrize(
    "options",
    [
        SolverOptions(max_time_seconds=0),
        SolverOptions(max_time_seconds=-1),
        SolverOptions(num_search_workers=0),
        SolverOptions(random_seed=-5),
    ],
)
def test_invalid_options_are_rejected(options):
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[candidate("k1", "s1")],
    )
    with pytest.raises(SolverInputError):
        solve(problem, options)


def test_same_placement_with_different_penalty_is_rejected():
    # Penalty is a preference, not part of what and where a placement happens, so
    # the cheaper of two otherwise identical placements is the only real choice.
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            PlacementCandidate(
                candidate_id="expensive",
                session_id="s1",
                day_of_week=0,
                slot_ids=(10, 11),
                room_id=7,
                instructor_ids=(5,),
                student_group_ids=(3,),
                penalty=10,
            ),
            PlacementCandidate(
                candidate_id="cheap",
                session_id="s1",
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


def test_a_different_room_is_a_different_placement():
    # Only the physical placement defines identity, so a different room stays a
    # legitimate alternative rather than a duplicate.
    problem = SolverProblem(
        sessions=[session("s1", "c1")],
        candidates=[
            candidate("room-one", "s1", slots=(10,), instructors=(5,), room=1),
            candidate("room-two", "s1", slots=(10,), instructors=(5,), room=2),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.placement_count == 1


def test_non_problem_input_is_rejected():
    with pytest.raises(SolverInputError):
        solve({"sessions": []})  # type: ignore[arg-type]


def test_engine_does_not_raise_on_valid_but_unsatisfiable_input():
    # Guard against turning INFEASIBLE into an exception.
    problem = SolverProblem(
        sessions=[session("s1", "c1"), session("s2", "c2")],
        candidates=[
            candidate("p", "s1", slots=(1,), room=1),
            candidate("q", "s2", slots=(1,), room=1),
        ],
    )
    result = solve(problem)
    assert result.status is SolverStatus.INFEASIBLE


def test_status_map_covers_every_application_status():
    from scheduling.services.solver.solver import STATUS_MAP

    assert set(STATUS_MAP.values()) == set(SolverStatus)


# --- architecture guards ---------------------------------------------------


FORBIDDEN_IMPORT_ROOTS = {"django", "rest_framework", "rest_framework_simplejwt", "requests"}


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_solver_package_imports_no_django_or_drf():
    for path in sorted(SOLVER_PACKAGE_DIR.glob("*.py")):
        roots = _imported_roots(path)
        assert not (roots & FORBIDDEN_IMPORT_ROOTS), f"{path.name} imports {roots}"


def test_solver_package_does_not_import_project_models():
    for path in sorted(SOLVER_PACKAGE_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "scheduling.models" not in source
        assert "academics.models" not in source
        assert "resources.models" not in source


def test_solver_package_imports_without_django_settings():
    """The engine must be usable with no Django configuration at all."""
    env = dict(os.environ)
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.pop("DJANGO_SETTINGS_MODULE".lower(), None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import scheduling.services.solver as s; print(s.DEFAULT_NUM_SEARCH_WORKERS)",
        ],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "1"


def test_pre_scheduling_validator_still_reachable_through_package_root():
    # The lazy package exports must keep working for Phase 7 callers.
    from scheduling.services import PreSchedulingValidator, ValidationScope

    assert PreSchedulingValidator is not None
    assert ValidationScope.DEPARTMENT == "DEPARTMENT"
