"""Schedule generation (Phases 9 and 10).

The adapter layer between stored data and the pure CP-SAT engine:

* ``candidates.GenerationProblemBuilder`` - the Django adapter. Reads the academic,
  resource and calendar data, expands teaching components into weekly sessions and
  generates every valid placement candidate. ``DepartmentProblemBuilder`` scopes it
  to one managing department, ``CollegeProblemBuilder`` to the whole semester.
* ``blocks.find_exact_contiguous_slot_blocks`` - pure discrete-grid arithmetic. A
  session occupies adjacent periods whose durations sum *exactly* to its length.
* ``preferences.PreferencePenaltyCalculator`` - the soft preference policy, mapping
  instructor PREFERRED/AVOID windows onto the engine's generic penalty.
* ``preview.PreviewBuilder`` - flat, readable description of each chosen placement;
  ``CollegePreviewBuilder`` adds the documented department-first ordering.
* ``service.ScheduleGenerationPipeline`` - the pipeline: validate, build, solve,
  preview. ``DepartmentScheduleGenerator`` and ``CollegeScheduleGenerator`` are its
  two scopes. Nothing is persisted.

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
from scheduling.services.generation.candidates import (
    CollegeProblemBuilder,
    DepartmentProblemBuilder,
    GenerationProblemBuilder,
)
from scheduling.services.generation.domain import (
    CollegeGenerationSummary,
    ComponentInfo,
    CourseInfo,
    DepartmentBuildCount,
    DepartmentGenerationSummary,
    DepartmentInfo,
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
from scheduling.services.generation.preview import (
    CollegePreviewBuilder,
    PreviewBuilder,
    session_ordinal,
)
from scheduling.services.generation.service import (
    CollegeScheduleGenerator,
    DepartmentScheduleGenerator,
    ScheduleGenerationPipeline,
)

__all__ = [
    "PENALTY_AVOID",
    "PENALTY_NEUTRAL",
    "PENALTY_PREFERRED",
    "REASON_CANDIDATE_BUILD_FAILED",
    "REASON_VALIDATION_FAILED",
    "CollegeGenerationSummary",
    "CollegePreviewBuilder",
    "CollegeProblemBuilder",
    "CollegeScheduleGenerator",
    "ComponentInfo",
    "CourseInfo",
    "DepartmentBuildCount",
    "DepartmentGenerationSummary",
    "DepartmentInfo",
    "DepartmentProblemBuilder",
    "DepartmentScheduleGenerator",
    "GenerationDiagnostics",
    "GenerationIssueCode",
    "GenerationOutcome",
    "GenerationProblemBuilder",
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
    "ScheduleGenerationPipeline",
    "SessionCandidateCount",
    "SessionContext",
    "SlotBlock",
    "SlotInfo",
    "build_preference_windows",
    "find_exact_blocks_by_weekday",
    "find_exact_contiguous_slot_blocks",
    "group_slots_by_weekday",
    "session_ordinal",
]
