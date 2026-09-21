"""Semantic validation of a parsed semester teaching plan.

Validation answers one question: could this workbook be applied exactly as written? It
resolves every reference, checks every value against the same model rules the HTTP API
uses, and reports what is wrong - without writing anything. ``apply`` runs this same
validation inside its transaction immediately before the writes, so a validate response
from an earlier request is never trusted on its own.

Resolution is done in bulk (one query per referenced collection) and each row is turned
into an unsaved model instance whose ``clean()`` decides the domain rules. That is what
keeps the import from inventing a second, weaker copy of the Phase 3, 4 and 5 rules: a
component whose weekly hours do not divide into whole sessions fails here for the same
reason it fails on ``POST /api/teaching-components/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError

from academics.models import (
    Course,
    CourseOffering,
    StudentGroup,
    StudyProgram,
    StudyStage,
    TeachingComponent,
    TeachingComponentGroup,
)
from resources.models import (
    AssignmentRole,
    InstructorProfile,
    RoomCapability,
    RoomType,
    TeachingAssignment,
    TeachingComponentCapabilityRequirement,
    TeachingComponentRoomRequirement,
)

from scheduling.services.imports.domain import (
    ASSIGNMENT_ROLES,
    COMPONENT_TYPES,
    DEFAULT_ASSIGNMENT_ROLE,
    DEFAULT_OFFERING_CODE,
    REFERENCE_COLUMNS,
    SHEET_ASSIGNMENTS,
    SHEET_COMPONENT_GROUPS,
    SHEET_COMPONENTS,
    SHEET_COURSES,
    SHEET_OFFERINGS,
    SHEET_REQUIREMENT_CAPABILITIES,
    SHEET_ROOM_REQUIREMENTS,
    SHEET_STUDENT_GROUPS,
    PlanRow,
    PlanWorkbook,
)
from scheduling.services.imports.issues import IssueCollector

#: Decimal limits of the hour columns, mirroring the model fields.
HOURS_MAX_DIGITS = 5
HOURS_DECIMAL_PLACES = 2


@dataclass(frozen=True)
class CourseSpec:
    row: PlanRow
    ref: str
    instance: Course


@dataclass(frozen=True)
class GroupSpec:
    row: PlanRow
    ref: str
    instance: StudentGroup


@dataclass(frozen=True)
class OfferingSpec:
    row: PlanRow
    ref: str
    course_ref: str
    instance: CourseOffering


@dataclass(frozen=True)
class ComponentSpec:
    row: PlanRow
    ref: str
    offering_ref: str
    instance: TeachingComponent


@dataclass(frozen=True)
class ComponentGroupSpec:
    row: PlanRow
    component_ref: str
    group_ref: str
    instance: TeachingComponentGroup


@dataclass(frozen=True)
class AssignmentSpec:
    row: PlanRow
    component_ref: str
    instance: TeachingAssignment


@dataclass(frozen=True)
class RoomRequirementSpec:
    row: PlanRow
    component_ref: str
    instance: TeachingComponentRoomRequirement


@dataclass(frozen=True)
class CapabilityRequirementSpec:
    row: PlanRow
    component_ref: str
    instance: TeachingComponentCapabilityRequirement


@dataclass(frozen=True)
class ValidatedPlan:
    """A workbook that passed every check, ready to be written in one transaction.

    The specs hold unsaved model instances: applying means saving them in dependency
    order, nothing else. Counts are reported to the caller.
    """

    department: object
    semester: object
    courses: tuple[CourseSpec, ...] = ()
    groups: tuple[GroupSpec, ...] = ()
    offerings: tuple[OfferingSpec, ...] = ()
    components: tuple[ComponentSpec, ...] = ()
    component_groups: tuple[ComponentGroupSpec, ...] = ()
    assignments: tuple[AssignmentSpec, ...] = ()
    room_requirements: tuple[RoomRequirementSpec, ...] = ()
    capability_requirements: tuple[CapabilityRequirementSpec, ...] = ()

    def counts(self) -> dict[str, int]:
        """Row counts per created record type, in the documented order."""
        return {
            "courses": len(self.courses),
            "student_groups": len(self.groups),
            "offerings": len(self.offerings),
            "components": len(self.components),
            "component_group_links": len(self.component_groups),
            "teaching_assignments": len(self.assignments),
            "room_requirements": len(self.room_requirements),
            "requirement_capabilities": len(self.capability_requirements),
        }

    @property
    def total_records(self) -> int:
        return sum(self.counts().values())


@dataclass
class _Context:
    """Shared state of one validation pass."""

    workbook: PlanWorkbook
    department: object
    semester: object
    cross_department: bool
    collector: IssueCollector
    refs: dict[str, dict[str, PlanRow]] = field(default_factory=dict)


def validate_plan(
    *,
    workbook: PlanWorkbook,
    department,
    semester,
    cross_department: bool,
) -> tuple[ValidatedPlan | None, IssueCollector]:
    """Validate a parsed workbook against current database state.

    Returns the plan and the collector. The plan is ``None`` whenever the collector holds
    a blocking issue, so a caller cannot accidentally apply a partially valid workbook.
    """
    context = _Context(
        workbook=workbook,
        department=department,
        semester=semester,
        cross_department=cross_department,
        collector=IssueCollector(),
    )

    _collect_refs(context)
    courses = _validate_courses(context)
    groups = _validate_groups(context)
    offerings = _validate_offerings(context, courses)
    components = _validate_components(context, offerings)
    component_groups = _validate_component_groups(
        context, components, groups
    )
    assignments = _validate_assignments(context, components)
    room_requirements = _validate_room_requirements(context, components)
    capability_requirements = _validate_capabilities(context, room_requirements)
    _warn_missing_assignments(context, components, assignments)

    if not context.collector.valid:
        return None, context.collector
    return (
        ValidatedPlan(
            department=department,
            semester=semester,
            courses=courses,
            groups=groups,
            offerings=offerings,
            components=components,
            component_groups=component_groups,
            assignments=assignments,
            room_requirements=room_requirements,
            capability_requirements=capability_requirements,
        ),
        context.collector,
    )


# --- reference collection ---------------------------------------------------


def _collect_refs(context: _Context) -> None:
    """Index the workbook-local references and reject missing or duplicated ones."""
    for sheet, column in REFERENCE_COLUMNS.items():
        index: dict[str, PlanRow] = {}
        for row in context.workbook.rows_for(sheet):
            ref = row.get(column)
            if not ref:
                context.collector.add(
                    sheet=sheet,
                    row=row.row,
                    code="MISSING_VALUE",
                    message=f"Column '{column}' is required.",
                    column=column,
                )
                continue
            if ref in index:
                context.collector.add(
                    sheet=sheet,
                    row=row.row,
                    code="DUPLICATE_REF",
                    message=(
                        f"Reference '{ref}' is already used on row {index[ref].row} of "
                        f"sheet '{sheet}'."
                    ),
                    column=column,
                    details={"first_row": index[ref].row},
                )
                continue
            index[ref] = row
        context.refs[sheet] = index


def _ref_rows(context: _Context, sheet: str) -> tuple[PlanRow, ...]:
    """Rows of a sheet whose reference column resolved."""
    index = context.refs.get(sheet, {})
    return tuple(index.values())


# --- value helpers ----------------------------------------------------------


def _to_int(text: str) -> int | None:
    if text == "":
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if number != number.to_integral_value():
        return None
    return int(number)


def _to_decimal(text: str) -> Decimal | None:
    if text == "":
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if number.is_nan() or number.is_infinite():
        return None
    exponent = -number.as_tuple().exponent
    if exponent > HOURS_DECIMAL_PLACES:
        return None
    if len(number.as_tuple().digits) > HOURS_MAX_DIGITS:
        return None
    return number


def _clean(instance) -> tuple[str, str] | None:
    """Run a model's ``clean()``; return the first (field, message) it raised.

    Returns None when the instance is acceptable. The field name becomes the reported
    column, so an error points at the cell a spreadsheet author must change.
    """
    try:
        instance.clean()
    except DjangoValidationError as exc:
        for field_name, messages in exc.message_dict.items():
            return field_name, str(messages[0])
        return "non_field_errors", "; ".join(exc.messages)
    return None


def _reject(context: _Context, row: PlanRow, column: str | None, code: str, message: str):
    context.collector.add(
        sheet=row.sheet, row=row.row, code=code, message=message, column=column
    )
    return None


# --- sheet validation -------------------------------------------------------


def _validate_courses(context: _Context) -> tuple[CourseSpec, ...]:
    """Create-only courses for the authorized department."""
    rows = _ref_rows(context, SHEET_COURSES)
    if not rows:
        return ()

    codes = [row.get("code") for row in rows]
    existing = set(
        Course.objects.filter(
            department=context.department, code__in=[code for code in codes if code]
        ).values_list("code", flat=True)
    )

    specs: list[CourseSpec] = []
    seen: dict[str, PlanRow] = {}
    for row in rows:
        ref = row.get(REFERENCE_COLUMNS[SHEET_COURSES])
        code = row.get("code")
        name = row.get("name")
        if not code:
            _reject(
                context,
                row,
                "code",
                "MISSING_VALUE",
                "A course code is required.",
            )
            continue
        if not name:
            _reject(
                context,
                row,
                "name",
                "MISSING_VALUE",
                "A course name is required.",
            )
            continue
        if code in seen:
            _reject(
                context,
                row,
                "code",
                "DUPLICATE_COURSE_CODE",
                f"Course code '{code}' is already used on row {seen[code].row}.",
            )
            continue
        seen[code] = row
        if code in existing:
            _reject(
                context,
                row,
                "code",
                "COURSE_ALREADY_EXISTS",
                (
                    f"Course '{code}' already exists in "
                    f"{context.department.code}. This import never overwrites an "
                    "existing course."
                ),
            )
            continue
        specs.append(
            CourseSpec(
                row=row,
                ref=ref,
                instance=Course(
                    department=context.department,
                    code=code,
                    name=name,
                    description=row.get("description"),
                ),
            )
        )
    return tuple(specs)


def _validate_groups(context: _Context) -> tuple[GroupSpec, ...]:
    """Create-only groups under existing programs and stages."""
    rows = _ref_rows(context, SHEET_STUDENT_GROUPS)
    if not rows:
        return ()

    program_codes = {row.get("program_code") for row in rows if row.get("program_code")}
    local_programs = {
        program.code: program
        for program in StudyProgram.objects.filter(
            code__in=program_codes, department=context.department
        ).select_related("department")
    }
    foreign_programs: dict[str, list[StudyProgram]] = {}
    if context.cross_department:
        for program in StudyProgram.objects.filter(
            code__in=program_codes
        ).select_related("department"):
            foreign_programs.setdefault(program.code, []).append(program)

    stage_numbers = {
        _to_int(row.get("stage_number")) for row in rows if row.get("stage_number")
    }
    stage_numbers = {number for number in stage_numbers if number is not None}
    stages: dict[tuple[int, int], StudyStage] = {}
    if stage_numbers:
        program_ids = {
            program.pk for program in local_programs.values()
        } | {
            program.pk
            for programs in foreign_programs.values()
            for program in programs
        }
        for stage in StudyStage.objects.filter(
            program_id__in=program_ids, number__in=stage_numbers
        ).select_related("program"):
            stages[(stage.program_id, stage.number)] = stage

    existing_group_codes: set[tuple[int, str]] = set()
    codes = {row.get("code") for row in rows if row.get("code")}
    if stages and codes:
        existing_group_codes = set(
            StudentGroup.objects.filter(
                stage_id__in=[stage.pk for stage in stages.values()], code__in=codes
            ).values_list("stage_id", "code")
        )

    specs: list[GroupSpec] = []
    pairs: dict[tuple[int | None, str], PlanRow] = {}
    parents: dict[str, str] = {}
    for row in rows:
        ref = row.get(REFERENCE_COLUMNS[SHEET_STUDENT_GROUPS])
        code = row.get("code")
        name = row.get("name")
        program_code = row.get("program_code")
        stage_number = _to_int(row.get("stage_number"))
        student_count = _to_int(row.get("student_count", "0"))

        if not code or not name:
            _reject(
                context,
                row,
                "code" if not code else "name",
                "MISSING_VALUE",
                "A group code and name are required.",
            )
            continue
        program = local_programs.get(program_code)
        if program is None and context.cross_department:
            candidates = foreign_programs.get(program_code, [])
            if len(candidates) == 1:
                program = candidates[0]
            elif len(candidates) > 1:
                _reject(
                    context,
                    row,
                    "program_code",
                    "PROGRAM_NOT_FOUND",
                    (
                        f"Program code '{program_code}' exists in more than one "
                        "department and is therefore ambiguous."
                    ),
                )
                continue
        if program is None:
            if StudyProgram.objects.filter(code=program_code).exists():
                _reject(
                    context,
                    row,
                    "program_code",
                    "PROGRAM_OUTSIDE_DEPARTMENT",
                    (
                        f"Program '{program_code}' belongs to another department. Only "
                        "a college administrator may import for it."
                    ),
                )
            else:
                _reject(
                    context,
                    row,
                    "program_code",
                    "PROGRAM_NOT_FOUND",
                    f"No study program with code '{program_code}' exists.",
                )
            continue
        if stage_number is None:
            _reject(
                context,
                row,
                "stage_number",
                "INVALID_INTEGER",
                "Stage number must be a whole number.",
            )
            continue
        stage = stages.get((program.pk, stage_number))
        if stage is None:
            _reject(
                context,
                row,
                "stage_number",
                "STAGE_NOT_FOUND",
                f"Program '{program_code}' has no stage {stage_number}.",
            )
            continue
        if student_count is None or student_count < 0:
            _reject(
                context,
                row,
                "student_count",
                "INVALID_STUDENT_COUNT",
                "Student count must be a whole number of zero or more.",
            )
            continue
        if (stage.pk, code) in existing_group_codes or (stage.pk, code) in pairs:
            other = pairs.get((stage.pk, code))
            _reject(
                context,
                row,
                "code",
                "GROUP_ALREADY_EXISTS",
                (
                    f"Group code '{code}' already exists in this stage."
                    if other is None
                    else f"Group code '{code}' is already used on row {other.row}."
                ),
            )
            continue
        pairs[(stage.pk, code)] = row
        parents[ref] = row.get("parent_group_ref")
        specs.append(
            GroupSpec(
                row=row,
                ref=ref,
                instance=StudentGroup(
                    stage=stage,
                    code=code,
                    name=name,
                    student_count=student_count,
                ),
            )
        )

    valid_refs = {spec.ref: spec for spec in specs}
    for spec in specs:
        parent_ref = parents.get(spec.ref, "")
        if parent_ref:
            if parent_ref == spec.ref:
                _reject(
                    context,
                    spec.row,
                    "parent_group_ref",
                    "PARENT_GROUP_SELF",
                    "A group cannot be its own parent.",
                )
                continue
            parent_spec = valid_refs.get(parent_ref)
            if parent_spec is None:
                _reject(
                    context,
                    spec.row,
                    "parent_group_ref",
                    "PARENT_GROUP_NOT_IN_WORKBOOK",
                    (
                        f"Parent reference '{parent_ref}' does not resolve to a group row "
                        "in this workbook."
                    ),
                )
                continue
            if parent_spec.instance.stage_id != spec.instance.stage_id:
                _reject(
                    context,
                    spec.row,
                    "parent_group_ref",
                    "PARENT_GROUP_DIFFERENT_STAGE",
                    "A subgroup must belong to the same stage as its parent group.",
                )
                continue
            if _creates_cycle(spec.ref, parents, valid_refs):
                _reject(
                    context,
                    spec.row,
                    "parent_group_ref",
                    "PARENT_GROUP_CYCLE",
                    "The subgroup hierarchy of this workbook contains a cycle.",
                )
                continue
            spec.instance.parent_group = parent_spec.instance

        # The Phase 2 subgroup rules are re-run on the assembled instance, so a
        # workbook cannot store a hierarchy the API would reject.
        problem = _clean(spec.instance)
        if problem is not None:
            _reject(
                context,
                spec.row,
                problem[0],
                "INVALID_VALUE",
                problem[1],
            )
    return tuple(specs)


def _creates_cycle(
    ref: str, parents: dict[str, str], valid_refs: dict[str, GroupSpec]
) -> bool:
    """True when following parent references from ``ref`` returns to ``ref``."""
    seen = {ref}
    current = parents.get(ref, "")
    while current:
        if current in seen:
            return True
        seen.add(current)
        current = parents.get(current, "")
        if current and current not in valid_refs:
            return False
    return False


def _validate_offerings(
    context: _Context, courses: tuple[CourseSpec, ...]
) -> tuple[OfferingSpec, ...]:
    """Create-only offerings in the requested semester, managed by the request department."""
    rows = _ref_rows(context, SHEET_OFFERINGS)
    if not rows:
        return ()

    courses_by_ref = {spec.ref: spec for spec in courses}
    existing_offerings = set(
        CourseOffering.objects.filter(semester=context.semester).values_list(
            "course__department_id", "course__code", "offering_code"
        )
    )

    specs: list[OfferingSpec] = []
    seen: dict[tuple[str, str], PlanRow] = {}
    for row in rows:
        ref = row.get(REFERENCE_COLUMNS[SHEET_OFFERINGS])
        course_ref = row.get("course_ref")
        offering_code = row.get("offering_code", DEFAULT_OFFERING_CODE)
        course_spec = courses_by_ref.get(course_ref)
        if course_spec is None:
            _reject(
                context,
                row,
                "course_ref",
                "COURSE_REF_NOT_FOUND",
                f"Course reference '{course_ref}' does not resolve to a Courses row.",
            )
            continue
        key = (course_spec.instance.code, offering_code)
        if key in seen:
            _reject(
                context,
                row,
                "offering_code",
                "DUPLICATE_OFFERING",
                (
                    f"Offering '{offering_code}' for course "
                    f"'{course_spec.instance.code}' is already used on row "
                    f"{seen[key].row}."
                ),
            )
            continue
        seen[key] = row
        if (
            context.department.pk,
            course_spec.instance.code,
            offering_code,
        ) in existing_offerings:
            _reject(
                context,
                row,
                "offering_code",
                "OFFERING_ALREADY_EXISTS",
                (
                    f"Course '{course_spec.instance.code}' already has an offering "
                    f"'{offering_code}' in {context.semester}."
                ),
            )
            continue
        instance = CourseOffering(
            course=course_spec.instance,
            semester=context.semester,
            managing_department=context.department,
            offering_code=offering_code,
        )
        problem = _clean(instance)
        if problem is not None:
            _reject(
                context,
                row,
                problem[0],
                "COURSE_NOT_OWNED_BY_DEPARTMENT",
                problem[1],
            )
            continue
        specs.append(
            OfferingSpec(
                row=row, ref=ref, course_ref=course_ref, instance=instance
            )
        )
    return tuple(specs)


def _validate_components(
    context: _Context, offerings: tuple[OfferingSpec, ...]
) -> tuple[ComponentSpec, ...]:
    """Teaching components, validated by the Phase 3 model rules."""
    rows = _ref_rows(context, SHEET_COMPONENTS)
    if not rows:
        return ()

    offerings_by_ref = {spec.ref: spec for spec in offerings}
    specs: list[ComponentSpec] = []
    for row in rows:
        ref = row.get(REFERENCE_COLUMNS[SHEET_COMPONENTS])
        offering_ref = row.get("offering_ref")
        component_type = row.get("component_type", "").upper()
        weekly_hours = _to_decimal(row.get("weekly_hours"))
        session_duration = _to_decimal(row.get("session_duration_hours"))

        offering_spec = offerings_by_ref.get(offering_ref)
        if offering_spec is None:
            _reject(
                context,
                row,
                "offering_ref",
                "OFFERING_REF_NOT_FOUND",
                (
                    f"Offering reference '{offering_ref}' does not resolve to a "
                    "CourseOfferings row."
                ),
            )
            continue
        if component_type not in COMPONENT_TYPES:
            _reject(
                context,
                row,
                "component_type",
                "INVALID_COMPONENT_TYPE",
                (
                    f"Component type must be one of {', '.join(COMPONENT_TYPES)}; got "
                    f"'{row.get('component_type')}'."
                ),
            )
            continue
        if weekly_hours is None:
            _reject(
                context,
                row,
                "weekly_hours",
                "INVALID_NUMBER",
                "Weekly hours must be a positive number with at most two decimals.",
            )
            continue
        if session_duration is None:
            _reject(
                context,
                row,
                "session_duration_hours",
                "INVALID_NUMBER",
                (
                    "Session duration must be a positive number with at most two "
                    "decimals."
                ),
            )
            continue
        instance = TeachingComponent(
            offering=offering_spec.instance,
            component_type=component_type,
            label=row.get("label"),
            weekly_hours=weekly_hours,
            session_duration_hours=session_duration,
        )
        problem = _clean(instance)
        if problem is not None:
            _reject(
                context,
                row,
                problem[0],
                "INVALID_COMPONENT_HOURS",
                problem[1],
            )
            continue
        specs.append(
            ComponentSpec(
                row=row,
                ref=ref,
                offering_ref=offering_ref,
                instance=instance,
            )
        )
    return tuple(specs)


def _validate_component_groups(
    context: _Context,
    components: tuple[ComponentSpec, ...],
    groups: tuple[GroupSpec, ...],
) -> tuple[ComponentGroupSpec, ...]:
    """Component/group links, honouring the Phase 3 hierarchy and authority rules."""
    rows = context.workbook.rows_for(SHEET_COMPONENT_GROUPS)
    if not rows:
        return ()

    components_by_ref = {spec.ref: spec for spec in components}
    groups_by_ref = {spec.ref: spec for spec in groups}
    per_component: dict[str, set[str]] = {}
    specs: list[ComponentGroupSpec] = []
    for row in rows:
        component_ref = row.get("component_ref")
        group_ref = row.get("group_ref")
        component_spec = components_by_ref.get(component_ref)
        group_spec = groups_by_ref.get(group_ref)
        if component_spec is None:
            _reject(
                context,
                row,
                "component_ref",
                "COMPONENT_REF_NOT_FOUND",
                (
                    f"Component reference '{component_ref}' does not resolve to a "
                    "TeachingComponents row."
                ),
            )
            continue
        if group_spec is None:
            _reject(
                context,
                row,
                "group_ref",
                "GROUP_REF_NOT_FOUND",
                f"Group reference '{group_ref}' does not resolve to a StudentGroups row.",
            )
            continue
        attached = per_component.setdefault(component_ref, set())
        if group_ref in attached:
            _reject(
                context,
                row,
                "group_ref",
                "DUPLICATE_RELATION",
                f"Group '{group_ref}' is already attached to component '{component_ref}'.",
            )
            continue

        group_department_id = group_spec.instance.stage.program.department_id
        if (
            group_department_id != context.department.pk
            and not context.cross_department
        ):
            _reject(
                context,
                row,
                "group_ref",
                "CROSS_DEPARTMENT_LINK_REQUIRES_COLLEGE_ADMIN",
                (
                    "Linking another department's students into a course is reserved for "
                    "college administrators."
                ),
            )
            continue
        overlap = _hierarchy_overlap(group_spec, attached, groups_by_ref)
        if overlap is not None:
            _reject(
                context,
                row,
                "group_ref",
                "GROUP_HIERARCHY_OVERLAP",
                (
                    f"Group '{group_ref}' and group '{overlap}' are in the same "
                    "hierarchy, so attaching both would count their students twice."
                ),
            )
            continue

        attached.add(group_ref)
        specs.append(
            ComponentGroupSpec(
                row=row,
                component_ref=component_ref,
                group_ref=group_ref,
                instance=TeachingComponentGroup(
                    teaching_component=component_spec.instance,
                    student_group=group_spec.instance,
                ),
            )
        )
    return tuple(specs)


def _hierarchy_overlap(
    group_spec: GroupSpec,
    attached: set[str],
    groups_by_ref: dict[str, GroupSpec],
) -> str | None:
    """Reference of an attached group that is an ancestor or descendant of this one.

    Phase 3 rejects a component that holds both a group and one of its ancestors or
    descendants, because those students would be counted twice. The same rule is applied
    here over the workbook's own hierarchy before anything is written.
    """
    group = group_spec.instance
    for ref in attached:
        other = groups_by_ref.get(ref)
        if other is None or other.instance is group:
            continue
        if _is_ancestor(group, other.instance) or _is_ancestor(other.instance, group):
            return ref
    return None


def _is_ancestor(candidate: StudentGroup, group: StudentGroup) -> bool:
    """True when ``candidate`` is an ancestor of ``group`` inside the workbook."""
    current = group.parent_group
    seen: set[int] = set()
    while current is not None:
        if current is candidate:
            return True
        marker = id(current)
        if marker in seen:
            return False
        seen.add(marker)
        current = current.parent_group
    return False


def _validate_assignments(
    context: _Context, components: tuple[ComponentSpec, ...]
) -> tuple[AssignmentSpec, ...]:
    """Teaching assignments: existing, eligible instructors only."""
    rows = context.workbook.rows_for(SHEET_ASSIGNMENTS)
    if not rows:
        return ()

    components_by_ref = {spec.ref: spec for spec in components}
    staff_codes = {row.get("staff_code") for row in rows if row.get("staff_code")}
    instructors = {
        instructor.staff_code: instructor
        for instructor in InstructorProfile.objects.filter(staff_code__in=staff_codes)
    }

    specs: list[AssignmentSpec] = []
    seen: set[tuple[str, str]] = set()
    primary_per_component: dict[str, str] = {}
    for row in rows:
        component_ref = row.get("component_ref")
        staff_code = row.get("staff_code")
        role = row.get("assignment_role", DEFAULT_ASSIGNMENT_ROLE).upper()
        component_spec = components_by_ref.get(component_ref)
        if component_spec is None:
            _reject(
                context,
                row,
                "component_ref",
                "COMPONENT_REF_NOT_FOUND",
                (
                    f"Component reference '{component_ref}' does not resolve to a "
                    "TeachingComponents row."
                ),
            )
            continue
        instructor = instructors.get(staff_code)
        if instructor is None:
            _reject(
                context,
                row,
                "staff_code",
                "INSTRUCTOR_NOT_FOUND",
                (
                    f"No instructor profile with staff code '{staff_code}' exists. Create "
                    "the instructor first; this import never creates instructors."
                ),
            )
            continue
        if role not in ASSIGNMENT_ROLES:
            _reject(
                context,
                row,
                "assignment_role",
                "INVALID_ASSIGNMENT_ROLE",
                (
                    f"Assignment role must be one of {', '.join(ASSIGNMENT_ROLES)}; got "
                    f"'{row.get('assignment_role')}'."
                ),
            )
            continue
        if (component_ref, staff_code) in seen:
            _reject(
                context,
                row,
                "staff_code",
                "DUPLICATE_RELATION",
                (
                    f"Instructor '{staff_code}' is already assigned to component "
                    f"'{component_ref}'."
                ),
            )
            continue
        if role == AssignmentRole.PRIMARY and component_ref in primary_per_component:
            _reject(
                context,
                row,
                "assignment_role",
                "MULTIPLE_PRIMARY_INSTRUCTORS",
                (
                    f"Component '{component_ref}' already has primary instructor "
                    f"'{primary_per_component[component_ref]}'."
                ),
            )
            continue

        instance = TeachingAssignment(
            teaching_component=component_spec.instance,
            instructor=instructor,
            assignment_role=role,
        )
        problem = _assignment_problem(instructor, context.department)
        if problem is not None:
            _reject(context, row, problem[0], problem[1], problem[2])
            continue
        seen.add((component_ref, staff_code))
        if role == AssignmentRole.PRIMARY:
            primary_per_component[component_ref] = staff_code
        specs.append(
            AssignmentSpec(
                row=row, component_ref=component_ref, instance=instance
            )
        )
    return tuple(specs)


def _validate_room_requirements(
    context: _Context, components: tuple[ComponentSpec, ...]
) -> tuple[RoomRequirementSpec, ...]:
    """Room requirements per component: room types are referenced, never created."""
    rows = context.workbook.rows_for(SHEET_ROOM_REQUIREMENTS)
    if not rows:
        return ()

    components_by_ref = {spec.ref: spec for spec in components}
    type_codes = {
        row.get("required_room_type_code")
        for row in rows
        if row.get("required_room_type_code")
    }
    room_types = {
        room_type.code: room_type
        for room_type in RoomType.objects.filter(code__in=type_codes)
    }

    specs: list[RoomRequirementSpec] = []
    seen: set[str] = set()
    for row in rows:
        component_ref = row.get("component_ref")
        type_code = row.get("required_room_type_code")
        capacity = _to_int(row.get("minimum_capacity"))
        component_spec = components_by_ref.get(component_ref)
        if component_spec is None:
            _reject(
                context,
                row,
                "component_ref",
                "COMPONENT_REF_NOT_FOUND",
                (
                    f"Component reference '{component_ref}' does not resolve to a "
                    "TeachingComponents row."
                ),
            )
            continue
        if component_ref in seen:
            _reject(
                context,
                row,
                "component_ref",
                "DUPLICATE_ROOM_REQUIREMENT",
                f"Component '{component_ref}' already has a room requirement row.",
            )
            continue
        room_type = None
        if type_code:
            room_type = room_types.get(type_code)
            if room_type is None:
                _reject(
                    context,
                    row,
                    "required_room_type_code",
                    "ROOM_TYPE_NOT_FOUND",
                    (
                        f"No room type with code '{type_code}' exists. This import never "
                        "creates room types."
                    ),
                )
                continue
            if not room_type.is_active:
                _reject(
                    context,
                    row,
                    "required_room_type_code",
                    "ROOM_TYPE_INACTIVE",
                    f"Room type '{type_code}' is inactive.",
                )
                continue
        if row.get("minimum_capacity") and capacity is None:
            _reject(
                context,
                row,
                "minimum_capacity",
                "INVALID_INTEGER",
                "Minimum capacity must be a whole number of one or more.",
            )
            continue
        instance = TeachingComponentRoomRequirement(
            teaching_component=component_spec.instance,
            required_room_type=room_type,
            minimum_capacity=capacity,
        )
        problem = _clean(instance)
        if problem is not None:
            _reject(
                context,
                row,
                problem[0],
                "INVALID_VALUE",
                problem[1],
            )
            continue
        seen.add(component_ref)
        specs.append(
            RoomRequirementSpec(
                row=row, component_ref=component_ref, instance=instance
            )
        )
    return tuple(specs)


def _validate_capabilities(
    context: _Context, room_requirements: tuple[RoomRequirementSpec, ...]
) -> tuple[CapabilityRequirementSpec, ...]:
    """Required capabilities per room requirement, referenced by code."""
    rows = context.workbook.rows_for(SHEET_REQUIREMENT_CAPABILITIES)
    if not rows:
        return ()

    requirements_by_component = {
        spec.component_ref: spec for spec in room_requirements
    }
    capability_codes = {row.get("capability_code") for row in rows if row.get("capability_code")}
    capabilities = {
        capability.code: capability
        for capability in RoomCapability.objects.filter(code__in=capability_codes)
    }

    specs: list[CapabilityRequirementSpec] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        component_ref = row.get("component_ref")
        code = row.get("capability_code")
        requirement = requirements_by_component.get(component_ref)
        if requirement is None:
            _reject(
                context,
                row,
                "component_ref",
                "ROOM_REQUIREMENT_MISSING",
                (
                    f"Component '{component_ref}' has no RoomRequirements row, so it "
                    "cannot require a capability."
                ),
            )
            continue
        if not code:
            _reject(
                context,
                row,
                "capability_code",
                "MISSING_VALUE",
                "A capability code is required.",
            )
            continue
        capability = capabilities.get(code)
        if capability is None:
            _reject(
                context,
                row,
                "capability_code",
                "CAPABILITY_NOT_FOUND",
                (
                    f"No room capability with code '{code}' exists. This import never "
                    "creates capabilities."
                ),
            )
            continue
        if not capability.is_active:
            _reject(
                context,
                row,
                "capability_code",
                "CAPABILITY_INACTIVE",
                f"Capability '{code}' is inactive.",
            )
            continue
        if (component_ref, code) in seen:
            _reject(
                context,
                row,
                "capability_code",
                "DUPLICATE_RELATION",
                f"Capability '{code}' is already required by component '{component_ref}'.",
            )
            continue
        seen.add((component_ref, code))
        specs.append(
            CapabilityRequirementSpec(
                row=row,
                component_ref=component_ref,
                instance=TeachingComponentCapabilityRequirement(
                    room_requirement=requirement.instance, capability=capability
                ),
            )
        )
    return tuple(specs)


def _assignment_problem(instructor, department):
    """Eligibility of one instructor for the request department.

    The rules are the Phase 4 ones - an active profile, and
    :meth:`InstructorProfile.can_teach_in_department` for the department that manages the
    offering - applied explicitly rather than through ``TeachingAssignment.clean()``,
    because that validator queries the component's existing assignments and the component
    does not exist yet at validation time. Sharing is therefore enforced from the same
    single source of truth the API uses, so a workbook can never grant itself an
    instructor the department could not assign through the API.
    """
    if not instructor.is_active:
        return (
            "staff_code",
            "INSTRUCTOR_INACTIVE",
            "Inactive instructors cannot hold active assignments.",
        )
    if not instructor.can_teach_in_department(department):
        return (
            "staff_code",
            "INSTRUCTOR_NOT_ELIGIBLE",
            (
                "This instructor is not allowed to teach in the managing department of "
                "the offering. Change the instructor's sharing first."
            ),
        )
    return None


def _warn_missing_assignments(
    context: _Context,
    components: tuple[ComponentSpec, ...],
    assignments: tuple[AssignmentSpec, ...],
) -> None:
    """Warn about a plan that is stored but not yet teachable.

    Both warnings are informational: the import is still applied, because the plan may be
    completed in a later workbook or through the API. They do not block, and they never
    replace the Phase 7 readiness report.
    """
    linked = {spec.component_ref for spec in assignments}
    primary = {
        spec.component_ref
        for spec in assignments
        if spec.instance.assignment_role == AssignmentRole.PRIMARY
    }
    grouped = {
        row.get("component_ref")
        for row in context.workbook.rows_for(SHEET_COMPONENT_GROUPS)
        if row.get("component_ref")
    }
    for component in components:
        if component.ref in linked and component.ref not in primary:
            context.collector.warn(
                sheet=SHEET_COMPONENTS,
                row=component.row.row,
                code="NO_PRIMARY_INSTRUCTOR",
                message=(
                    "This component has assignments but no active primary instructor."
                ),
                column="component_ref",
            )
        if component.ref not in grouped:
            context.collector.warn(
                sheet=SHEET_COMPONENTS,
                row=component.row.row,
                code="COMPONENT_WITHOUT_GROUP",
                message="This component has no student group attached yet.",
                column="component_ref",
            )


__all__ = [
    "AssignmentSpec",
    "CapabilityRequirementSpec",
    "ComponentGroupSpec",
    "ComponentSpec",
    "CourseSpec",
    "GroupSpec",
    "OfferingSpec",
    "RoomRequirementSpec",
    "ValidatedPlan",
    "validate_plan",
]
