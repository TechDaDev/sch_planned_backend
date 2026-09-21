"""Input validation for the CP-SAT scheduling engine.

Bad application input must fail here, with a clear message, before a CP-SAT model
exists. Otherwise a mistyped candidate id surfaces as an OR-Tools error or, worse,
as a silently different problem.

Validation also produces the deterministic indexes the model builder uses, so the
builder never has to search a list and never depends on dictionary order.

Two documented behaviours worth noting:

* **A session with no candidates is not an input error.** The problem is valid
  but unsatisfiable, so it is modelled as infeasible and the solve returns
  ``INFEASIBLE``.
* **Exact duplicate candidates for one session are rejected.** Two identical
  options for the same session carry no information and only enlarge the search,
  so they are refused rather than silently deduplicated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from scheduling.services.solver.domain import (
    PlacementCandidate,
    ResourceReservation,
    SessionDemand,
    SolverOptions,
    SolverProblem,
)
from scheduling.services.solver.errors import SolverInputError


@dataclass(frozen=True)
class ValidatedProblem:
    """A validated problem plus the indexes the model builder relies on."""

    sessions: tuple[SessionDemand, ...]
    candidates: tuple[PlacementCandidate, ...]
    reservations: tuple[ResourceReservation, ...]
    candidates_by_session: Mapping[str, tuple[PlacementCandidate, ...]]
    candidates_by_id: Mapping[str, PlacementCandidate]
    component_by_session: Mapping[str, str]

    @property
    def is_empty(self) -> bool:
        return not self.sessions


def validate_options(options: SolverOptions | None) -> SolverOptions:
    """Return usable options, rejecting impossible run configurations."""
    if options is None:
        return SolverOptions()
    if not isinstance(options, SolverOptions):
        raise SolverInputError(
            "options must be a SolverOptions instance, "
            f"got {type(options).__name__}."
        )
    if not isinstance(options.max_time_seconds, (int, float)) or isinstance(
        options.max_time_seconds, bool
    ):
        raise SolverInputError("max_time_seconds must be a number.")
    if options.max_time_seconds <= 0:
        raise SolverInputError("max_time_seconds must be greater than zero.")
    if not isinstance(options.num_search_workers, int) or isinstance(
        options.num_search_workers, bool
    ):
        raise SolverInputError("num_search_workers must be an integer.")
    if options.num_search_workers < 1:
        raise SolverInputError("num_search_workers must be at least 1.")
    if not isinstance(options.random_seed, int) or isinstance(
        options.random_seed, bool
    ):
        raise SolverInputError("random_seed must be an integer.")
    if options.random_seed < 0:
        raise SolverInputError("random_seed must not be negative.")
    return options


def _require_non_empty_string(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SolverInputError(f"{field_name} must be a non-empty string.")
    return value


def _require_int(value, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SolverInputError(f"{field_name} must be an integer.")
    return value


def _require_positive_int(value, field_name: str) -> int:
    _require_int(value, field_name)
    if value < 1:
        raise SolverInputError(f"{field_name} must be a positive integer.")
    return value


def _validate_sessions(sessions) -> tuple[SessionDemand, ...]:
    seen: set[str] = set()
    for session in sessions:
        if not isinstance(session, SessionDemand):
            raise SolverInputError(
                "every session must be a SessionDemand instance, "
                f"got {type(session).__name__}."
            )
        _require_non_empty_string(session.session_id, "session_id")
        _require_non_empty_string(session.component_id, "component_id")
        _require_int(session.ordinal, f"ordinal of session '{session.session_id}'")
        if session.ordinal < 0:
            raise SolverInputError(
                f"ordinal of session '{session.session_id}' must not be negative."
            )
        if session.session_id in seen:
            raise SolverInputError(
                f"duplicate session_id '{session.session_id}'."
            )
        seen.add(session.session_id)
    return tuple(sorted(sessions, key=lambda item: (item.component_id, item.ordinal, item.session_id)))


def _validate_candidate(candidate, known_sessions: set[str]) -> None:
    if not isinstance(candidate, PlacementCandidate):
        raise SolverInputError(
            "every candidate must be a PlacementCandidate instance, "
            f"got {type(candidate).__name__}."
        )
    _require_non_empty_string(candidate.candidate_id, "candidate_id")
    _require_non_empty_string(
        candidate.session_id, f"session_id of candidate '{candidate.candidate_id}'"
    )
    if candidate.session_id not in known_sessions:
        raise SolverInputError(
            f"candidate '{candidate.candidate_id}' references unknown session "
            f"'{candidate.session_id}'."
        )
    if not candidate.slot_ids:
        raise SolverInputError(
            f"candidate '{candidate.candidate_id}' must occupy at least one slot."
        )
    for slot_id in candidate.slot_ids:
        _require_positive_int(slot_id, f"slot id of candidate '{candidate.candidate_id}'")
    if len(set(candidate.slot_ids)) != len(candidate.slot_ids):
        raise SolverInputError(
            f"candidate '{candidate.candidate_id}' repeats a slot id; "
            "a candidate occupies each slot once."
        )
    _require_int(candidate.day_of_week, f"day_of_week of candidate '{candidate.candidate_id}'")
    if candidate.day_of_week < 0:
        raise SolverInputError(
            f"day_of_week of candidate '{candidate.candidate_id}' must not be negative."
        )
    if candidate.room_id is not None:
        _require_positive_int(
            candidate.room_id, f"room_id of candidate '{candidate.candidate_id}'"
        )
    for instructor_id in candidate.instructor_ids:
        _require_positive_int(
            instructor_id, f"instructor id of candidate '{candidate.candidate_id}'"
        )
    if len(set(candidate.instructor_ids)) != len(candidate.instructor_ids):
        raise SolverInputError(
            f"candidate '{candidate.candidate_id}' repeats an instructor id."
        )
    for group_id in candidate.student_group_ids:
        _require_positive_int(
            group_id, f"student group id of candidate '{candidate.candidate_id}'"
        )
    if len(set(candidate.student_group_ids)) != len(candidate.student_group_ids):
        raise SolverInputError(
            f"candidate '{candidate.candidate_id}' repeats a student group id."
        )
    _require_int(candidate.penalty, f"penalty of candidate '{candidate.candidate_id}'")
    if candidate.penalty < 0:
        raise SolverInputError(
            f"penalty of candidate '{candidate.candidate_id}' must not be negative; "
            "penalties are non-negative costs."
        )


def _validate_reservation(reservation) -> None:
    if not isinstance(reservation, ResourceReservation):
        raise SolverInputError(
            "every reservation must be a ResourceReservation instance, "
            f"got {type(reservation).__name__}."
        )
    _require_non_empty_string(reservation.reservation_id, "reservation_id")
    if not reservation.slot_ids:
        raise SolverInputError(
            f"reservation '{reservation.reservation_id}' must cover at least one slot."
        )
    for slot_id in reservation.slot_ids:
        _require_positive_int(
            slot_id, f"slot id of reservation '{reservation.reservation_id}'"
        )
    for field_name, values in (
        ("room id", reservation.room_ids),
        ("instructor id", reservation.instructor_ids),
        ("student group id", reservation.student_group_ids),
    ):
        for value in values:
            _require_positive_int(
                value, f"{field_name} of reservation '{reservation.reservation_id}'"
            )


def validate_problem(problem: SolverProblem) -> ValidatedProblem:
    """Validate ``problem`` and return its deterministic indexes.

    Raises :class:`SolverInputError` with a specific message for the first problem
    found. Iteration is in declaration order so the reported error is stable.
    """
    if not isinstance(problem, SolverProblem):
        raise SolverInputError(
            f"problem must be a SolverProblem instance, got {type(problem).__name__}."
        )

    sessions = _validate_sessions(problem.sessions)
    known_sessions = {session.session_id for session in sessions}

    candidates_by_session: dict[str, list[PlacementCandidate]] = {
        session.session_id: [] for session in sessions
    }
    candidates_by_id: dict[str, PlacementCandidate] = {}
    placement_keys: set[tuple[str, tuple]] = set()

    for candidate in problem.candidates:
        _validate_candidate(candidate, known_sessions)
        if candidate.candidate_id in candidates_by_id:
            raise SolverInputError(f"duplicate candidate_id '{candidate.candidate_id}'.")
        duplicate_key = (candidate.session_id, candidate.placement_key)
        if duplicate_key in placement_keys:
            raise SolverInputError(
                f"candidate '{candidate.candidate_id}' duplicates an existing "
                f"placement for session '{candidate.session_id}'."
            )
        placement_keys.add(duplicate_key)
        candidates_by_id[candidate.candidate_id] = candidate
        candidates_by_session[candidate.session_id].append(candidate)

    # A declared candidate list must match the candidates actually offered.
    for session in sessions:
        if session.candidate_ids is None:
            continue
        declared = set(session.candidate_ids)
        offered = {
            candidate.candidate_id
            for candidate in candidates_by_session[session.session_id]
        }
        if declared != offered:
            raise SolverInputError(
                f"session '{session.session_id}' declares candidate ids that do not "
                f"match its candidates (declared only: {sorted(declared - offered)}, "
                f"offered only: {sorted(offered - declared)})."
            )

    for reservation in problem.reservations:
        _validate_reservation(reservation)

    ordered_candidates = tuple(
        sorted(
            problem.candidates,
            key=lambda candidate: (
                candidate.session_id,
                candidate.sort_key,
                candidate.candidate_id,
            ),
        )
    )

    return ValidatedProblem(
        sessions=sessions,
        candidates=ordered_candidates,
        reservations=tuple(problem.reservations),
        candidates_by_session={
            session_id: tuple(
                sorted(values, key=lambda candidate: candidate.candidate_id)
            )
            for session_id, values in candidates_by_session.items()
        },
        candidates_by_id=candidates_by_id,
        component_by_session={session.session_id: session.component_id for session in sessions},
    )


__all__ = ["ValidatedProblem", "validate_options", "validate_problem"]
