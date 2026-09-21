"""Department schedule generation (Phase 9).

The adapter layer between stored data and the pure CP-SAT engine:

* ``candidates.DepartmentProblemBuilder`` - the Django adapter. Reads the academic,
  resource and calendar data, expands teaching components into weekly sessions and
  generates every valid placement candidate.
* ``blocks.find_exact_contiguous_slot_blocks`` - pure discrete-grid arithmetic. A
  session occupies adjacent periods whose durations sum *exactly* to its length.
* ``preferences.PreferencePenaltyCalculator`` - the soft preference policy, mapping
  instructor PREFERRED/AVOID windows onto the engine's generic penalty.
* ``preview.PreviewBuilder`` - flat, readable description of each chosen placement.
* ``service.DepartmentScheduleGenerator`` - the pipeline: validate, build, solve,
  preview. Nothing is persisted.

Only this package knows about Django; ``scheduling.services.solver`` stays pure and
must never import from here.
"""

from scheduling.services.generation.blocks import (
    GridSlot,
    SlotBlock,
    find_exact_blocks_by_weekday,
    find_exact_contiguous_slot_blocks,
    group_slots_by_weekday,
)
from scheduling.services.generation.candidates import DepartmentProblemBuilder
from scheduling.services.generation.domain import (
    ComponentInfo,
    CourseInfo,
    GenerationDiagnostics,
    GenerationOutcome,
    GenerationSummary,
    GroupInfo,
    InstructorInfo,
    OfferingInfo,
    PlacementInstructor,
    PreviewPlacement,
    ProblemBundle,
    RoomInfo,
    SessionCandidateCount,
    SessionContext,
    SlotInfo,
)
from scheduling.services.generation.issues import (
    GenerationIssueCode,
    REASON_CANDIDATE_BUILD_FAILED,
    REASON_VALIDATION_FAILED,
)
from scheduling.services.generation.preferences import (
    PENALTY_AVOID,
    PENALTY_NEUTRAL,
    PENALTY_PREFERRED,
    PreferencePenaltyCalculator,
    build_preference_windows,
)
from scheduling.services.generation.preview import PreviewBuilder
from scheduling.services.generation.service import DepartmentScheduleGenerator

__all__ = [
    "PENALTY_AVOID",
    "PENALTY_NEUTRAL",
    "PENALTY_PREFERRED",
    "REASON_CANDIDATE_BUILD_FAILED",
    "REASON_VALIDATION_FAILED",
    "ComponentInfo",
    "CourseInfo",
    "DepartmentProblemBuilder",
    "DepartmentScheduleGenerator",
    "GenerationDiagnostics",
    "GenerationIssueCode",
    "GenerationOutcome",
    "GenerationSummary",
    "GridSlot",
    "GroupInfo",
    "InstructorInfo",
    "OfferingInfo",
    "PlacementInstructor",
    "PreferencePenaltyCalculator",
    "PreviewBuilder",
    "PreviewPlacement",
    "ProblemBundle",
    "RoomInfo",
    "SessionCandidateCount",
    "SessionContext",
    "SlotBlock",
    "SlotInfo",
    "build_preference_windows",
    "find_exact_blocks_by_weekday",
    "find_exact_contiguous_slot_blocks",
    "group_slots_by_weekday",
]
