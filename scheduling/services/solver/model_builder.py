"""CP-SAT model construction.

The model is built from a validated problem and expresses the hard rules as
*resource buckets*: every candidate contributes its placements to the buckets it
touches, and each bucket gets one "at most one of these" constraint. This mirrors
the discrete timetable grid and avoids comparing every candidate with every other
one.

Buckets are keyed by ``(kind, resource_id, slot_id)``:

* ``("instructor", id, slot)`` - primary and assistant instructors alike,
* ``("group", id, slot)`` - normal groups, subgroups and joint-course groups,
* ``("room", id, slot)``,
* ``("component", id, slot)`` - a defensive rule, see below.

Because a candidate carries all of its slots, a two-slot session conflicts with
anything that overlaps *either* slot; the builder never looks at start slots only.

This module builds a model; it never solves one and never touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ortools.sat.python import cp_model

from scheduling.services.solver.validator import ValidatedProblem

#: Bucket kinds. ``component`` is a defensive invariant: sessions of one
#: component must not overlap even if a caller forgot to share a group or an
#: instructor between them.
COMPONENT_KIND = "component"
INSTRUCTOR_KIND = "instructor"
STUDENT_GROUP_KIND = "group"
ROOM_KIND = "room"

#: ``(kind, resource id, slot id)``. Resource ids may be strings (components) or
#: integers (instructors, groups, rooms).
ConflictKey = tuple[str, object, int]


@dataclass(frozen=True)
class BuiltModel:
    """The constructed CP-SAT model plus what the run will report about it."""

    model: cp_model.CpModel
    variables: Mapping[str, cp_model.IntVar]
    has_objective: bool
    conflict_bucket_count: int
    blocked_candidate_count: int
    unplaceable_sessions: tuple[str, ...]


def _bucket_sort_key(key: ConflictKey) -> tuple[str, str, int]:
    """Order buckets deterministically; resource ids may be str or int."""
    kind, resource_id, slot_id = key
    return (kind, str(resource_id), slot_id)


def _reservation_index(reservations) -> tuple[frozenset[int], frozenset[ConflictKey]]:
    """Split reservations into fully closed slots and closed resource/slot pairs."""
    closed_slots: set[int] = set()
    closed_keys: set[ConflictKey] = set()
    for reservation in reservations:
        if reservation.blocks_slots_entirely:
            closed_slots.update(reservation.slot_ids)
            continue
        for slot_id in reservation.slot_ids:
            for room_id in reservation.room_ids:
                closed_keys.add((ROOM_KIND, room_id, slot_id))
            for instructor_id in reservation.instructor_ids:
                closed_keys.add((INSTRUCTOR_KIND, instructor_id, slot_id))
            for group_id in reservation.student_group_ids:
                closed_keys.add((STUDENT_GROUP_KIND, group_id, slot_id))
    return frozenset(closed_slots), frozenset(closed_keys)


def _is_blocked(candidate, closed_slots: frozenset[int], closed_keys: frozenset) -> bool:
    """True when a reservation forbids this candidate entirely."""
    for slot_id in candidate.slot_ids:
        if slot_id in closed_slots:
            return True
        if candidate.room_id is not None and (
            ROOM_KIND,
            candidate.room_id,
            slot_id,
        ) in closed_keys:
            return True
        for instructor_id in candidate.instructor_ids:
            if (INSTRUCTOR_KIND, instructor_id, slot_id) in closed_keys:
                return True
        for group_id in candidate.student_group_ids:
            if (STUDENT_GROUP_KIND, group_id, slot_id) in closed_keys:
                return True
    return False


def build_model(validated: ValidatedProblem) -> BuiltModel:
    """Build the CP-SAT model for ``validated``.

    The model is always built, even for a problem with no sessions: an empty model
    solves to ``OPTIMAL`` with no placements, which is the documented behaviour
    for an empty problem.
    """
    model = cp_model.CpModel()
    variables = {
        candidate.candidate_id: model.NewBoolVar(f"place_{candidate.candidate_id}")
        for candidate in validated.candidates
    }

    # Every session is scheduled exactly once. A session with no candidates is
    # valid input but unsatisfiable, so it is modelled as an immediate conflict
    # rather than rejected; the solve then reports INFEASIBLE.
    unplaceable: list[str] = []
    for session in validated.sessions:
        options = validated.candidates_by_session.get(session.session_id, ())
        if not options:
            model.Add(0 == 1)
            unplaceable.append(session.session_id)
            continue
        model.AddExactlyOne(
            [variables[candidate.candidate_id] for candidate in options]
        )

    buckets: dict[ConflictKey, list[cp_model.IntVar]] = {}
    for candidate in validated.candidates:
        variable = variables[candidate.candidate_id]
        component_id = validated.component_by_session[candidate.session_id]
        for slot_id in candidate.slot_ids:
            buckets.setdefault((COMPONENT_KIND, component_id, slot_id), []).append(
                variable
            )
            for instructor_id in candidate.instructor_ids:
                buckets.setdefault(
                    (INSTRUCTOR_KIND, instructor_id, slot_id), []
                ).append(variable)
            for group_id in candidate.student_group_ids:
                buckets.setdefault(
                    (STUDENT_GROUP_KIND, group_id, slot_id), []
                ).append(variable)
            if candidate.room_id is not None:
                buckets.setdefault((ROOM_KIND, candidate.room_id, slot_id), []).append(
                    variable
                )

    conflict_buckets = 0
    for key in sorted(buckets, key=_bucket_sort_key):
        literals = buckets[key]
        if len(literals) > 1:
            model.AddAtMostOne(literals)
            conflict_buckets += 1

    closed_slots, closed_keys = _reservation_index(validated.reservations)
    blocked_candidates = 0
    for candidate in validated.candidates:
        if _is_blocked(candidate, closed_slots, closed_keys):
            model.Add(variables[candidate.candidate_id] == 0)
            blocked_candidates += 1

    weighted = [c for c in validated.candidates if c.penalty > 0]
    has_objective = bool(weighted)
    if has_objective:
        model.Minimize(
            sum(variables[candidate.candidate_id] * candidate.penalty for candidate in weighted)
        )

    return BuiltModel(
        model=model,
        variables=variables,
        has_objective=has_objective,
        conflict_bucket_count=conflict_buckets,
        blocked_candidate_count=blocked_candidates,
        unplaceable_sessions=tuple(unplaceable),
    )


__all__ = [
    "COMPONENT_KIND",
    "ConflictKey",
    "INSTRUCTOR_KIND",
    "ROOM_KIND",
    "STUDENT_GROUP_KIND",
    "BuiltModel",
    "build_model",
]
