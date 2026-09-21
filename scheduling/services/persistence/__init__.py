"""Persisting generated timetables as version history (Phase 11).

* ``snapshots.build_entry_snapshots`` - pure reshaping of a generation preview into
  the frozen rows a version keeps, including every display value a later rename
  would change.
* ``service.SchedulePersistenceService`` - verification, version numbering and the
  single short transaction that writes one version with all of its entries.

The package is the only writer of schedule history. The generation pipeline stays
read-only: ``POST /api/scheduling/generate/`` and its college sibling still return a
preview with ``persisted: false``, and generating a *draft* is an explicit, separate
request.
"""

from scheduling.services.persistence.service import (
    REASON_RESULT_INCOMPLETE,
    PersistResult,
    SchedulePersistenceService,
)
from scheduling.services.persistence.snapshots import (
    EntrySnapshot,
    GroupSnapshot,
    InstructorSnapshot,
    SlotSnapshot,
    build_entry_snapshots,
    parse_clock,
)

__all__ = [
    "REASON_RESULT_INCOMPLETE",
    "EntrySnapshot",
    "GroupSnapshot",
    "InstructorSnapshot",
    "PersistResult",
    "SchedulePersistenceService",
    "SlotSnapshot",
    "build_entry_snapshots",
    "parse_clock",
]
