"""The Django adapter that turns stored data into a Phase 8 problem.

This is the layer Phase 8 deliberately does not have: it decides which sessions
exist, which periods can hold them, which rooms are allowed, and how expensive a
placement is. It reads the academic, resource and calendar data once, works in
memory afterwards, and hands the pure engine a prepared discrete problem.

Two scopes share this one implementation:

* :class:`DepartmentProblemBuilder` covers the active components of one managing
  department, which is what the Phase 9 endpoint asks for;
* :class:`CollegeProblemBuilder` covers every active component of the semester
  across all managing departments, which is what the Phase 10 endpoint asks for.

Both extend :class:`GenerationProblemBuilder`, so slot blocks, room suitability,
instructor availability, preference penalties, session identity and candidate
identity are literally the same code. The only differences are which components
are demand and how the diagnostics are grouped.

A component belongs to the department that manages its offering. A joint component
that several departments attend stays *one* component with *one* set of weekly
sessions: its candidates carry every attached student group, so the engine can
enforce group conflicts globally instead of the adapter guessing at them.

The builder never solves anything. Instructor, group and room collisions are left
to the engine, which enforces them globally; the adapter only supplies the ids.
"""

from __future__ import annotations

from typing import Iterable

from academics.models import TeachingComponent, TeachingComponentGroup
from django.db.models import Prefetch
from resources.models import (
    AssignmentRole,
    InstructorAvailability,
    InstructorPreference,
    Room,
    RoomAvailability,
    TeachingAssignment,
    TeachingComponentCapabilityRequirement,
)
from scheduling.models import TimeSlot, WorkingDay
from scheduling.services.generation.blocks import (
    GridSlot,
    SlotBlock,
    find_exact_blocks_by_weekday,
    group_slots_by_weekday,
)
from scheduling.services.generation.domain import (
    ComponentInfo,
    CourseInfo,
    DepartmentBuildCount,
    DepartmentInfo,
    GenerationDiagnostics,
    GroupInfo,
    InstructorInfo,
    OfferingInfo,
    ProblemBundle,
    RoomInfo,
    SessionCandidateCount,
    SessionContext,
    SlotInfo,
)
from scheduling.services.generation.issues import GenerationIssueCode
from scheduling.services.generation.preferences import (
    PreferencePenaltyCalculator,
    build_preference_windows,
)
from scheduling.services.solver import PlacementCandidate, SessionDemand, SolverProblem
from scheduling.services.validation.issues import EntityType, Severity, ValidationIssue
from scheduling.services.validation.resources import ResourceFacts
from scheduling.services.validation.time_grid import hours_to_minutes, time_to_minutes

#: A time window as ``(start_minute, end_minute)`` inside one weekday.
Interval = tuple[int, int]

#: How many low-candidate sessions the diagnostics list for an infeasible run.
DIAGNOSTIC_SESSION_SAMPLE = 5


def _windows_by_weekday(
    rows: Iterable[tuple[int, int, int]],
) -> dict[int, tuple[Interval, ...]]:
    """Group ``(weekday, start_minute, end_minute)`` rows, dropping empty windows."""
    grouped: dict[int, list[Interval]] = {}
    for weekday, start_minute, end_minute in rows:
        if end_minute <= start_minute:
            continue
        grouped.setdefault(weekday, []).append((start_minute, end_minute))
    return {weekday: tuple(sorted(values)) for weekday, values in grouped.items()}


class GenerationProblemBuilder:
    """Shared adapter for department-scoped and college-scoped generation.

    Subclasses only decide *which* components are demand, *how* the problem is
    named, and which extra fields their issues carry. Everything that decides
    sessions, candidates, availability, suitability and penalties lives here, so
    the two scopes cannot drift apart.
    """

    def __init__(self, *, semester, department=None) -> None:
        self.semester = semester
        self.department = department
        self._issues: list[ValidationIssue] = []
        self._sessions: list[SessionDemand] = []
        self._candidates: list[PlacementCandidate] = []
        self._session_context: dict[str, SessionContext] = {}
        self._slot_info: dict[int, SlotInfo] = {}
        self._slots_by_weekday: dict[int, tuple[GridSlot, ...]] = {}
        self._instructor_windows: dict[int, dict[int, tuple[Interval, ...]]] = {}
        self._instructor_info: dict[int, InstructorInfo] = {}
        self._room_windows: dict[int, dict[int, tuple[Interval, ...]]] = {}
        self._room_info: dict[int, RoomInfo] = {}
        self._group_info: dict[int, GroupInfo] = {}
        self._rooms: list[Room] = []
        self._rooms_by_signature: dict[tuple, list[Room]] = {}
        self._room_suitability: dict[tuple[int, tuple], bool] = {}
        self._preferences: PreferencePenaltyCalculator | None = None
        self._components_considered = 0
        self._department_info: dict[int, DepartmentInfo] = {}
        self._department_components: dict[int, int] = {}
        self._department_sessions: dict[int, int] = {}
        self._department_candidates: dict[int, int] = {}

    # --- subclass hooks ----------------------------------------------------

    def _components_queryset(self):
        """The active components this scope has to schedule."""
        raise NotImplementedError

    def _problem_name(self) -> str:
        """Human-readable name of the built problem, used for logging only."""
        raise NotImplementedError

    def _issue_details(self, component) -> dict:
        """Extra issue fields for this scope, empty by default."""
        return {}

    # --- entry point -------------------------------------------------------

    def build(self) -> ProblemBundle:
        """Load the data, expand sessions and generate every valid candidate."""
        components = list(self._load_components())
        self._components_considered = len(components)
        self._load_grid()
        self._load_instructor_facts()
        self._load_rooms()

        for component in components:
            self._build_component(component)

        return ProblemBundle(
            solver_problem=SolverProblem(
                sessions=tuple(self._sessions),
                candidates=tuple(self._candidates),
                reservations=(),
                name=self._problem_name(),
            ),
            sessions=tuple(self._sessions),
            candidates=tuple(self._candidates),
            session_context=dict(self._session_context),
            slot_map=dict(self._slot_info),
            room_map=dict(self._room_info),
            instructor_map=dict(self._instructor_info),
            group_map=dict(self._group_info),
            diagnostics=self._diagnostics(),
            issues=tuple(self._issues),
        )

    # --- loading -----------------------------------------------------------

    def _load_components(self):
        """Active components of this scope in this semester.

        The offering, course and managing department must all be active, so a
        component whose dependency chain is switched off is not demand. Rooms and
        room requirements are joined in one pass, and the capability links of each
        requirement are prefetched *with* their capability, so the canonical
        suitability helper never point-looks-up a capability per link.
        """
        return (
            self._components_queryset()
            .select_related(
                "offering",
                "offering__course",
                "offering__managing_department",
                "room_requirement",
                "room_requirement__required_room_type",
            )
            .prefetch_related(
                Prefetch(
                    "group_links",
                    queryset=TeachingComponentGroup.objects.select_related(
                        "student_group"
                    ).order_by("student_group_id"),
                    to_attr="attached_group_links",
                ),
                Prefetch(
                    "instructor_assignments",
                    queryset=TeachingAssignment.objects.filter(is_active=True)
                    .select_related("instructor")
                    .order_by("assignment_role", "instructor_id"),
                    to_attr="attached_assignments",
                ),
                Prefetch(
                    "room_requirement__capability_requirements",
                    queryset=TeachingComponentCapabilityRequirement.objects.select_related(
                        "capability"
                    ).order_by("capability_id"),
                ),
            )
            .order_by("pk")
        )

    def _load_grid(self) -> None:
        """Active working days and their active periods, grouped by weekday.

        There is one recurring weekly grid per semester, so both scopes read the
        same working days and periods and both use the same exact-block rule:
        adjacent periods whose durations sum *exactly* to the session length, which
        is why a 90-minute session is never satisfied by two 60-minute periods.
        """
        working_days = (
            WorkingDay.objects.filter(semester=self.semester, is_active=True)
            .prefetch_related(
                Prefetch(
                    "time_slots",
                    queryset=TimeSlot.objects.filter(is_active=True).order_by(
                        "start_time", "sequence", "pk"
                    ),
                )
            )
            .order_by("day_of_week")
        )

        grid_slots: list[GridSlot] = []
        for working_day in working_days:
            weekday = int(working_day.day_of_week)
            for slot in working_day.time_slots.all():
                start_minute = time_to_minutes(slot.start_time)
                end_minute = time_to_minutes(slot.end_time)
                if start_minute is None or end_minute is None:
                    continue
                if end_minute <= start_minute:
                    continue
                grid_slots.append(
                    GridSlot(
                        slot_id=slot.pk,
                        weekday=weekday,
                        sequence=slot.sequence,
                        start_minute=start_minute,
                        end_minute=end_minute,
                    )
                )
                self._slot_info[slot.pk] = SlotInfo(
                    id=slot.pk,
                    sequence=slot.sequence,
                    label=slot.label or "",
                    start_time=slot.start_time.strftime("%H:%M"),
                    end_time=slot.end_time.strftime("%H:%M"),
                )
        self._slots_by_weekday = group_slots_by_weekday(grid_slots)

    def _load_instructor_facts(self) -> None:
        """Availability and preference windows for every instructor of the semester.

        Loaded once for the whole semester, which is what keeps college scope
        affordable: availability and preferences of every instructor are read in
        two queries no matter how many departments the problem spans.
        """
        availability_rows: dict[int, list[tuple[int, int, int]]] = {}
        for instructor_id, weekday, start, end in (
            InstructorAvailability.objects.filter(
                semester=self.semester, is_active=True
            )
            .values_list("instructor_id", "day_of_week", "start_time", "end_time")
            .order_by("instructor_id", "day_of_week", "start_time")
        ):
            start_minute = time_to_minutes(start)
            end_minute = time_to_minutes(end)
            if start_minute is None or end_minute is None:
                continue
            availability_rows.setdefault(instructor_id, []).append(
                (int(weekday), start_minute, end_minute)
            )
        self._instructor_windows = {
            instructor_id: _windows_by_weekday(rows)
            for instructor_id, rows in availability_rows.items()
        }

        preference_rows: list[tuple[int, int, int, int, str]] = []
        for instructor_id, weekday, start, end, preference_type in (
            InstructorPreference.objects.filter(semester=self.semester, is_active=True)
            .values_list(
                "instructor_id",
                "day_of_week",
                "start_time",
                "end_time",
                "preference_type",
            )
            .order_by("instructor_id", "day_of_week", "start_time")
        ):
            start_minute = time_to_minutes(start)
            end_minute = time_to_minutes(end)
            if start_minute is None or end_minute is None:
                continue
            preference_rows.append(
                (instructor_id, int(weekday), start_minute, end_minute, preference_type)
            )
        self._preferences = PreferencePenaltyCalculator(
            build_preference_windows(preference_rows)
        )

    def _load_rooms(self) -> None:
        """Active rooms college-wide, plus their availability windows.

        Rooms owned by other departments stay in the pool: the canonical Phase 5
        suitability helper decides, per requirement, whether the managing department
        may use them. Pool and availability are therefore loaded once per problem,
        not once per department.
        """
        self._rooms = list(
            Room.objects.filter(is_active=True)
            .select_related("room_type")
            .prefetch_related(
                "capability_assignments__capability",
                "department_access",
            )
            .order_by("pk")
        )
        self._room_info = {
            room.pk: RoomInfo(id=room.pk, code=room.code, name=room.name)
            for room in self._rooms
        }

        rows: dict[int, list[tuple[int, int, int]]] = {}
        for room_id, weekday, start, end in (
            RoomAvailability.objects.filter(semester=self.semester, is_active=True)
            .values_list("room_id", "day_of_week", "start_time", "end_time")
            .order_by("room_id", "day_of_week", "start_time")
        ):
            start_minute = time_to_minutes(start)
            end_minute = time_to_minutes(end)
            if start_minute is None or end_minute is None:
                continue
            rows.setdefault(room_id, []).append((int(weekday), start_minute, end_minute))
        self._room_windows = {
            room_id: _windows_by_weekday(values) for room_id, values in rows.items()
        }

    # --- component planning ------------------------------------------------

    def _build_component(self, component: TeachingComponent) -> None:
        """Expand one component into sessions and all of their candidates."""
        required_minutes = hours_to_minutes(component.session_duration_hours)
        weekly_minutes = hours_to_minutes(component.weekly_hours)
        session_count = component.sessions_per_week or 0
        assignments = list(getattr(component, "attached_assignments", []) or [])
        links = list(getattr(component, "attached_group_links", []) or [])
        primary = [
            assignment
            for assignment in assignments
            if assignment.assignment_role == AssignmentRole.PRIMARY
        ]

        department_id = component.offering.managing_department_id
        self._count_component(component)

        # Adapter preconditions. Phase 7 readiness normally guarantees these, so any
        # failure here means the data changed between validation and building, and
        # generation stops with a diagnostic instead of raising.
        if required_minutes <= 0:
            self._precondition_issue(
                component, "The component has no usable session duration."
            )
            return
        if session_count < 1:
            self._precondition_issue(
                component,
                "The component has no whole weekly session to schedule.",
                session_duration_minutes=required_minutes,
            )
            return
        if not primary:
            self._precondition_issue(
                component, "The component has no active primary instructor."
            )
            return

        requirement = getattr(component, "room_requirement", None)
        if requirement is None or not requirement.is_active:
            self._precondition_issue(
                component, "The component has no active room requirement."
            )
            return

        instructor_ids = tuple(sorted({a.instructor_id for a in assignments}))
        student_group_ids = tuple(sorted({link.student_group_id for link in links}))
        self._remember_instructors(assignments)
        self._remember_groups(links)

        candidate_rooms = self._rooms_for(requirement)
        blocks = [
            block
            for block in find_exact_blocks_by_weekday(
                self._slots_by_weekday, required_minutes
            )
            if self._instructors_available(instructor_ids, block)
        ]

        placements: list[tuple[SlotBlock, Room, int]] = []
        for block in blocks:
            penalty = self._penalty(instructor_ids, block)
            for room in candidate_rooms:
                if not self._room_available(room, block):
                    continue
                placements.append((block, room, penalty))

        component_info = self._component_info(component, required_minutes, weekly_minutes)
        roles = {a.instructor_id: a.assignment_role for a in assignments}
        session_ids: list[str] = []
        for ordinal in range(1, session_count + 1):
            session_id = f"component:{component.pk}:session:{ordinal}"
            session_ids.append(session_id)
            self._session_context[session_id] = SessionContext(
                session_id=session_id,
                ordinal=ordinal,
                component=component_info,
                instructor_ids=instructor_ids,
                student_group_ids=student_group_ids,
                assignment_roles=roles,
            )

        # Sessions are always recorded, even when no placement can be built for
        # them: the diagnostics then report the real session count and name the
        # sessions with zero candidates, and the service refuses to solve instead
        # of asking the engine a question that already has no answer.
        seen: set[tuple[str, tuple]] = set()
        for session_id in session_ids:
            self._bump(self._department_sessions, department_id)
            session_candidate_ids: list[str] = []
            for block, room, penalty in placements:
                candidate_id = self._candidate_id(
                    component_id=component.pk,
                    ordinal=self._session_context[session_id].ordinal,
                    block=block,
                    room_id=room.pk,
                )
                placement_key = (
                    block.weekday,
                    block.slot_ids,
                    room.pk,
                    instructor_ids,
                    student_group_ids,
                )
                if (session_id, placement_key) in seen:
                    self._duplicate_issue(component, session_id, candidate_id)
                    continue
                seen.add((session_id, placement_key))
                session_candidate_ids.append(candidate_id)
                self._bump(self._department_candidates, department_id)
                self._candidates.append(
                    PlacementCandidate(
                        candidate_id=candidate_id,
                        session_id=session_id,
                        day_of_week=block.weekday,
                        slot_ids=block.slot_ids,
                        room_id=room.pk,
                        instructor_ids=instructor_ids,
                        student_group_ids=student_group_ids,
                        penalty=penalty,
                        metadata={
                            "course_code": component.offering.course.code,
                            "component_type": component.component_type,
                            "offering_id": component.offering_id,
                        },
                    )
                )
            if not session_candidate_ids:
                self._no_candidates_issue(
                    component=component,
                    session_id=session_id,
                    required_minutes=required_minutes,
                    time_block_count=len(blocks),
                    candidate_room_count=len(candidate_rooms),
                )
            self._sessions.append(
                SessionDemand(
                    session_id=session_id,
                    component_id=str(component.pk),
                    ordinal=self._session_context[session_id].ordinal,
                    candidate_ids=tuple(session_candidate_ids),
                )
            )

    def _count_component(self, component: TeachingComponent) -> None:
        """Remember one component against its managing department, for diagnostics."""
        department = component.offering.managing_department
        self._department_info.setdefault(
            department.pk,
            DepartmentInfo(id=department.pk, code=department.code, name=department.name),
        )
        self._bump(self._department_components, department.pk)

    @staticmethod
    def _bump(counter: dict[int, int], key: int) -> None:
        """Increment one per-department diagnostic counter."""
        counter[key] = counter.get(key, 0) + 1

    def _component_info(
        self, component: TeachingComponent, required_minutes: int, weekly_minutes: int
    ) -> ComponentInfo:
        """Shallow, JSON-safe description of one component."""
        offering = component.offering
        course = offering.course
        department = offering.managing_department
        return ComponentInfo(
            id=component.pk,
            component_type=component.component_type,
            label=component.label or "",
            session_duration_minutes=required_minutes,
            weekly_minutes=weekly_minutes,
            course=CourseInfo(id=course.pk, code=course.code, name=course.name),
            offering=OfferingInfo(
                id=offering.pk, offering_code=offering.offering_code or ""
            ),
            managing_department=DepartmentInfo(
                id=department.pk, code=department.code, name=department.name
            ),
        )

    def _remember_instructors(self, assignments) -> None:
        for assignment in assignments:
            instructor = assignment.instructor
            self._instructor_info.setdefault(
                instructor.pk,
                InstructorInfo(id=instructor.pk, full_name=instructor.full_name),
            )

    def _remember_groups(self, links) -> None:
        for link in links:
            group = link.student_group
            self._group_info.setdefault(
                group.pk,
                GroupInfo(id=group.pk, code=group.code, name=group.name),
            )

    # --- availability and suitability --------------------------------------

    def _instructors_available(self, instructor_ids, block: SlotBlock) -> bool:
        """True when every assigned instructor covers the whole block.

        A slot counts only when it lies fully inside one availability window of the
        matching weekday. An instructor without availability for the semester
        produces no candidates at all, because absence is never unrestricted
        availability. Assistants are checked exactly like primary instructors.

        Only the instructors actually assigned to the component are considered, so
        college scope cannot widen one department's teaching rights: who may teach a
        component stays a property of its assignment, which Phase 7 checks against
        the component's managing department. Running the solver college-wide does not
        turn a grant for department B into a grant for department C.
        """
        for instructor_id in instructor_ids:
            windows = self._instructor_windows.get(instructor_id, {}).get(
                block.weekday, ()
            )
            if not windows:
                return False
            for slot in block.slots:
                if not any(
                    slot.start_minute >= start and slot.end_minute <= end
                    for start, end in windows
                ):
                    return False
        return True

    def _room_available(self, room: Room, block: SlotBlock) -> bool:
        """True when the room's own availability covers the whole block."""
        windows = self._room_windows.get(room.pk, {}).get(block.weekday, ())
        if not windows:
            return False
        for slot in block.slots:
            if not any(
                slot.start_minute >= start and slot.end_minute <= end
                for start, end in windows
            ):
                return False
        return True

    def _rooms_for(self, requirement) -> list[Room]:
        """Rooms that currently satisfy ``requirement``, via the canonical helper.

        Shared rooms are included whenever Phase 5 sharing allows the managing
        department to use them, so ownership never restricts candidates by itself.
        Results are memoised per requirement *shape*: two components with the same
        managing department, required room type, effective capacity and capability
        set get the same answer, so the expensive canonical check runs once per
        shape rather than once per component. The shape includes the managing
        department, so a room shared with one department is never silently reused as
        suitable for another.
        """
        signature = ResourceFacts.requirement_signature(requirement)
        cached = self._rooms_by_signature.get(signature)
        if cached is not None:
            return cached

        rooms: list[Room] = []
        for room in self._rooms:
            if not ResourceFacts.may_satisfy_shape(room, requirement):
                continue
            key = (room.pk, signature)
            verdict = self._room_suitability.get(key)
            if verdict is None:
                verdict = room.meets_requirement(requirement)
                self._room_suitability[key] = verdict
            if verdict:
                rooms.append(room)
        self._rooms_by_signature[signature] = rooms
        return rooms

    def _penalty(self, instructor_ids, block: SlotBlock) -> int:
        """Summed preference penalty of every assigned instructor for one block."""
        if self._preferences is None:
            return 0
        return self._preferences.penalty_for(
            instructor_ids, block.weekday, block.start_minute, block.end_minute
        )

    # --- identifiers -------------------------------------------------------

    @staticmethod
    def _candidate_id(
        *, component_id: int, ordinal: int, block: SlotBlock, room_id: int
    ) -> str:
        """Stable candidate identifier built only from placement facts.

        The id carries no penalty, no scope, no timestamp and no random part, so
        repeated generation against unchanged data produces identical candidate ids,
        and the same physical placement receives the same id whether it was built by
        department generation or by college generation.
        """
        slots = "-".join(str(slot_id) for slot_id in block.slot_ids)
        return (
            f"component:{component_id}:session:{ordinal}"
            f":day:{block.weekday}:slots:{slots}:room:{room_id}"
        )

    # --- diagnostics -------------------------------------------------------

    def _precondition_issue(self, component, message: str, **details) -> None:
        self._issues.append(
            ValidationIssue(
                code=GenerationIssueCode.ADAPTER_PRECONDITION_FAILED,
                severity=Severity.ERROR,
                message=message,
                entity_type=EntityType.TEACHING_COMPONENT,
                entity_id=component.pk,
                details={
                    "course_code": component.offering.course.code,
                    **details,
                    **self._issue_details(component),
                },
            )
        )

    def _duplicate_issue(self, component, session_id: str, candidate_id: str) -> None:
        self._issues.append(
            ValidationIssue(
                code=GenerationIssueCode.ADAPTER_DUPLICATE_CANDIDATE,
                severity=Severity.ERROR,
                message=(
                    "The adapter produced the same physical placement twice for one "
                    "session and refused it."
                ),
                entity_type=EntityType.TEACHING_COMPONENT,
                entity_id=component.pk,
                details={"session_id": session_id, "candidate_id": candidate_id},
            )
        )

    def _no_candidates_issue(
        self,
        *,
        component,
        session_id: str,
        required_minutes: int,
        time_block_count: int,
        candidate_room_count: int,
    ) -> None:
        """One session could not be given a single candidate, so no solve is possible.

        Only counts and the component's own identity are reported, never a foreign
        resource identity.
        """
        self._issues.append(
            ValidationIssue(
                code=GenerationIssueCode.NO_PLACEMENT_CANDIDATES,
                severity=Severity.ERROR,
                message=(
                    "No valid time block and room combination exists for this session."
                ),
                entity_type=EntityType.TEACHING_COMPONENT,
                entity_id=component.pk,
                details={
                    "session_id": session_id,
                    "required_duration_minutes": required_minutes,
                    "suitable_room_count": candidate_room_count,
                    "available_time_block_count": time_block_count,
                    "course_code": component.offering.course.code,
                    **self._issue_details(component),
                },
            )
        )

    def _diagnostics(self) -> GenerationDiagnostics:
        """Counts over what was built, ordered deterministically."""
        counts: list[SessionCandidateCount] = []
        for session in self._sessions:
            counts.append(
                SessionCandidateCount(
                    session_id=session.session_id,
                    component_id=int(session.component_id),
                    candidate_count=len(session.candidate_ids or ()),
                )
            )
        counts.sort(key=lambda item: (item.candidate_count, item.session_id))
        without = tuple(
            item.session_id for item in counts if item.candidate_count == 0
        )
        return GenerationDiagnostics(
            components=self._components_considered,
            sessions=len(self._sessions),
            candidates=len(self._candidates),
            min_candidates_per_session=counts[0].candidate_count if counts else 0,
            max_candidates_per_session=counts[-1].candidate_count if counts else 0,
            sessions_with_fewest_candidates=tuple(counts[:DIAGNOSTIC_SESSION_SAMPLE]),
            sessions_without_candidates=without,
            departments=len(self._department_info),
            department_breakdown=self._department_breakdown(),
        )

    def _department_breakdown(self) -> tuple[DepartmentBuildCount, ...]:
        """Per-managing-department build counts, sorted by department code then id.

        The order is documented because it is part of the response contract: a
        college preview lists its departments in the same order on every run.
        """
        rows = [
            DepartmentBuildCount(
                department=info,
                components=self._department_components.get(department_id, 0),
                sessions=self._department_sessions.get(department_id, 0),
                candidates=self._department_candidates.get(department_id, 0),
            )
            for department_id, info in self._department_info.items()
        ]
        rows.sort(key=lambda row: (row.department.code, row.department.id))
        return tuple(rows)


class DepartmentProblemBuilder(GenerationProblemBuilder):
    """Builds one department's discrete scheduling problem for one semester."""

    def __init__(self, *, semester, department) -> None:
        super().__init__(semester=semester, department=department)

    def _components_queryset(self):
        """Active components managed by this department.

        A component that merely shares students with the department belongs to the
        department that manages it, so it is not demand here.
        """
        return TeachingComponent.objects.filter(
            is_active=True,
            offering__is_active=True,
            offering__course__is_active=True,
            offering__semester=self.semester,
            offering__managing_department=self.department,
        )

    def _problem_name(self) -> str:
        return f"department:{self.department.pk}:semester:{self.semester.pk}"


class CollegeProblemBuilder(GenerationProblemBuilder):
    """Builds one semester's college-wide discrete scheduling problem.

    Every active component of every managing department becomes part of a single
    problem, so shared instructors, shared rooms and joint student groups are
    constrained together instead of department by department.
    """

    def __init__(self, *, semester) -> None:
        super().__init__(semester=semester, department=None)

    def _components_queryset(self):
        """Active components of the semester across all managing departments."""
        return TeachingComponent.objects.filter(
            is_active=True,
            offering__is_active=True,
            offering__course__is_active=True,
            offering__semester=self.semester,
        )

    def _problem_name(self) -> str:
        return f"college:semester:{self.semester.pk}"

    def _issue_details(self, component) -> dict:
        """Name the managing department, which is ambiguous only in college scope.

        The department endpoint covers exactly one department, so its issues keep
        their existing shape and stay compatible with Phase 9.
        """
        return {
            "managing_department_id": component.offering.managing_department_id,
        }


__all__ = [
    "DIAGNOSTIC_SESSION_SAMPLE",
    "CollegeProblemBuilder",
    "DepartmentProblemBuilder",
    "GenerationProblemBuilder",
]
