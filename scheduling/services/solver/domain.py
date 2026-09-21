"""Input value objects for the CP-SAT scheduling engine.

The engine solves an *already prepared discrete problem*: a set of weekly session
demands, the feasible placements a caller has derived for each of them, and any
pre-existing resource occupancy that must be respected. It never decides which
instructor is eligible, which room suits a course, or which slots sit inside an
availability window - that derivation is the adapter's job, because it needs the
academic and resource data the engine deliberately does not know about.

Nothing in this module imports Django, the ORM or DRF. The objects are plain
frozen dataclasses holding primitives, so the engine is reusable and testable
without a database.

Two conventions the caller must respect:

* ``slot_ids`` are *globally unique* discrete time-slot identifiers (the primary
  key of a teaching period), so a slot id already implies its weekday. Conflict
  buckets are therefore keyed by slot id alone.
* ``penalty`` is a non-negative integer cost for choosing a placement. It is
  purely a weight: the engine never interprets *why* a placement is expensive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

#: Default time limit in seconds. Generous, but bounded.
DEFAULT_MAX_TIME_SECONDS = 30.0

#: Fixed seed, so repeated runs of the same problem stay reproducible.
DEFAULT_RANDOM_SEED = 0

#: Single worker by default: CP-SAT stays deterministic across runs.
DEFAULT_NUM_SEARCH_WORKERS = 1


def _as_int_tuple(values: Iterable[int] | None) -> tuple[int, ...]:
    """Return ``values`` as a tuple, tolerating ``None`` and lists."""
    if values is None:
        return ()
    return tuple(values)


def _as_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy caller metadata so later mutation cannot change a frozen object."""
    if not metadata:
        return {}
    return dict(metadata)


@dataclass(frozen=True)
class SolverOptions:
    """Run configuration for one solve.

    Defaults are chosen for reproducible development and tests: one search worker
    and a fixed seed. Callers that need speed may raise ``num_search_workers``,
    accepting that results need no longer be reproducible.
    """

    max_time_seconds: float = DEFAULT_MAX_TIME_SECONDS
    random_seed: int = DEFAULT_RANDOM_SEED
    num_search_workers: int = DEFAULT_NUM_SEARCH_WORKERS
    log_search_progress: bool = False


@dataclass(frozen=True)
class SessionDemand:
    """One required weekly session of a teaching component.

    A component with ``weekly_hours = 4`` and ``session_duration = 2`` becomes two
    demands, for example ``component-15/session-1`` and ``component-15/session-2``.
    The engine receives these; it does not derive them from teaching components.

    ``candidate_ids`` is optional. When supplied it declares exactly which
    candidates the caller considers available for this session, and the validator
    rejects any mismatch with the candidate list - a cheap guard against an
    adapter that builds candidates for the wrong session.
    """

    session_id: str
    component_id: str
    ordinal: int = 1
    candidate_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.candidate_ids is not None:
            object.__setattr__(
                self, "candidate_ids", tuple(self.candidate_ids)
            )


@dataclass(frozen=True)
class PlacementCandidate:
    """One indivisible placement option for a session.

    A candidate is one decision, never several: a two-period session carries
    ``slot_ids = (41, 42)`` as a single option. Splitting it into independent
    decisions would let the solver place one half of a session.

    A candidate is one indivisible placement option. Its identity as a placement -
    used to reject meaningless duplicate alternatives - is the day, the slots, the
    room and the groups and instructors involved. ``penalty`` only states how
    expensive that placement is, so two candidates differing solely in penalty are
    the same placement and are refused.

    ``instructor_ids`` holds every instructor attached to the placement - primary
    and assistants alike - because the engine only has to keep each of them free.
    """

    candidate_id: str
    session_id: str
    day_of_week: int
    slot_ids: tuple[int, ...]
    room_id: int | None = None
    instructor_ids: tuple[int, ...] = ()
    student_group_ids: tuple[int, ...] = ()
    penalty: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot_ids", _as_int_tuple(self.slot_ids))
        object.__setattr__(
            self, "instructor_ids", _as_int_tuple(self.instructor_ids)
        )
        object.__setattr__(
            self, "student_group_ids", _as_int_tuple(self.student_group_ids)
        )
        object.__setattr__(self, "metadata", _as_metadata(self.metadata))

    @property
    def first_slot_id(self) -> int:
        """Lowest slot id, used for deterministic ordering (0 when unset)."""
        return min(self.slot_ids) if self.slot_ids else 0

    @property
    def placement_key(self) -> tuple:
        """Physical identity of this placement: *where* it happens, not its cost.

        ``penalty`` and ``metadata`` are excluded on purpose. Two candidates with
        the same key on the same session occupy the same day, slots, room,
        instructors and groups; the cheaper one dominates and the other carries no
        information, so the validator refuses the pair instead of letting a
        meaningless alternative enlarge the search. A different penalty alone
        therefore never makes two otherwise identical placements distinct.
        """
        return (
            self.day_of_week,
            self.slot_ids,
            self.room_id,
            self.instructor_ids,
            self.student_group_ids,
        )

    @property
    def sort_key(self) -> tuple:
        """Stable ordering key independent of insertion or dict order."""
        return (
            self.day_of_week,
            self.first_slot_id,
            self.session_id,
            self.candidate_id,
        )


@dataclass(frozen=True)
class ResourceReservation:
    """Pre-existing occupancy the engine must work around.

    Phase 8 persists nothing, but the future Department Scheduler has to respect
    published or otherwise fixed occupancy. A reservation blocks combinations,
    not whole resources: ``slot_ids=(41, 42)`` with ``room_ids=(7,)`` blocks room 7
    in those two slots only. A reservation with no resource ids blocks the slots
    entirely.
    """

    reservation_id: str
    slot_ids: tuple[int, ...]
    room_ids: tuple[int, ...] = ()
    instructor_ids: tuple[int, ...] = ()
    student_group_ids: tuple[int, ...] = ()
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot_ids", _as_int_tuple(self.slot_ids))
        object.__setattr__(self, "room_ids", _as_int_tuple(self.room_ids))
        object.__setattr__(
            self, "instructor_ids", _as_int_tuple(self.instructor_ids)
        )
        object.__setattr__(
            self, "student_group_ids", _as_int_tuple(self.student_group_ids)
        )
        object.__setattr__(self, "metadata", _as_metadata(self.metadata))

    @property
    def blocks_slots_entirely(self) -> bool:
        """True when the reservation names no resource, so it closes the slots."""
        return not (self.room_ids or self.instructor_ids or self.student_group_ids)


@dataclass(frozen=True)
class SolverProblem:
    """A complete discrete scheduling problem for the engine.

    ``sessions`` is the demand, ``candidates`` the feasible options, and
    ``reservations`` occupancy that is already fixed outside this solve.
    """

    sessions: tuple[SessionDemand, ...] = ()
    candidates: tuple[PlacementCandidate, ...] = ()
    reservations: tuple[ResourceReservation, ...] = ()
    name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "sessions", tuple(self.sessions))
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "reservations", tuple(self.reservations))

    @property
    def is_empty(self) -> bool:
        """True when there is no demand at all: nothing to schedule."""
        return not self.sessions

    def candidates_for_session(self, session_id: str) -> tuple[PlacementCandidate, ...]:
        """Candidates offered for ``session_id``, in declaration order."""
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.session_id == session_id
        )

    def candidate_ids_for_session(self, session_id: str) -> tuple[str, ...]:
        """Candidate ids offered for ``session_id``."""
        return tuple(
            candidate.candidate_id
            for candidate in self.candidates_for_session(session_id)
        )


__all__ = [
    "DEFAULT_MAX_TIME_SECONDS",
    "DEFAULT_NUM_SEARCH_WORKERS",
    "DEFAULT_RANDOM_SEED",
    "PlacementCandidate",
    "ResourceReservation",
    "SessionDemand",
    "SolverOptions",
    "SolverProblem",
]
