# College Academic Schedule Planner — Backend

Django REST Framework backend for the College Academic Schedule Planner.
Provides the project foundation (configuration package, domain app skeletons,
custom user model, API/OpenAPI plumbing) that later phases build on.

- Current phase: **Phase 15 — Excel/PDF export and controlled Excel import** (read-only
  timetable and report downloads over persisted versions and the published timetable,
  plus a validate-then-apply semester teaching plan import).

## Architecture

```
sch_planner_backend/
├── config/            # Django project/configuration package
│   ├── settings.py    # environment-driven settings
│   ├── urls.py        # root URLconf: /admin/ and /api/
│   ├── api_urls.py    # /api/ namespace (health, app URLconfs, schema, docs)
│   ├── views.py       # project-level API views (health probe)
│   ├── asgi.py
│   └── wsgi.py
├── accounts/          # custom user model, roles, permissions, auth API
│   ├── models.py      # User (AbstractUser) + UserRole
│   ├── permissions.py # reusable role and department-scope permissions
│   ├── serializers.py # current-user representation
│   ├── views.py       # login, refresh, /api/me/
│   └── urls.py        # /api/auth/*, /api/me/
├── academics/         # academic structure
│   ├── models.py      # College, Department, AcademicYear, Semester,
│   │                  # StudyProgram, StudyStage, StudentGroup,
│   │                  # Course, CourseOffering, TeachingComponent,
│   │                  # TeachingComponentGroup, Weekday (Sunday→Thursday)
│   ├── permissions.py # role, department and joint-teaching visibility rules
│   ├── serializers.py # read/write serializers + nested summaries
│   ├── views.py       # DRF viewsets (no hard delete)
│   ├── urls.py        # /api/colleges/, /api/departments/, /api/courses/, ...
│   └── migrations/    # 0001_initial, 0002_academic_structure,
│                      # 0003_teaching_structure
├── resources/         # instructors, rooms and their teaching requirements
│   ├── models.py      # InstructorProfile, InstructorDepartmentAccess,
│   │                  # InstructorAvailability, InstructorPreference,
│   │                  # TeachingAssignment, RoomType, RoomCapability, Room,
│   │                  # RoomDepartmentAccess, RoomCapabilityAssignment,
│   │                  # RoomAvailability, TeachingComponentRoomRequirement,
│   │                  # TeachingComponentCapabilityRequirement
│   ├── permissions.py # instructor and room read-visibility rules
│   ├── serializers.py # read/write serializers + summaries
│   ├── views.py       # viewsets + /api/me/teaching-assignments/
│   ├── urls.py        # /api/instructors/, /api/rooms/, ...
│   └── migrations/    # 0001_initial, 0002_rooms_and_requirements
├── scheduling/        # calendar, time configuration, solver and persistence
│   ├── models.py      # WorkingDay, TimeSlot, BreakPeriod, CalendarException,
│   │                  # Schedule, ScheduleVersion, ScheduleEntry and its slot,
│   │                  # instructor and student-group snapshot children
│   ├── services/      # domain logic kept out of the views
│   │   ├── validation/# issues, time_grid, resources, validator
│   │   ├── solver/    # domain, validator, model_builder, solver, result
│   │   ├── generation/# blocks, candidates, preferences, preview, service
│   │   ├── persistence/# snapshots, service (version history writer)
│   │   ├── manual_edit/# domain, issues, validator, cloning, service
│   │   ├── workflow/  # issues, validation, service, publication
│   │   ├── analytics/ # domain, summary, workload, rooms, gaps, quality, service
│   │   ├── exports/   # domain, tables, excel, pdf, filenames, service
│   │   └── imports/   # domain, issues, workbook, template, validator, applier, service
│   ├── permissions.py # calendar visibility, validation scope, schedule read/edit scope
│   ├── serializers.py # resource, validation, generation and persistence contracts
│   ├── views.py       # time-grid viewsets, generation endpoints, schedule read APIs
│   ├── urls.py        # /api/working-days/, /api/scheduling/generate/, /api/schedules/
│   └── migrations/    # 0001_calendar_and_time_configuration,
│                      # 0002_schedule_persistence,
│                      # 0003_manual_edit_support, 0004_workflow_publication
├── reports/           # reserved for later report artifacts (Phase 15 exports are
│                      # generated on request in scheduling/services/exports/)
├── tests/             # pytest suite for the whole project
├── manage.py
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

Phase 5 adds physical teaching spaces (rooms and laboratories) with sharing,
capabilities, weekly availability and the room requirements that teaching
components declare. Phase 6 adds the college time configuration the scheduler
will search: which weekdays each semester teaches, the teaching periods and
breaks inside those days, and the dated exceptions (holidays, exams, closures,
absences) that remove availability. Phase 7 adds a computed pre-scheduling
validator that reports whether the stored data is ready for timetable
generation. Phase 8 adds the generic CP-SAT engine that turns a prepared discrete
problem into a conflict-free assignment. Phase 9 adds the department scheduler: it
builds that prepared problem from the stored academic, resource and calendar data
and returns a preview timetable. **Nothing is persisted yet** - no `Schedule`,
`ScheduleVersion` or `ScheduleEntry` model exists - and college-wide generation is
Phase 10. Reports and the Flutter instructor app follow later.

## Requirements

- Python 3.12+
- SQLite (bundled with Python; no separate database server needed yet)

## Local setup

All commands assume the repository root `~/PycharmProjects/sch_planner_backend`.

Create the virtual environment and install dependencies:

```bash
cd ~/PycharmProjects/sch_planner_backend
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Activate it in your shell if you prefer (`source .venv/bin/activate`).

Create your local environment file (never committed):

```bash
cp .env.example .env
```

`DJANGO_SECRET_KEY` may stay as the placeholder for local development; a real
secret is required as soon as `DJANGO_DEBUG=False`.

Apply migrations (creates `db.sqlite3`):

```bash
.venv/bin/python manage.py migrate
```

Run the development server:

```bash
.venv/bin/python manage.py runserver
```

## Tests

```bash
.venv/bin/python -m pytest
```

## API endpoints

| Method | Path                 | Auth          | Purpose                            |
| ------ | -------------------- | ------------- | ---------------------------------- |
| GET    | `/admin/`            | staff         | Django admin                       |
| GET    | `/api/health/`       | public        | Liveness probe                     |
| POST   | `/api/auth/login/`   | public        | Obtain JWT access/refresh tokens   |
| POST   | `/api/auth/refresh/` | public        | Refresh an access token            |
| GET    | `/api/me/`           | authenticated | Current user identity, role, dept. |
| GET    | `/api/me/teaching-assignments/` | authenticated | Own active teaching assignments |
| GET    | `/api/schema/`       | public        | OpenAPI 3 schema                   |
| GET    | `/api/docs/`         | public        | Swagger UI for the schema          |

All resource APIs expose the same five operations — `GET` list, `GET` detail,
`POST`, `PUT`, `PATCH`:

| Resource                  | Path                               | Department scope path                 |
| ------------------------- | ---------------------------------- | ------------------------------------- |
| Colleges                  | `/api/colleges/`                   | college-wide                          |
| Departments               | `/api/departments/`                | the department itself                 |
| Academic years            | `/api/academic-years/`             | college-wide                          |
| Semesters                 | `/api/semesters/`                  | college-wide                          |
| Study programs            | `/api/programs/`                   | `program.department`                  |
| Study stages              | `/api/stages/`                     | `stage.program.department`            |
| Student groups            | `/api/student-groups/`             | `group.stage.program.department`      |
| Courses                   | `/api/courses/`                    | `course.department` (+ joint teaching) |
| Course offerings          | `/api/course-offerings/`           | managing department (+ joint teaching) |
| Teaching components       | `/api/teaching-components/`        | offering's managing department (+ joint) |
| Teaching component groups | `/api/teaching-component-groups/`  | component *and* student group          |
| Instructor profiles       | `/api/instructors/`                | `instructor.primary_department` (+ sharing) |
| Instructor access grants  | `/api/instructor-department-access/` | grant's instructor primary department |
| Instructor availability   | `/api/instructor-availability/`    | availability's instructor primary department |
| Instructor preferences    | `/api/instructor-preferences/`     | preference's instructor primary department |
| Teaching assignments      | `/api/teaching-assignments/`       | component's offering managing department |
| Room types                | `/api/room-types/`                 | college-wide (writes: college admin)   |
| Room capabilities         | `/api/room-capabilities/`          | college-wide (writes: college admin)   |
| Rooms                     | `/api/rooms/`                      | `room.owner_department` (+ sharing)    |
| Room access grants        | `/api/room-department-access/`     | grant's room owner department          |
| Room capability assignments | `/api/room-capability-assignments/` | assignment's room owner department   |
| Room availability         | `/api/room-availability/`          | availability's room owner department   |
| Room requirements         | `/api/teaching-component-room-requirements/` | component's offering managing department |
| Capability requirements   | `/api/teaching-component-capability-requirements/` | component's offering managing department |
| Working days              | `/api/working-days/`               | college-wide (writes: college admin)   |
| Time slots                | `/api/time-slots/`                 | college-wide (writes: college admin)   |
| Break periods             | `/api/break-periods/`              | college-wide (writes: college admin)   |
| Calendar exceptions       | `/api/calendar-exceptions/`        | scope-dependent (see the calendar section) |
| Scheduling validation     | `POST /api/scheduling/validate/`   | see the validation section below       |
| Department generation     | `POST /api/scheduling/generate/`   | own department (college admin: any)    |
| College generation        | `POST /api/scheduling/generate-college/` | college administrator or superuser only |
| Department draft          | `POST /api/schedules/generate-department-draft/` | own department (college admin: any) |
| College draft             | `POST /api/schedules/generate-college-draft/` | college administrator or superuser only |
| Schedule reads            | `GET /api/schedules/`, `/api/schedule-versions/` | college admin, or own-department drafts |
| Manual edit validate      | `POST /api/schedule-versions/{id}/validate-manual-edit/` | college admin, or own-department draft |
| Manual edit apply         | `POST /api/schedule-versions/{id}/manual-edit/` | college admin, or own-department draft |
| Workflow validation       | `GET /api/schedule-versions/{id}/workflow-validation/` | management roles, in scope |
| Workflow transitions      | `POST /api/schedule-versions/{id}/submit\|review\|approve\|publish/` | see the workflow section |
| Published timetable       | `GET /api/published-schedules/current/?semester=` | any authenticated user, filtered by role |
| Version analytics         | `GET /api/schedule-versions/{id}/analytics/` | schedule read roles, in scope (see the analytics section) |
| Published analytics       | `GET /api/published-schedules/current/analytics/?semester=` | management roles, filtered by role |
| Version export (Excel)    | `GET /api/schedule-versions/{id}/export/xlsx/` | schedule read roles, in scope |
| Version export (PDF)      | `GET /api/schedule-versions/{id}/export/pdf/` | schedule read roles, in scope |
| Published export (Excel)  | `GET /api/published-schedules/current/export/xlsx/?semester=` | management roles, filtered by role |
| Published export (PDF)    | `GET /api/published-schedules/current/export/pdf/?semester=` | management roles, filtered by role |
| Import template           | `GET /api/imports/semester-plan/template/` | college or department administrator |
| Import validate           | `POST /api/imports/semester-plan/validate/` (multipart) | college or department administrator |
| Import apply              | `POST /api/imports/semester-plan/apply/` (multipart) | college or department administrator |

Write ownership in this table is stricter than read visibility for shared
resources: shared instructors and rooms are readable by the departments they are
shared with, and joint-course components are readable by participating
departments, but writes always stay with the owning department. Simple
exact-match query filters are available on the resource endpoints
(`primary_department`, `owner_department`, `room_type`, `sharing_scope`,
`instructor`, `room`, `semester`, `day_of_week`, `preference_type`,
`capability`, `assignment_role`, `is_active`, `working_day`, `date`,
`exception_type`, `scope_type`, `department`, `student_group`); invalid filter
values answer `400`.

`DELETE` is intentionally not part of the API: the detail routes exist but
answer **405 Method Not Allowed**. Lifecycle is managed with `is_active`.

Requests with payloads must send `Content-Type: application/json`; the API is
configured with DRF's `JSONParser` only, so other content types answer `415`.

Health response:

```json
{ "status": "ok", "service": "sch_planner_backend" }
```

Swagger UI: <http://127.0.0.1:8000/api/docs/>

## Authentication

JSON Web Tokens (SimpleJWT, bearer header). Login:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "ahmed", "password": "secret"}'
```

```json
{ "access": "<jwt>", "refresh": "<jwt>" }
```

Only the tokens are returned — no user details, no password material. Invalid
credentials and inactive accounts both answer `401`. The access token lives 30
minutes, the refresh token 7 days (see `SIMPLE_JWT` in `config/settings.py`).

Refresh:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<jwt>"}'
```

```json
{ "access": "<jwt>" }
```

Refreshing re-checks the token's user on every call: a user deactivated after
receiving a refresh token can no longer refresh, and an access token belonging
to a deactivated user is rejected on the next request.

Current user:

```bash
curl http://127.0.0.1:8000/api/me/ -H "Authorization: Bearer <access>"
```

```json
{
  "id": 12,
  "username": "ahmed",
  "email": "ahmed@example.com",
  "first_name": "Ahmed",
  "last_name": "Hassan",
  "full_name": "Ahmed Hassan",
  "role": "DEPARTMENT_ADMIN",
  "department": { "id": 3, "name": "Biomedical Applications", "code": "BIOAI" }
}
```

`department` is `null` when the user has no department (college administrators
may have none). `full_name` falls back to the username when both name fields
are blank. `/api/me/` is read-only: role and department cannot be written
through it.

## Roles and permissions

Roles live on `accounts.User.role` (a `TextChoices` field, no separate role
table) and default to the least-privilege `VIEWER`:

| Role               | Meaning                                             |
| ------------------ | --------------------------------------------------- |
| `COLLEGE_ADMIN`    | College-wide administrator, may have no department  |
| `DEPARTMENT_ADMIN` | Administrator of one department                     |
| `SCHEDULER`        | Builds and maintains schedules                      |
| `VIEWER`           | Read-only access (default)                          |
| `INSTRUCTOR`       | Teaching staff                                      |

Reusable DRF permission classes in `accounts/permissions.py`:

| Class                             | Grants access to                                        |
| --------------------------------- | ------------------------------------------------------- |
| `IsCollegeAdmin`                  | `COLLEGE_ADMIN` (and Django superusers)                 |
| `IsDepartmentAdmin`               | `DEPARTMENT_ADMIN` (and Django superusers)               |
| `IsScheduler`                     | `SCHEDULER`                                              |
| `IsViewer`                        | `VIEWER`                                                 |
| `IsInstructor`                    | `INSTRUCTOR`                                             |
| `IsCollegeOrDepartmentAdmin`      | either administrative role (and Django superusers)       |
| `IsSameDepartmentOrCollegeAdmin`  | object-level department scoping (see below)              |

Decisions, applied consistently:

- Every permission requires an authenticated **and active** user; inactive
  users are always rejected (defence in depth — SimpleJWT also refuses them).
- Django superusers pass the *administrative* checks (`is_superuser` is a
  framework-level operator concept, not an application role) but not the
  functional ones (`IsScheduler`, `IsViewer`, `IsInstructor`).
- `IsSameDepartmentOrCollegeAdmin` lets superusers and college administrators
  reach objects in any department, while other users only reach objects whose
  persisted department matches `request.user.department`. It accepts a
  `Department` instance, objects with a `department_id`, or objects with a
  `department` relation, fails closed when the department cannot be determined,
  and never trusts a department id coming from the request body.
- Views must reuse these classes instead of comparing role strings inline.

## Academic structure

`academics` implements the hierarchy and the college calendar:

```
College
└── Department
    └── StudyProgram            study_type: UNDERGRADUATE | MASTER | PHD
        └── StudyStage          number (>= 1) + free-form name
            └── StudentGroup    code + student_count
                └── StudentGroup  optional subgroup hierarchy (parent_group)

AcademicYear  2026-2027
└── Semester   number 1 or 2, optional start/end dates
```

| Model | Key fields | Notable rules |
| --- | --- | --- |
| `College` | `name`, unique `code`, `is_active`, timestamps | one college per deployment today; no multi-college tenancy |
| `Department` | `college` (optional), `name`, unique `code`, `is_active`, timestamps | `college` is nullable so Phase 1 rows stay valid; the API requires it on create |
| `AcademicYear` | `start_year`, `end_year`, `is_active`, timestamps | `end_year = start_year + 1`; `(start_year, end_year)` unique |
| `Semester` | `academic_year`, `number`, `start_date`, `end_date`, `is_active`, timestamps | `(academic_year, number)` unique; `end_date >= start_date` when both are set |
| `StudyProgram` | `department`, `name`, `code`, `study_type`, `is_active`, timestamps | `(department, code)` unique — the same code may exist in another department |
| `StudyStage` | `program`, `number`, `name`, `is_active`, timestamps | `(program, number)` unique; stage count is not hard-coded |
| `StudentGroup` | `stage`, `name`, `code`, `student_count`, `parent_group`, `is_active`, timestamps | `(stage, code)` unique; a subgroup must share its parent's stage, cannot parent itself and cannot form a cycle |

Rules SQL can express live in the database (unique constraints plus check
constraints for consecutive years, semester date order, positive stage number,
non-negative student counts and self-parenting). Cross-row rules — subgroup
stage and cycle checks — live in `Model.clean()`, and the API serializers run
the same `clean()`, so predictable invalid input answers `400` instead of
failing at the database level.

`accounts.User.department` stays optional (`SET_NULL`), so users can exist
without a department.

## Study types

`study_type` is a stable enum (`academics.StudyType`): `UNDERGRADUATE`,
`MASTER`, `PHD`. Arbitrary free-text study types are not accepted.

## Teaching structure

Courses are reusable catalog definitions; actual delivery lives on offerings and
their components.

```
Course                     CourseOffering                     TeachingComponent
Machine Learning (ML301) → 2026-2027 · Sem 1 · [MAIN]      →  THEORY     4h/week, 2h sessions
                                                              PRACTICAL  3h/week, 1.5h sessions
                                                                   ↓
                                          TeachingComponentGroup → StudentGroup (or subgroup)
```

| Model | Key fields | Notable rules |
| --- | --- | --- |
| `Course` | `department`, `name`, `code`, `description`, `is_active`, timestamps | `(department, code)` unique; holds no professor, hours, room, year or semester data — the catalog entry is reusable |
| `CourseOffering` | `course`, `semester`, `managing_department`, `offering_code` (default `MAIN`), `is_active`, timestamps | `(course, semester, offering_code)` unique — several offerings per semester are possible; `managing_department` must be the department that owns the course; the academic year comes from `semester`; `total_weekly_hours` is derived from the active components |
| `TeachingComponent` | `offering`, `component_type`, `label`, `weekly_hours`, `session_duration_hours`, `is_active`, timestamps | type is `THEORY` or `PRACTICAL`; hours are `DECIMAL` (never binary floating point) and must be `> 0`; the session count must be whole; `sessions_per_week` is derived and never stored |
| `TeachingComponentGroup` | `teaching_component`, `student_group`, `created_at` | `(teaching_component, student_group)` unique; one component may not contain a group together with its ancestor or descendant |

### Weekly hours, session duration, sessions per week

| `weekly_hours` | `session_duration_hours` | `sessions_per_week` |
| --- | --- | --- |
| 4 | 2 | 2 |
| 3 | 1.5 | 2 |
| 2.5 | 0.5 | 5 |
| 3 | 2 | rejected (`400`) — would be 1.5 sessions |

Invalid combinations are rejected with `400` and never silently rounded.
`total_weekly_hours` on an offering sums the weekly hours of its **active**
components only.

### Which groups attend a component

`TeachingComponentGroup` is an explicit resource rather than an implicit M2M
table because it carries authorization and validation. It expresses:

- **single class** — component → Group A
- **combined groups** — component → Group A + Group B (one shared lecture)
- **practical subgroups** — practical component 1 → A1, practical component 2 → A2
- **joint inter-department courses** — one component → groups from several
  departments' stages

Within one component a group may not be combined with its own ancestor or
descendant (that would represent the same students twice); siblings and
unrelated groups are valid.

### Joint courses

An offering has exactly one `managing_department` (the course owner). Groups
from other departments may attend its components. Those departments can **read**
the course, offering, component and relation rows, but never write them; linking
another department's student group is reserved for `COLLEGE_ADMIN`/superusers so
one department cannot unilaterally enrol another department's students.

## Instructor resources

Instructors are first-class academic resources: an `InstructorProfile` is what
gets scheduled, while `accounts.User` remains the authentication identity. A
profile is valid **without** an account, so instructors can be entered
administratively long before logins exist.

| Model | Key fields | Notable rules |
| --- | --- | --- |
| `InstructorProfile` | `primary_department`, `full_name`, `staff_code`, `academic_title`, `user` (optional), `max_weekly_hours`, `max_daily_hours`, `sharing_scope`, `is_active`, timestamps | `staff_code` unique when present (blank is stored as `NULL`, so many instructors may have none); limits must be `> 0` with `max_daily_hours <= max_weekly_hours`; a linked account must already hold the `INSTRUCTOR` role and belong to the primary department — linking never mutates the account |
| `InstructorDepartmentAccess` | `instructor`, `department`, `is_active`, timestamps | one row per instructor/department; the primary department cannot be granted (it already has inherent access) |
| `InstructorAvailability` | `instructor`, `semester`, `day_of_week`, `start_time`, `end_time`, `is_active`, timestamps | recurring **hard** availability; `start_time < end_time`; active windows may not overlap on the same weekday (adjacent boundaries are fine, exact duplicates are blocked by a partial unique index) |
| `InstructorPreference` | as availability plus `preference_type` (`PREFERRED`/`AVOID`), timestamps | **soft** preference: `AVOID` is not unavailability; same window and overlap rules |
| `TeachingAssignment` | `teaching_component`, `instructor`, `assignment_role` (`PRIMARY`/`ASSISTANT`), `is_active`, timestamps | one row per instructor/component; at most **one active `PRIMARY`** per component (partial unique index); multiple assistants are allowed |

The college week is **Sunday → Thursday** (`academics.Weekday`, shared with the
later calendar/time-slot phase). Absence of availability rows means
"availability not configured", never "unrestricted" — the pre-scheduling
validation phase decides what to do about that.

### Sharing scopes

| Scope | Meaning |
| --- | --- |
| `PRIVATE` (default) | may teach only in the primary department |
| `SELECTED_DEPARTMENTS` | may also teach in departments holding an **active** `InstructorDepartmentAccess` row |
| `COLLEGE_WIDE` | may teach in any active department |

`InstructorProfile.can_teach_in_department(department)` is the single eligibility
helper reused by assignment validation (inactive instructor → never; primary
department → always; `PRIVATE` → nothing else; `SELECTED_DEPARTMENTS` → active
grant required; `COLLEGE_WIDE` → active department). It applies to **every**
writer, including college administrators, who must adjust sharing first.
Changing a scope never deletes stored access rows; a non-selected scope simply
ignores them.

### Teaching assignments

`TeachingAssignment` links an instructor to a `TeachingComponent` — no
instructor fields were added to `Course` or `TeachingComponent`. Active
assignments require an active instructor, component, offering and course, plus
eligibility for the offering's managing department:

```
Dr. Ahmed — primary: Computer Science, scope: SELECTED_DEPARTMENTS
  access grant: Biomedical Applications
  → assignment to "Programming for Biomedical Applications"
    (managing department: Biomedical Applications)        accepted

Same instructor, no access grant                           rejected (400)
```

`GET /api/me/teaching-assignments/` returns the active assignments of the
instructor linked to the authenticated account, and `[]` when the account has no
instructor profile. It prepares the future Flutter instructor app; it is not a
timetable endpoint.

### Availability vs. instructor visibility

Availability and preferences are readable by the primary department and by
departments the instructor is actually shared with — **not** merely because the
instructor teaches one joint course. A participating department sees who teaches
the joint course (read-only) but cannot assign that instructor elsewhere, and
cannot inspect their full weekly availability.

## Room resources

Physical teaching spaces are modelled as owned resources with sharing, plus the
room requirements that teaching components state for later scheduling.

| Model | Key fields | Notable rules |
| --- | --- | --- |
| `RoomType` | `name`, unique `code`, `description`, `is_active`, timestamps | college-wide vocabulary (`LECTURE_HALL`, `COMPUTER_LAB`, ...); writable by college admins only |
| `RoomCapability` | `name`, unique `code`, `description`, `is_active`, timestamps | college-wide equipment vocabulary (`COMPUTERS`, `PROJECTOR`, ...); writable by college admins only |
| `Room` | `owner_department`, `name`, unique `code`, `room_type`, `capacity` (>= 1), `sharing_scope`, `is_active`, timestamps | globally unique physical room code; ownership is `PROTECT`ed; `capacity` must be at least 1 |
| `RoomDepartmentAccess` | `room`, `department`, `is_active`, timestamps | one row per room/department; the owner department cannot be granted (it already has access) |
| `RoomCapabilityAssignment` | `room`, `capability`, `created_at` | one row per room/capability; capabilities are rows, never comma-separated text |
| `RoomAvailability` | `room`, `semester`, `day_of_week`, `start_time`, `end_time`, `is_active`, timestamps | recurring weekly windows; `start_time < end_time`; active windows may not overlap (adjacent boundaries are fine, exact duplicates blocked by a partial unique index) |
| `TeachingComponentRoomRequirement` | `teaching_component` (one-to-one), `required_room_type` (nullable), `minimum_capacity` (nullable), `is_active`, timestamps | one requirement per component; `null` room type means no type restriction; derived values are read-only |
| `TeachingComponentCapabilityRequirement` | `room_requirement`, `capability`, `created_at` | one row per requirement/capability; every required capability must be present in a room |

### Room sharing scopes

| Scope | Meaning |
| --- | --- |
| `PRIVATE` (default) | usable only by the owner department |
| `SELECTED_DEPARTMENTS` | also usable by departments holding an **active** `RoomDepartmentAccess` row |
| `COLLEGE_WIDE` | usable by any active department |

`Room.can_be_used_by_department(department)` is the canonical sharing rule: an
inactive room or inactive room type is never usable, the owner department always
may use it, `SELECTED_DEPARTMENTS` requires an active grant, `COLLEGE_WIDE`
allows any active department. Changing a scope never deletes stored grants; a
non-selected scope simply ignores them.

### Capacity rules

```
expected_student_count      = sum of student_count of the groups attached to the component
effective_minimum_capacity = max(expected_student_count, minimum_capacity if supplied)
```

With groups of 25 and 30 students the expected count is 55; supplying
`minimum_capacity = 60` raises the effective minimum to 60, and leaving it
`null` keeps 55. Both values are derived at read time and never stored.

### Room suitability helper

`Room.evaluate_suitability(requirement)` returns the reasons a room does **not**
satisfy a requirement (room/room-type activity, access for the offering's
managing department, required room type, effective minimum capacity, and every
required capability — an "all capabilities" rule, never "any").
`Room.meets_requirement(requirement)` is the boolean form, and
`Room.is_suitable_for_teaching_component(component)` is deliberately
conservative: a component **without an active room requirement** is never
reported as suitable, because nothing states what it needs. Time slots are not
part of the helper yet.

### Shared rooms do not transfer ownership

A department that may use another department's room can see the room, its
capabilities and its availability, and can later schedule into it — but it can
never rename it, change its capacity, type, sharing scope, capabilities or
availability, nor grant it to a third department. Only the owner department (or
a college administrator) controls the resource.

**Actual room assignment is not implemented yet.** Teaching components define
requirements only; the room a session finally uses belongs to future
timetable/schedule entries, and room double-booking detection arrives with that
scheduling layer.

## Calendar and time configuration

The time grid describes when a semester may teach at all. A working day gives one
schedulable weekday of a semester with its opening hours, time slots are the
teaching periods inside it, and breaks carve out the gaps (morning break, lunch,
prayer). Weekdays reuse the shared `academics.Weekday` numbering
(Sunday = 0 … Thursday = 4); Friday and Saturday are not ordinary working days
in this version, and nothing assumes all five weekdays exist — each semester is
configured explicitly.

```
Semester ──< WorkingDay (one per weekday) ──< TimeSlot   (sequence 1, 2, 3, ...)
                                          └─< BreakPeriod (named gaps)
Semester ──< CalendarException (dated removals, scoped)
```

| Resource | Notable fields |
| --- | --- |
| Working day | `semester`, `day_of_week` (+ `day_of_week_code`, `day_of_week_display`), `start_time`, `end_time`, `is_active` |
| Time slot | `working_day`, `sequence`, `label`, `start_time`, `end_time`, `duration_minutes` (derived), `is_active` |
| Break period | `working_day`, `name`, `start_time`, `end_time`, `is_active` |
| Calendar exception | `semester`, `date`, `exception_type`, `scope_type`, `target` (derived), `title`, `description`, `start_time`, `end_time`, `is_full_day` (derived), `is_active` |

`day_of_week` is exposed as the shared integer plus a stable `day_of_week_code`
(`SUNDAY`) for clients that prefer names. `duration_minutes` and `is_full_day`
are computed at read time and never stored.

### Grid consistency rules

A working day must end after it starts, and one weekday may appear only once per
semester. Narrowing a working day must not silently invalidate what already
exists: if an active time slot or break would fall outside the new window, the
update is rejected with `400` and the offending rows are named. A time slot must
fit inside its working day and follow a positive `sequence` that is unique
within the day, and slots and breaks may not overlap each other in either
direction — creating a break over an existing slot fails exactly like creating a
slot over an existing break. Inactive rows neither conflict nor block, so the
grid can be reshaped before it is switched on.

### Calendar exceptions

An exception removes availability on one date. `exception_type` says what it is
(`HOLIDAY`, `EXAM`, `EVENT`, `MAINTENANCE`, `INSTRUCTOR_ABSENCE`,
`ROOM_CLOSURE`) and `scope_type` says what it affects:

| Scope | Target field | Owning department |
| --- | --- | --- |
| `COLLEGE` | none | college-wide |
| `DEPARTMENT` | `department` | the department |
| `INSTRUCTOR` | `instructor` | `instructor.primary_department` |
| `ROOM` | `room` | `room.owner_department` |
| `STUDENT_GROUP` | `student_group` | `student_group.stage.program.department` |

Exactly the target matching the scope must be set, and no second target may be
sent. `INSTRUCTOR_ABSENCE` is pinned to the instructor scope and `ROOM_CLOSURE`
to the room scope. Omitting both times makes a full-day exception; supplying one
without the other, or an end before the start, answers `400`. When the semester
has published dates, the exception date must fall inside them.

The read shape returns the exception, not the whole resource graph: `target`
carries the single summary matching the scope (`null` for college-wide) plus the
derived `is_full_day` flag.

### What a department can see

College-wide and own-department exceptions are visible to a department, along
with instructor exceptions for instructors shared with it, room exceptions for
rooms it may use, and group exceptions for its own groups. A joint course alone
does not expose another department's absence or closure records, and a user
without a department still reads the college-wide exceptions — those affect
everybody — but nothing else. Writes need a college administrator, or a
department administrator acting on a resource its own department owns — a
department administrator cannot create a college-wide exception, and cannot move
an owned exception onto a foreign instructor, room or group.

### The grid is configuration, not assignment

Working days, time slots and breaks say *when teaching is possible*, never *who
teaches what where*. Nothing in this phase attaches a teaching component,
instructor, room or student group to a slot, and no double-booking is prevented
— that belongs to schedule entries and the pre-scheduling validator in later
phases.

## Pre-scheduling validation

Timetable generation is expensive and its failures are opaque, so the backend can
report — before any solver runs — what would make generation fail. The validator
reads the data already stored in the backend and returns a computed report.

```
POST /api/scheduling/validate/
```

```json
{ "semester": 3, "scope": "DEPARTMENT", "department": 2 }
```

```json
{ "semester": 3, "scope": "COLLEGE" }
```

`scope` is either `COLLEGE` or `DEPARTMENT`, and the two shapes never overlap: a
college-wide run must omit `department`, a department run must supply exactly
one. Ambiguous or malformed input is rejected with `400`, an unknown semester or
department id with `400`, a caller whose role may not run validation (or a
department-scoped caller without a department) with `403`, and an existing
department outside the caller's scope with `400` — the same convention earlier
phases use for out-of-scope payload references. Nothing about another
department's data is revealed either way.

**Nothing is written.** The endpoint is read/compute only: no saves, no temporary
records, no automatic corrections, and no database table for results.

### Who may validate

| Caller | May validate |
| --- | --- |
| `COLLEGE_ADMIN`, Django superuser | the whole college, or any single department |
| `DEPARTMENT_ADMIN`, `SCHEDULER` | its own department only — never the whole college, and never another department by submitting its id |
| `VIEWER`, `INSTRUCTOR` | nothing (`403`) |
| department-scoped user with no department | nothing (`403`, fail closed) |

### Response contract

```json
{
  "ready": false,
  "scope": "DEPARTMENT",
  "semester": { "id": 3, "number": 1, "academic_year": "2026-2027", "academic_year_id": 2 },
  "department": { "id": 2, "name": "Biomedical Applications", "code": "BIOAI" },
  "summary": { "components_checked": 18, "errors": 4, "warnings": 2 },
  "issues": [
    {
      "code": "PRIMARY_INSTRUCTOR_MISSING",
      "severity": "ERROR",
      "message": "This teaching component has no active primary instructor.",
      "entity_type": "TeachingComponent",
      "entity_id": 15,
      "details": { "course_code": "BIO201", "component_type": "THEORY" }
    }
  ]
}
```

`ready` is **true only when there are zero `ERROR` issues**; warnings never make a
run un-ready. `department` is `null` for a college-wide run. `components_checked`
counts the teaching components treated as timetable demand, so a component whose
offering, course or managing department is switched off is reported but not
counted.

`entity_type` is the model name of the row the issue is reported against, and
`entity_id` its primary key. Messages are written for humans and never echo a
Python exception. `details` carries scalars specific to the code.

### What it checks

**Scope population.** `DEPARTMENT` validates the active components of active
offerings for the requested semester whose managing department is the requested
department; `COLLEGE` validates every active component of the semester. Other
semesters are ignored, and inactive components are never treated as demand.
Components may legitimately serve groups of other departments (joint teaching).

**The time grid** — the recurring weekly grid only:

- `NO_ACTIVE_WORKING_DAYS` when the semester has no active working day;
- `WORKING_DAY_NO_ACTIVE_SLOTS` for each active working day with no active slot.

**Component demand** — which sessions have to be placed and how big they are:

- `COMPONENT_NO_STUDENT_GROUPS`, `STUDENT_GROUP_INACTIVE`, `STUDENT_COUNT_ZERO`;
- `SESSION_DURATION_NOT_SUPPORTED_BY_GRID` when the session duration fits no
  contiguous block of active slots on any active working day;
- `COMPONENT_WEEKLY_HOURS_EXCEED_GRID` when one component's weekly minutes exceed
  the entire configured weekly grid;
- `INACTIVE_ACADEMIC_DEPENDENCY` when a component's offering, course or managing
  department is inactive, or when a participating group sits in an inactive
  study stage, program or department.

**Instructors** — presence, current eligibility and necessary workload ceilings:

- `PRIMARY_INSTRUCTOR_MISSING` / `MULTIPLE_PRIMARY_INSTRUCTORS` (the validator
  does not trust the database constraint alone and fails safely on inconsistent
  data);
- `INSTRUCTOR_INACTIVE` and `INSTRUCTOR_NOT_ELIGIBLE` — eligibility is
  re-derived through `InstructorProfile.can_teach_in_department`, because sharing
  scope and access grants may have changed since the assignment was created;
- `INSTRUCTOR_AVAILABILITY_MISSING` — absence of availability rows is never read
  as 24/7 availability;
- `INSTRUCTOR_SESSION_DURATION_UNSUPPORTED` when no contiguous block the
  instructor is available for is long enough for the session;
- `INSTRUCTOR_AVAILABLE_TIME_INSUFFICIENT` when assigned weekly minutes exceed the
  weekly minutes the instructor's availability actually covers;
- `INSTRUCTOR_MAX_WEEKLY_HOURS_EXCEEDED`;
- `INSTRUCTOR_MAX_DAILY_HOURS_IMPOSSIBLE` — either a single session is longer than
  the daily limit, or the necessary weekly ceiling `usable_days × max_daily_hours`
  is below the assigned weekly hours.

**Rooms** — requirements, current candidates and available blocks:

- `ROOM_REQUIREMENT_MISSING` / `ROOM_REQUIREMENT_INACTIVE`;
- `ROOM_TYPE_INACTIVE` / `ROOM_CAPABILITY_INACTIVE`;
- `NO_SUITABLE_ROOM` when no active room satisfies the requirement;
- `NO_SUITABLE_ROOM_WITH_AVAILABILITY` when suitable rooms exist but none has both
  a long enough contiguous block for one session and enough usable weekly minutes
  for the component's whole weekly demand.

Room suitability is not re-implemented: `Room.meets_requirement` (the canonical
Phase 5 helper) decides ownership/sharing, room type, effective capacity and the
"all required capabilities" rule, and its verdict is memoised per
`(room, requirement shape)` so a college-wide run does not pay for the same pair
twice.

### Warnings

Only two codes are warnings, and they never block:

- `INSTRUCTOR_MAX_WEEKLY_HOURS_NOT_CONFIGURED`;
- `INSTRUCTOR_MAX_DAILY_HOURS_NOT_CONFIGURED`.

`InstructorPreference` is deliberately **not** consulted: preferences are soft, so
an unsatisfiable preference is never an error and Phase 7 does not optimise for
them.

### Ordering and deduplication

Issues are sorted deterministically by severity (errors first), then `code`,
`entity_type`, `entity_id` and the canonical rendering of `details`, so identical
data always yields an identical response. Exact duplicates are collapsed, and
resource-scoped findings are reported per resource: an instructor assigned to
three components with no availability produces **one**
`INSTRUCTOR_AVAILABILITY_MISSING` for that instructor, while a component-specific
duration problem stays per component.

Contiguous-session arithmetic is pure and exact: hours are converted with
`Decimal` (never binary floating point), and adjacent slots merge into one block
(`08:00-08:45` + `08:45-09:30` supports 90 minutes) while slots separated by a gap
do not (`08:00-08:45` + `09:00-09:45` does not).

### What it deliberately does not check

These are necessary feasibility conditions, **not a solver**:

- no session placement, no schedule generation, no room or time assignment;
- no collision avoidance between components, groups or rooms (two components may
  each pass while still competing for the same slot);
- no optimisation of instructor preferences or daily distribution — the daily
  limit is only used as a necessary ceiling;
- **calendar exceptions are not subtracted from recurring weekly capacity.** A
  holiday does not invalidate the weekly grid, and date-by-date capacity belongs
  to later calendar-aware schedule application and publication, not to this
  validator;
- **no OR-Tools.** Phase 7 installs and imports no solver; `ortools` is
  deliberately absent from `requirements.txt`.

### Architecture

The view validates its input, authorizes the scope, calls the service and
serializes the result — it contains no checking logic:

```
scheduling/services/validation/
├── issues.py     # severities, stable codes, issue shape, dedup + ordering
├── time_grid.py  # duration conversion, contiguous blocks, grid capacity
├── resources.py  # instructor availability/eligibility, room candidates
└── validator.py  # scope population and the per-domain checks
```

The validator loads its inputs with `select_related`/`prefetch_related` (grid,
offerings, groups and their hierarchy, assignments and instructors, room
requirements and capabilities, rooms with capabilities and grants, availability
rows) and then works in memory, memoising the canonical helper calls that would
otherwise repeat per component.

## CP-SAT scheduling engine

The engine turns an **already prepared discrete problem** into a conflict-free
assignment. It is a library, not a service: it imports neither Django nor DRF, and
it is usable without a database, a request or a serializer.

It deliberately does **not** decide which instructor is eligible, which room meets
a requirement, which slots fall inside an availability window, which groups belong
to a course, or whether Phase 7 validation is happy. Deriving feasible placements
needs the academic and resource data, and that adapter belongs to Phase 9.
The engine only chooses between the options it is given.

- **Solver:** OR-Tools `9.15.6755` (pinned in `requirements.txt`), CP-SAT via
  `from ortools.sat.python import cp_model`. Not the legacy CP solver.
- **No cost:** OR-Tools does not require the database, so the engine's unit tests
  run without a Django database fixture.

### Architecture

```
scheduling/services/solver/
├── errors.py         # SolverError, SolverInputError
├── domain.py         # SessionDemand, PlacementCandidate, ResourceReservation,
│                     # SolverProblem, SolverOptions
├── validator.py      # input validation + deterministic indexes
├── model_builder.py  # CP-SAT variables, buckets, objective
├── solver.py         # solve entry point + status mapping
└── result.py         # SolverStatus, ScheduledPlacement, SolverResult
```

`scheduling.services.__init__` resolves the Phase 7 validator symbols lazily, so
`from scheduling.services.solver import solve` does not drag Django into the import
path.

### Input objects

| Object | Meaning |
| --- | --- |
| `SessionDemand` | One required weekly session: `session_id`, `component_id`, `ordinal`, optional declared `candidate_ids` |
| `PlacementCandidate` | One indivisible option: `day_of_week`, ordered `slot_ids`, `room_id`, `instructor_ids`, `student_group_ids`, `penalty`, `metadata` |
| `ResourceReservation` | Occupancy that already exists: `slot_ids` plus `room_ids` / `instructor_ids` / `student_group_ids` |
| `SolverProblem` | `sessions` + `candidates` + `reservations` (+ optional `name`) |
| `SolverOptions` | `max_time_seconds`, `random_seed`, `num_search_workers`, `log_search_progress` |

A component with `weekly_hours = 4` and `session_duration = 2` becomes two
demands, for example `component-15/session-1` and `component-15/session-2`. The
engine receives them; it does not derive them from teaching components.

A candidate is **one decision**. A two-period session carries
`slot_ids = (41, 42)` as a single option, never as two independent decisions, so
the solver can never place half a session.

`slot_ids` are globally unique teaching-period identifiers, so a slot id already
implies its weekday. Conflict buckets are keyed by slot id alone.

### Hard constraints

- **Exactly one placement per session.** `AddExactlyOne` over a session's
  candidates. There is no dropping: a session the engine cannot place makes the
  problem `INFEASIBLE`.
- **Instructor** - no instructor, primary or assistant, occupies a slot twice.
  Every instructor id on a candidate is treated the same way.
- **Student group** - no group occupies a slot twice, covering normal groups,
  subgroups, joint-course groups and several groups on one candidate.
- **Room** - no room hosts two selected candidates in the same slot.
- **Component** - sessions of one component must not overlap, enforced explicitly
  as a defensive invariant even though shared groups or instructors usually imply
  it.
- **Reservations** - a candidate touching a reserved resource/slot pair is forced
  to 0. A reservation that names no resource closes its slots entirely. Both
  directions support multi-slot reservations.

Multi-slot sessions are compared on every slot they occupy: a candidate using
`(10, 11)` conflicts with one using `(11, 12)`, not only with one starting at 10.

Two candidates for the *same* session never conflict with each other, even when
they share an instructor and a slot: at most one of them is ever selected.

### Objective

Each candidate carries a non-negative integer `penalty` and the engine minimises
`sum(selected_penalty)`. The core is deliberately generic: it never interprets
*why* a placement is expensive. Later adapters translate preferred or avoided
times, period order and workload spreading into penalties. When every penalty is
zero the problem is solved as pure feasibility, which is supported rather than
special-cased.

### Result

| Status | Meaning | Placements |
| --- | --- | --- |
| `OPTIMAL` | Best weighted assignment proven | yes |
| `FEASIBLE` | Valid assignment found, optimality unproven (usually a time limit) | yes |
| `INFEASIBLE` | No conflict-free assignment exists | empty |
| `MODEL_INVALID` | The solver rejected the constructed model (engine defect) | empty |
| `UNKNOWN` | No proven answer, typically the time limit | empty |

Statuses are never upgraded or downgraded: `UNKNOWN` is never reported as
`INFEASIBLE`, and a feasible solution is never reported as optimal. The result
also carries `objective_value`, `wall_time_seconds`, `num_conflicts`,
`num_branches` and a `message`.

`SolverResult.placements` are plain `ScheduledPlacement` values - no OR-Tools
object is exposed - ordered by `day_of_week`, first slot id, component id, session
id, candidate id, and `as_dict()` is JSON-serializable in principle even though no
API exists yet.

### Determinism and options

Defaults favour reproducibility over speed: one search worker, a fixed
`random_seed`, `max_time_seconds = 30` and `log_search_progress = False`. The same
problem and options therefore return the same placements in the same order.
Callers may raise the worker count for speed and accept that runs may then differ.

### Input validation

Invalid input fails as a `SolverInputError` before any CP-SAT model exists, never
as an OR-Tools error: unknown session, duplicate session or candidate ids, empty
or repeated slot ids, an empty candidate id, a negative penalty, a repeated
instructor or group id, a session whose declared `candidate_ids` do not match its
candidates, a reservation with no slots, and impossible options.

Two documented behaviours:

- a session with **no candidates** is valid but unsatisfiable, so the solve
  returns `INFEASIBLE` and names that session in the message;
- an **empty problem** solves to `OPTIMAL` with no placements and objective 0,
  instead of crashing.

Exact duplicate candidates for one session are rejected rather than silently
deduplicated, because meaningless alternatives only enlarge the search. Placement
identity is *where* the session happens - day, slots, room, instructors, groups -
so two candidates differing only in `penalty` are the same placement and the pair
is refused; a different room, slot or resource set remains a legitimate
alternative.

### Not in Phase 8

- no `/api/scheduling/generate/` and no other scheduling endpoint - the OpenAPI
  path set is unchanged from Phase 7;
- no `Schedule`, `ScheduleVersion` or `ScheduleEntry` model, and no migration;
- no persistence of solver results;
- no Django problem builder: the engine does not know what a `CourseOffering`,
  `TeachingComponent`, `InstructorProfile` or `Room` is;
- no call to `PreSchedulingValidator` from inside the engine. Phase 9 orchestrates
  `validate`, then `build candidates`, then `call engine`.

Phase 9 will provide the Django problem builder and the department scheduler on
top of this engine.

## Department schedule generation

```
POST /api/scheduling/generate/
```

```json
{ "semester": 3, "department": 2, "max_time_seconds": 30 }
```

Builds the department's weekly scheduling problem from stored data, solves it with
CP-SAT and returns the resulting timetable **preview**. Only the department scope
exists on this endpoint: there is no `scope` field, and the college-wide solver is a
separate endpoint, `POST /api/scheduling/generate-college/`.

`semester` and `department` are required; `max_time_seconds` is optional and
defaults to 30 (accepted range 1–120). The caller cannot control the search seed,
the worker count or the solver log: those are fixed server-side for
reproducibility.

**Nothing is persisted.** No `Schedule`, `ScheduleVersion` or `ScheduleEntry` model
exists, no migration was added, and repeated requests against unchanged data return
the same preview. Every response carries `"persisted": false`.

### Authorization

`COLLEGE_ADMIN` and superusers may generate any department; `DEPARTMENT_ADMIN` and
`SCHEDULER` only their own; `VIEWER` and `INSTRUCTOR` are refused (`403`). A
department-scoped caller without a department fails closed. The department scope is
resolved by the same Phase 7 rule the validation endpoint uses, so the two
endpoints cannot drift apart.

### The validation gate

Generation calls the Phase 7 validator service directly - never the HTTP endpoint -
for the requested semester and department. If the scope is not ready the request
stops with `409` and the Phase 7 result is returned inline:

```json
{
  "generated": false,
  "persisted": false,
  "reason": "PRE_SCHEDULING_VALIDATION_FAILED",
  "validation": { "ready": false, "summary": {}, "issues": [] }
}
```

Warnings do **not** block generation: a ready scope with warnings generates
normally and the warnings come back in the `validation` block.

### Session expansion

Each active teaching component of the requested department becomes as many session
demands as it has weekly sessions (`weekly_hours / session_duration_hours`). A
component with 4 weekly hours in 2-hour sessions becomes `component:15:session:1`
and `component:15:session:2`. Identifiers are stable across repeated generation.

Every candidate for a session carries **all** active assigned instructors (primary
and assistants) and **all** student groups attached to the component, sorted
deterministically. The adapter never decides which instructor teaches a session,
and never expands or infers groups: the joint-course groups of another department
travel with the component exactly as Phase 3 configured them.

### Exact discrete slot blocks

The timetable grid is discrete, so a session must occupy adjacent teaching periods
whose durations sum to **exactly** its length. 90 minutes fit `08:00-08:45` +
`08:45-09:30`, and also `30 + 60` or `30 + 30 + 30`, because period lengths may
differ. Two 60-minute periods are 120 minutes and must **not** serve a 90-minute
session: that would reserve teaching time the session does not use.

This is deliberately stricter than the Phase 7 check, which only asks whether *some*
contiguous block is at least as long as the session. A scope can therefore be
`ready: true` and still be unbuildable here, and that difference is reported
cleanly rather than rounded away:

```json
{
  "generated": false,
  "persisted": false,
  "reason": "CANDIDATE_BUILD_FAILED",
  "generation_issues": [
    {
      "code": "NO_PLACEMENT_CANDIDATES",
      "severity": "ERROR",
      "entity_type": "TeachingComponent",
      "entity_id": 15,
      "details": { "session_id": "component:15:session:1", "required_duration_minutes": 90 }
    }
  ],
  "diagnostics": { "sessions": 2, "sessions_without_candidates": ["component:15:session:1"] }
}
```

### Instructor and room filtering

A candidate block is valid only when **every** assigned active instructor is
available for the whole block, and the room is available for the whole block too. A
period counts only when it lies fully inside an availability window of the matching
weekday. An assistant who cannot cover the block removes the candidate, and missing
availability is never read as unrestricted availability — for instructors or rooms.

Rooms come from the canonical Phase 5 rule, so a room owned by another department is
a candidate whenever sharing allows this department to use it. Shared rooms and
shared instructors are used normally: eligibility is the only gate, and ownership
stops mattering afterwards.

### Preference penalties

The candidate penalty is the sum over assigned instructors of:

| Situation | Penalty |
| --- | --- |
| Interval overlaps an active `AVOID` window (wins over everything) | 20 |
| Interval lies entirely inside an active `PREFERRED` window | 0 |
| Neither | 5 |

Only active preferences for the requested semester count, and preferences are soft:
an `AVOID` window never removes a candidate, it only makes it expensive. Assistant
instructors count exactly like primary instructors. The constants live in one
place, `scheduling/services/generation/preferences.py`.

This is the only soft objective in Phase 9. Gap minimisation, day spreading, theory
before practical, daily balancing and period-order penalties need pairwise or global
terms and belong to a later optimisation phase.

### Result handling

| Solver status | HTTP | `generated` | Placements |
| --- | --- | --- | --- |
| `OPTIMAL` | 200 | true | returned |
| `FEASIBLE` | 200 | true | returned, clearly not labelled optimal |
| `INFEASIBLE` | 200 | false | empty, with `SOLVER_INFEASIBLE` and diagnostics |
| `UNKNOWN` | 200 | false | empty, with `SOLVER_UNKNOWN` (usually the time limit) |
| `MODEL_INVALID` | 200 | false | empty, with `SOLVER_MODEL_INVALID` |

A completed run that found no timetable is a `200`, because the request itself was
valid. `UNKNOWN` is never reported as `INFEASIBLE`, and a feasible solution is never
reported as optimal. Diagnostics report counts only - sessions, candidates, the
sessions with the fewest candidates and those with none - and are explicitly
diagnostics rather than a proven root cause.

### Preview shape

A successful response carries `generated`, `persisted`, the semester and
department, the validation summary, the solver block, `summary` counts and
`placements`. Each placement is flat and shallow: session id, course, offering,
teaching component, weekday plus display label, the occupied periods, derived
`start_time`/`end_time`, room, instructors with their assignment role, all student
groups, and the candidate penalty.

Only resources that take part in this department's generation are described, so a
preview cannot leak another department's catalogue. Diagnostics expose counts, never
foreign identities.

### Not in Phase 9

- no `scope=COLLEGE`: one managing department per request, and a component shared
  with this department belongs to the department that manages it;
- no persistence, versioning, approval or publication;
- no manual editing;
- no choice of instructor per session (Phase 4 decided that);
- no collision solving inside the adapter: the adapter supplies ids and the engine
  enforces instructor, group, room and component conflicts globally;
- no calendar-exception subtraction from the recurring weekly grid, matching the
  Phase 7 limitation;
- no candidate cap: every valid candidate is generated, so a solution is never lost
  to a truncation heuristic.

### Architecture

```
scheduling/services/generation/
├── blocks.py       # exact contiguous slot-block arithmetic (pure)
├── preferences.py  # preference windows and penalty constants (pure)
├── candidates.py   # shared Django adapter + department and college scopes
├── domain.py       # bundle, diagnostics, preview and outcome value objects
├── issues.py       # stable generation issue codes
├── preview.py      # placements to flat preview rows (+ college ordering)
└── service.py      # shared validate -> build -> solve -> preview pipeline
```

The pipeline reads its data once with `select_related`/`prefetch_related` - the
component graph, the grid, instructor availability and preferences, rooms with
their capabilities and grants, and room availability - and then works in memory, so
the `session x block x room` cross product never touches the database. Room
suitability reuses the canonical Phase 5 helper, memoised per requirement shape, and
its capability links are prefetched with `select_related` so the Phase 7 capability
N+1 fix stays fixed.

Phase 8's `scheduling.services.solver` package remains pure and never imports this
adapter.

The department and college scopes are built by one implementation, not two:
`GenerationProblemBuilder` holds every decision (sessions, exact blocks, instructor
and room eligibility, penalties, session and candidate identity) and the two
subclasses only choose which components are demand. Phase 10 therefore cannot
schedule a room, an instructor or a group by a rule that differs from Phase 9's.

## College-wide schedule generation

```
POST /api/scheduling/generate-college/
```

```json
{ "semester": 3, "max_time_seconds": 60 }
```

Builds **one** scheduling problem covering every active teaching component of the
semester in every managing department, solves it once with CP-SAT and returns the
college-wide preview. The scope is the endpoint itself: there is no `scope` field
and no `department` field, so a request cannot turn this endpoint into a
department run or the department endpoint into a college run.

`semester` is required; `max_time_seconds` is optional and defaults to 60 (accepted
range 1–300, wider than the department endpoint because a college-wide problem is
larger). The search seed, the single search worker and the solver log stay fixed
server-side.

This request body is validated strictly: any field the endpoint does not define is
rejected with `400`. `department` and `scope` are therefore refused rather than
silently ignored, so no caller can believe a hidden scope was honoured, and
`random_seed`, `num_search_workers`, `log_search_progress` and `reservations` are
refused rather than half-supported. The rest of the API ignores unknown fields; this
endpoint deliberately does not, because ignoring them here is a scope-confusion risk.

### Authorization

Only `COLLEGE_ADMIN` and Django superusers may call it. `DEPARTMENT_ADMIN`,
`SCHEDULER`, `VIEWER` and `INSTRUCTOR` are refused with `403` whatever their
department is, and anonymous callers get `401`. The gate is the same
cross-department property Phase 7 uses for college-wide validation, so the two
endpoints cannot disagree about who is a college administrator.

College administrator authority schedules *more sessions at once*; it does not widen
any academic rule. The builder still enforces each component's own managing-department
eligibility: an instructor or a room shared with department B is a candidate for
B-managed components only, never for C-managed ones.

### The validation gate

The Phase 7 validator service runs with `scope = COLLEGE` (never through HTTP). When
the scope is not ready the request stops with `409`, OR-Tools is never called, and the
Phase 7 result is returned inline:

```json
{
  "generated": false,
  "persisted": false,
  "scope": "COLLEGE",
  "reason": "PRE_SCHEDULING_VALIDATION_FAILED",
  "validation": { "ready": false, "summary": {}, "issues": [] }
}
```

Warnings never block generation. The second `409` reason is
`CANDIDATE_BUILD_FAILED`, returned when at least one session has no candidate at
all; it carries `NO_PLACEMENT_CANDIDATES` issues naming the session, the component,
the managing department and the required duration in minutes, and it also never
calls the engine.

### Component population

Every active `TeachingComponent` whose offering is active, whose course is active
and whose offering belongs to the requested semester is demand, across all managing
departments. The managing department stays
`component.offering.managing_department`.

A joint course is **one** component with **one** set of weekly sessions. Its
candidates carry every attached student group, including groups of other
departments, so a shared group is constrained globally instead of being copied per
participating department. The same rule applies to offerings that several
departments attend: no per-department duplication, no merged solutions.

### One global problem, not per-department solutions

All sessions of all departments go into a single `SolverProblem`, and the Phase 8
engine enforces the resource conflicts on it. This is the point of the phase:

- **Shared instructors.** An instructor owned by A and shared with B may teach an
  A-managed and a B-managed component in the same semester; the college-wide solve
  can never place those two sessions in overlapping periods.
- **Shared rooms.** A room usable by both A and B is never assigned to two sessions
  at the same time, even though each department would have been individually valid.
- **Joint student groups.** A group that attends an A-managed joint component and a
  B-managed component of its own is never booked into both at once.
- **Component self-conflict** stays with the engine: a component's own weekly
  sessions never overlap each other.

Solving each department separately and merging the answers cannot see any of these
collisions, so it is deliberately not what happens here.

### Identity is shared with Phase 9

Sessions keep the `component:<id>:session:<ordinal>` convention, and candidate ids
are built only from physical placement facts (component, ordinal, weekday, slot ids,
room) — no penalty, no timestamp, no scope. The same physical placement therefore
receives the same candidate id whether it was produced by department or by
college generation.

### Preferences and objective

The soft objective is still the sum of candidate-local instructor preference
penalties, with the Phase 9 constants unchanged (`PREFERRED = 0`, `NEUTRAL = 5`,
`AVOID = 20`). Phase 10 adds no gap minimisation, session spreading, daily balance,
theory/practical ordering, first/last-period avoidance, fairness or room-utilisation
term. Preference windows never affect feasibility.

### Preview and diagnostics

A successful response carries `generated`, `persisted`, `scope`, the semester, the
validation summary, the solver block, `summary` counts
(`departments`, `components`, `sessions`, `candidates`, `placements`),
`department_summaries` and `placements`.

Each placement is flat and shallow — session, course, offering, teaching component,
**managing department**, weekday with display label, occupied periods, derived
`start_time`/`end_time`, room, instructors with their assignment role, all student
groups and the candidate penalty. A joint placement appears once in `placements`,
belonging to the department that manages its component; participating departments
can be derived from its student groups later. The department endpoint's placement
body is unchanged.

`department_summaries` reports `components`, `sessions`, `candidates` and
`placements` per managing department, where `placements` counts components managed
by that department, so a joint placement is never counted for a department that
merely attends it. `diagnostics` adds `departments` and a `department_breakdown` to
the Phase 9 counts (components, sessions, candidates, minimum/maximum candidates per
session, the sessions with the fewest candidates and the sessions without any).
Both lists are ordered by department code, then department id. Diagnostics remain
counts, never a proven root cause.

Ordering is deterministic: placements are sorted by managing department code,
weekday, first period start, course code, component id and session ordinal, and the
engine's own order is deterministic too (fixed seed, one worker). Repeated college
generation against unchanged data returns identical session ids, candidate ids,
penalties, placements, ordering and department summaries.

### Queries

College scope does not query per department. The grid, instructor availability and
preferences, the room pool with capabilities and grants, and room availability are
loaded once per problem; component-level suitability reuses the memoised canonical
Phase 5 helper. Adding a third department therefore adds no resource queries.

### Empty semester

A semester that Phase 7 considers ready but that has no active component at all
produces `generated: true`, `persisted: false`, `solver.status: "OPTIMAL"` with zero
placements and zero counts. Nothing crashes, and the absence of a timetable is
reported as an empty timetable rather than as an error.

### No persistence

No `Schedule`, `ScheduleVersion` or `ScheduleEntry` model exists, no migration was
added, and calling the endpoint changes nothing: no academic, resource or calendar
row is created or modified. `"persisted": false` is always returned. Persistence and
versioning arrive in Phase 11.

### Not in Phase 10

- no persistence, versioning, approval or publication;
- no manual editing or change requests;
- no reservations: `reservations` stays empty, and clients cannot supply them;
- no calendar-exception subtraction from the recurring weekly grid, matching Phases
  7 and 9;
- no new soft constraints beyond instructor preference penalties;
- no reports or Excel/PDF export, no background jobs, no Railway configuration.

## Schedule persistence and versioning

```
POST /api/schedules/generate-department-draft/
POST /api/schedules/generate-college-draft/

GET  /api/schedules/
GET  /api/schedules/{id}/
GET  /api/schedules/{id}/versions/
GET  /api/schedule-versions/{id}/
GET  /api/schedule-versions/{id}/entries/
```

Phase 11 stores generated timetables as version history:

```
Schedule
  ├── ScheduleVersion 1  (DRAFT)
  │     ├── ScheduleEntry
  │     │     ├── ScheduleEntryTimeSlot
  │     │     ├── ScheduleEntryInstructor
  │     │     └── ScheduleEntryStudentGroup
  │     └── ...
  └── ScheduleVersion 2  (DRAFT, parent = version 1)
```

`Schedule` is the logical timetable of one semester and one scope. `ScheduleVersion`
is one immutable generated snapshot. `ScheduleEntry` is one persisted weekly session,
and its three child tables record the exact periods, instructors and student groups
that session had when it was generated.

### Scope

`ScheduleScope` is a model-level choice set, not a serializer enum, and the database
enforces the combination:

- `DEPARTMENT` requires `department`;
- `COLLEGE` requires `department` to be null;
- one department schedule per semester and department, one college schedule per
  semester.

Regenerating therefore appends a version to the same logical schedule instead of
creating a second one. Department schedules and the college schedule of a semester
are separate objects.

### Version numbering, lineage and immutability

`version_number` starts at 1 and is unique per schedule. The next persisted
generation takes the previous latest version plus one, and stores it in
`parent_version`; version 1 has no parent. A parent must belong to the same schedule,
which the model checks as well as the service.

A stored version is never modified: no `PUT`, `PATCH` or `DELETE` exists for
versions, entries or their children, creating an entry through the API is refused,
and a schedule cannot be deleted through the API at all. History grows only by
appending.

Every version created here is `DRAFT`. The remaining lifecycle values
(`SUBMITTED`, `REVIEWED`, `APPROVED`, `PUBLISHED`) exist so the workflow phases can
add transitions without a data migration; no transition, approval or publication
exists yet, and a client cannot choose a status.

### The generate-and-persist endpoints

Both endpoints generate **server-side** with the verified Phase 9 and Phase 10
pipelines and then store that result. An allowed body is small:

```json
{ "semester": 3, "department": 2, "max_time_seconds": 30, "notes": "initial" }
{ "semester": 3, "max_time_seconds": 60, "notes": "college-wide" }
```

Unknown fields are rejected with `400` rather than ignored, so `placements`,
`reservations`, `status`, `version_number` and (college) `department`/`scope` cannot
look like they were applied. There is deliberately no way to POST placements: a
client cannot bypass instructor, room, group, availability, sharing or CP-SAT
constraints, because the server generates the timetable it stores.

Authorization matches the preview endpoints: college administrators draft any
department, department administrators and schedulers their own, and the college-wide
draft is limited to college administrators and superusers.

### Nothing is stored unless the run succeeded

A version is written only when the generation reported success, the solver returned
`OPTIMAL` or `FEASIBLE`, and exactly one placement exists for every required
session. Otherwise:

- a Phase 7 gate failure answers `409` with `PRE_SCHEDULING_VALIDATION_FAILED`;
- a session without a single candidate answers `409` with `CANDIDATE_BUILD_FAILED`;
- an infeasible or timed-out solve answers `200` with `generated: false`;
- a result that looks successful but is structurally short, or whose placements fall
  outside the schedule's scope, answers `409` with `GENERATION_RESULT_INCOMPLETE`.

None of these writes a row: no empty draft, no partial version. The writes for one
version share a single short `transaction.atomic()` block, and the CP-SAT solve
happens before that block opens, so no row lock is ever held for the length of a
solve. Version numbers are allocated under `select_for_update()` on the schedule row,
with the unique constraint as the final guard, which is safe on SQLite today and on
PostgreSQL later.

### Preview endpoints stay preview-only

`POST /api/scheduling/generate/` and `POST /api/scheduling/generate-college/` still
return `"persisted": false` and write nothing. Generating a draft is an explicit,
separate request.

### Snapshots

A version records what the timetable looked like when it was generated. Alongside the
live foreign keys, every entry keeps snapshot columns for the course, offering,
teaching component, managing department and room, and its child rows keep the period
labels, instructor names with their assignment role, and student-group codes, names
and owning department. Renaming a course, room, department, instructor or group later
does not change what a stored version renders, and a joint course keeps the foreign
departments' groups as they were.

### Reading

- College administrators and superusers read every schedule, version and entry.
- A department's `DEPARTMENT_ADMIN`, `SCHEDULER` and `VIEWER` read that department's
  own drafts; another department's draft answers `404`.
- The college-wide draft stays with college administrators until a later workflow
  publishes timetables; department users do not read it.
- `INSTRUCTOR` has no administrative schedule access in this phase.
- A department-scoped user without a department sees nothing, and participating in
  another department's joint course grants no draft access.

List and detail responses carry version counts and the latest version number and
status from annotations, version lists are newest first, and entries are served from
the version's snapshot columns. Optional exact-match entry filters
(`managing_department`, `teaching_component`, `room`, `day_of_week`) narrow the
authorized queryset and can never widen it.

### Not in Phase 11

- no workflow transitions, `SUBMIT`, `REVIEW`, `APPROVE` or `PUBLISH` endpoint;
- no manual editing, entry swapping or change requests;
- no audit log, reports, PDF/Excel export or Flutter work;
- no reservations built from drafts;
- no Railway configuration.

### Architecture

```
scheduling/services/persistence/
├── snapshots.py   # preview placement -> frozen entry snapshots (pure)
└── service.py     # verify, allocate version number, write one version atomically
```

The generation pipeline stays read-only and knows nothing about persistence; the
solver package knows nothing about either. The persistence service is the only writer
of version history.

## Validated manual editing

```
POST /api/schedule-versions/{id}/validate-manual-edit/
POST /api/schedule-versions/{id}/manual-edit/
```

A stored version is immutable, so editing one is copy-on-write: the request names the
placements to move, the server builds the complete proposed timetable in memory,
validates it, and on success writes a **new** `DRAFT` version whose parent is the base
version. The base version and its entries are never modified.

```json
{
  "notes": "Moved two sessions off a room clash",
  "changes": [
    { "entry_id": 101, "time_slot_ids": [21, 22], "room_id": 7 },
    { "entry_id": 105, "room_id": 9 }
  ]
}
```

Each change needs `entry_id` and at least one of `time_slot_ids` or `room_id`. An
omitted `time_slot_ids` keeps the entry's periods; an omitted `room_id` keeps its room.
So a move, a room swap, both at once, or several entries together are all one request.

### Latest draft only

The base version must belong to a schedule the caller can reach, be the **latest**
version of that schedule, and still be `DRAFT`. Editing an older version would branch
one linear chain (`V1 → V2 → V3`), so it is refused with `409 STALE_BASE_VERSION`; a
version that is no longer a draft is refused with `409 BASE_VERSION_NOT_DRAFT`. The
freshness check runs again inside the write transaction while the schedule row is
locked, so two browsers cannot overwrite each other.

### Validate first, write nothing

The validation endpoint takes the same body, runs every check, and writes nothing. It
exists so a user interface can test a drag-and-drop move before offering to save it.
An invalid but well-formed proposal is a normal `200` with `valid: false` and the
issues; a malformed body is `400`; an out-of-reach version is `404`; a stale or
non-draft base is `409`.

### The apply endpoint

A valid request answers `200` with the new version's identity
(`source: MANUAL_EDIT`, `parent_version`, `version_number`, `status: DRAFT`) and counts.
It deliberately does **not** return `generated: true`, because no solver ran.

An invalid proposal answers `409` with `reason: MANUAL_EDIT_VALIDATION_FAILED` and the
issues inline, and creates zero versions and zero entries. Nothing is ever repaired
automatically: if a move collides, the request fails and the user decides the fix.
Several changes are evaluated as one final state, which is what makes an intentional
swap of two sessions possible.

### What is checked

Placement checks, for the placements that move:

- periods exist, are active, belong to an active working day of this semester;
- one weekday per session, no gaps, and periods adjacent in canonical timetable order
  (client order is ignored);
- the stored session duration is preserved exactly — the base entry's own period
  snapshots define the required minutes, so a 45 + 45 session cannot become 60 + 60;
- the entry's existing instructors are still active, still allowed to teach for the
  managing department, and available for the whole requested block;
- the target room is active, shared with the managing department, satisfies the
  component's current room requirement (type, capacity, capabilities) and is available.

Collision checks, over the complete proposed version: no instructor, room, student
group or teaching component may occupy one period twice. Overlaps are detected at
the period granularity the solver itself uses, and each clashing pair is reported once
with the shared period ids, so a two-period clash produces one issue rather than two
identical ones. Issues come back in a documented deterministic order.

`VIEWER` and `INSTRUCTOR` cannot edit at all, and a department administrator or
scheduler can only reach their own department's drafts: a college-wide draft is not in
their queryset, so it answers `404` rather than disclosing that it exists. College
administrators may edit any draft. Joint participation in another department's course
grants no edit authority.

### Copy-on-write semantics

A manual version is a complete timetable, never a delta. Every entry is cloned, and
only a changed placement is rewritten:

- **unchanged entries** keep their stored periods, room, snapshots, penalty and solver
  `candidate_id` exactly as the base version had them;
- **changed entries** keep their identity and history — `session_id`, ordinal,
  component, managing department, course, offering and department snapshots, and their
  instructor and student-group rows, names included — while the weekday, periods, room
  and room snapshots are taken from the request;
- a moved entry gets a documented manual identifier
  (`manual:<base-entry-id>:day:<day>:slots:<ids>:room:<room-id>`) instead of the
  solver's candidate id, because that id named a generated alternative that no longer
  applies;
- the penalty is recomputed with the Phase 9 preference policy for the requested
  interval and the entry's own instructors.

Renaming a live course, room, department, instructor or group therefore still cannot
rewrite what an older version shows.

### No solver, no re-optimisation

Manual editing never invokes CP-SAT and never runs the generation pipelines. It
validates the placement the user asked for and stores exactly that placement when it is
valid; other entries are not moved to compensate. The new version stores `null` for
`solver_status`, `objective_value`, `solver_wall_time_seconds`, `solver_num_conflicts`
and `solver_num_branches`, and records a compact manual summary instead:

```json
{
  "validation_summary": { "manual_edit": true, "base_version": 2, "changed_entries": 2, "validation_errors": 0 },
  "generation_summary": { "manual_edit": true, "source_version_number": 2, "entries": 24, "changed_entries": 2 }
}
```

Entry count and the set of `session_id` values are unchanged by construction: an edit
relocates sessions, it never adds, removes or re-times one, so a component's weekly
hours stay fulfilled. The whole version is written in one transaction, and the solve
free path makes the re-check inside that transaction cheap.

### Not in Phase 12

- no workflow transitions: no submit, review, approve or publish endpoint, and every
  version stays `DRAFT`;
- no change requests, audit log, reports or export;
- no instructor, student-group, component or course reassignment through an edit;
- no automatic conflict repair and no global re-optimisation;
- recurring weekly semantics only: a future holiday or exam date does not block a
  weekly placement, matching the earlier phases;
- no published-version reservations, and no Railway configuration.

## Schedule workflow and official publication

```
POST /api/schedule-versions/{id}/submit/
POST /api/schedule-versions/{id}/review/
POST /api/schedule-versions/{id}/approve/
POST /api/schedule-versions/{id}/publish/
GET  /api/schedule-versions/{id}/workflow-validation/
GET  /api/published-schedules/current/?semester=<id>
```

A stored version moves along one forward-only chain:

```
DRAFT -> SUBMITTED -> REVIEWED -> APPROVED -> PUBLISHED
```

There is no `PATCH status`, no skipping a stage and no backwards move. A transition
writes workflow metadata only: the version's status and that stage's own actor and
timestamp. No entry, period, instructor, room, student group, candidate id, session id
or snapshot is ever touched by a workflow action.

### Who may advance which stage

| Schedule | Submit | Review | Approve | Publish |
| --- | --- | --- | --- | --- |
| Department | college admin, or that department's admin/scheduler | college admin or superuser | college admin or superuser | never |
| College | college admin or superuser | college admin or superuser | college admin or superuser | college admin or superuser |

A department administrator or scheduler may submit their own draft but cannot review
or approve it, because reviewing your own timetable is not a review. Publishing a
department schedule answers `409 DEPARTMENT_SCHEDULE_NOT_PUBLISHABLE`: department
schedules are approved inside the college but never become the authoritative
timetable. `VIEWER` is read-only and `INSTRUCTOR` has no draft-management authority,
so neither can move a stage; a department-scoped account without a department fails
closed. Reachability reuses the draft read scoping, so a version a caller cannot read
answers `404` rather than disclosing that it exists.

### Latest version only

Only the newest version of a schedule may advance. Editing an older one is refused
with `409 STALE_VERSION`, which prevents an obsolete timetable from being approved by
a browser that still holds stale state. Creating a newer draft therefore makes an
older `SUBMITTED` version stale immediately; its historical status and metadata stay
as they were. The check runs again inside the write transaction, under a
`select_for_update()` lock on the schedule row, together with a re-check that the
version is still in the expected current status.

### Every forward step revalidates the whole version

A stored snapshot can decay: an instructor loses a sharing grant, a room is
deactivated or withdrawn, availability changes, a component's weekly hours or session
length change, the teaching assignment is replaced, student groups move, or the time
grid is re-cut. Submitting, reviewing, approving and publishing each run the full
stored-version validation first, and a failure answers `409` with
`SCHEDULE_VALIDATION_FAILED` and the issues inline, changing nothing.

`GET /api/schedule-versions/{id}/workflow-validation/` returns the same report
without writing. Every reported issue is a blocking `ERROR`:

- `INACTIVE_ACADEMIC_DEPENDENCY` — the component, offering, course or managing
department is no longer active;
- `SESSION_COUNT_MISMATCH`, `SESSION_DURATION_MISMATCH` — the component's current
  weekly sessions or session length differ from what the version was built from;
- `TEACHING_ASSIGNMENT_CHANGED`, `STUDENT_GROUP_CONFIGURATION_CHANGED`,
  `STUDENT_GROUP_INACTIVE` — the persisted members no longer match today's
  configuration, or a group left the academic structure;
- `INSTRUCTOR_INACTIVE`, `INSTRUCTOR_NOT_ELIGIBLE`, `INSTRUCTOR_UNAVAILABLE` — the
  stored instructors are gone, no longer allowed to teach for the managing department,
  or no longer available for the stored periods;
- `ROOM_INACTIVE`, `ROOM_NOT_ELIGIBLE`, `ROOM_REQUIREMENT_UNSATISFIED`,
  `ROOM_UNAVAILABLE` — the stored room fails today's activity, sharing, requirement or
  availability rules;
- `TIME_SLOT_INACTIVE`, `TIME_SLOT_WRONG_SEMESTER`, `TIME_SLOT_CONFIGURATION_CHANGED`
  — a saved period is gone, moved to another semester, or was redefined so the stored
  placement no longer matches the calendar;
- `INSTRUCTOR_CONFLICT`, `ROOM_CONFLICT`, `STUDENT_GROUP_CONFLICT`,
  `COMPONENT_CONFLICT` — the version collides with itself.

Issues are ordered by code, entry, conflicting entry and details, and duplicates are
merged, so repeated validation of unchanged data returns the same report.

### Publication

Publishing requires a college schedule with an `APPROVED` latest version and
`COLLEGE_ADMIN` (or superuser) authority. In one transaction the version becomes
`PUBLISHED` with its publish metadata, and the schedule's `published_version` pointer
moves to it. An empty version is refused with `EMPTY_SCHEDULE_CANNOT_BE_PUBLISHED`,
because an accidentally empty official timetable is worse than a refusal.

`Schedule.published_version` is the authoritative pointer. It is never inferred from
`status = PUBLISHED`, because earlier publications keep that status as history:

```
V3 PUBLISHED   (historical)
V4 DRAFT
V5 PUBLISHED   -> schedule.published_version = V5
```

After V5 publishes, V3 is still `PUBLISHED`, its status is not rewritten, and none of
its entries are deleted or modified. Creating or editing a draft never clears the
pointer, so the official timetable stays the last published version until a newer one
reaches `PUBLISHED`. Manual editing still applies to the latest `DRAFT` version only,
so a submitted version can no longer be edited by hand; corrections require a new
draft, which then walks the chain again.

### Reading the official timetable

`GET /api/published-schedules/current/?semester=<id>` returns the current publication
of that semester: the schedule identity, the published version, and the entries the
caller may see.

- college administrator or superuser: every entry;
- a department's administrator, scheduler or viewer: the entries that department
  manages, plus the joint sessions foreign departments manage whose student groups
  belong to it;
- an instructor linked to an instructor profile: the sessions that instructor teaches,
  taken from the persisted instructor rows — the safe foundation for the instructor
  app;
- an instructor without a linked profile: an empty list, never somebody else's
  timetable;
- a department-scoped account without a department: nothing;
- an unknown or missing `semester`: `400`; no published college schedule yet: `404`.

Entries are rendered from the published version's stored snapshots, so the official
timetable keeps the course, room, department, instructor, group and period values that
were approved even after the live records are renamed. Draft management privacy is
unchanged: department users still cannot read a college draft, and the published
endpoint is the only cross-department view.

### Not in Phase 13

- no reports, PDF/Excel export or generic audit log;
- no change requests, notifications, or automatic rejection and rollback;
- no `DELETE` for schedules, versions, entries or publication history;
- no client-supplied workflow actors or timestamps;
- no calendar-exception application, and no Railway configuration.

## Schedule reports and analytics

```
GET /api/schedule-versions/{id}/analytics/
GET /api/published-schedules/current/analytics/?semester=<id>
```

Both endpoints answer the same body, computed by the same service:

```json
{
  "scope": "COLLEGE",
  "version": { },
  "summary": { },
  "department_scope": null,
  "department_load": [ ],
  "instructor_workload": [ ],
  "room_utilization": [ ],
  "student_group_load": [ ],
  "quality": { }
}
```

The `version` block names what was analysed: `id`, `version_number`, `status`, `source`,
`scope` of the schedule it belongs to, its semester, its `created_at` and — for a
publication — `published_at` and `published_by`. Analytics describe a *stored version*,
not the live database, so a report is reproducible long after the data behind it was
renamed or reconfigured.

Analysis is read-only: no model, migration, service or endpoint added by this phase
writes anything. Entries are loaded with their snapshot children prefetched, so a
report costs a fixed number of queries rather than one per entry, and it never mutates
the rows it reads.

### Scope: `COLLEGE` or `DEPARTMENT`

`scope` says how the entry set was narrowed for this caller, not what kind of schedule
the version is. A management report follows its schedule's own scope. A published
report is `COLLEGE` for a college administrator and `DEPARTMENT` for a department user,
whose report carries a `department_scope` block:

| Field | Meaning |
| --- | --- |
| `managed_session_count`, `managed_minutes`, `managed_hours` | the department's own teaching |
| `participating_session_count`, `participating_minutes`, `participating_hours` | joint sessions another department manages that this department's student groups attend |
| `total_visible_session_count` | every session the caller may see |

The two are kept apart and never summed into one local load, because a joint course is
not the department's own teaching. A `COLLEGE` report answers `department_scope: null`.

The entry set is filtered *before* aggregation, so a foreign department's sessions never
contribute to a total, a workload, a room figure or a quality metric.

### Summary

`summary` counts the analysed entry set: `entry_count`, `session_count`,
`scheduled_minutes` (the authoritative integer figure), `scheduled_hours` (derived),
`unique_courses`, `unique_teaching_components`, `unique_departments`,
`unique_instructors`, `unique_rooms`, `unique_student_groups` and `days_used`.
Hours are always derived from stored minutes and never recomputed from clock strings,
so a report cannot drift by rounding twice. In this data model one stored entry is one
placed session, so `entry_count` and `session_count` agree today; both are reported so
that a future change to that relationship cannot silently change the meaning of either.

### Department load

One row per managing department, ordered by department code then id: component count,
session count, scheduled minutes and hours, unique courses, instructors, rooms and
student groups, and `joint_session_count` — the sessions whose persisted groups belong
to more than one department. A joint session counts once, under the department that
manages the component; the participating departments see it in their group and
instructor rows, which is how the work is really distributed.

### Instructor workload

One row per instructor, merged across departments: an instructor teaching for two
departments is one person, not two identities, and their row lists every managing
department they teach for (`department_ids`, `department_codes`, `department_count`).
Each row has session count, the `PRIMARY`/`ASSISTANT` split, scheduled minutes and
hours, active days, `max_daily_scheduled_minutes` (the heaviest single weekday) and the
gap figures below. The split comes from the role the version stored, so today's
teaching assignments cannot rewrite a historical workload.

### Room usage and utilization

One row per room used by the entry set, ordered by room code then id. Usage is
snapshot-stable: session count, occupied minutes and hours, occupied periods and active
days all come from the version.

Utilization is **not** snapshot-stable and is labelled as such. The snapshot does not
contain how much time a room could have been used, so the denominator is today's
configuration: the active teaching periods of the semester that fall completely inside
an active room availability window for that weekday. A period counts once even when
several windows overlap it, so the denominator is capacity rather than a sum of
overlapping grants.

- `utilization_basis` is `CURRENT_ROOM_AVAILABILITY` on every row, so a live
  denominator is never mistaken for history;
- when current configuration cannot supply a basis — the room is gone or inactive, or
  no period fits inside an availability window — `available_minutes`,
  `available_hours` and `utilization_percent` are `null` rather than a guess;
- when the historical timetable occupies more time than today's configuration allows,
  the percentage is reported above `100` and `configuration_mismatch` is `true`.
  Clamping to `100` would hide exactly the evidence an administrator needs.

A room a department may only read (shared) still appears if the version placed sessions
in it: analytics need no write access, and the room's own grants are not consulted.

### Student-group load

One row per persisted student group, ordered by the group's department code, then group
code, then id: session count, scheduled minutes and hours, active days,
`managing_department_count` (how many departments teach this group inside the version)
and the gap figures. Participation and department come from the version's snapshot
rows, not from today's component/group links, so a report keeps describing the
timetable that was actually approved.

### Gaps

A gap is free time *between* teaching, seen from one resource's point of view:

```
08:00-09:30  10:00-11:30   gap 09:30-10:00 = 30 min
08:00-09:30  (nothing else)  no gap
```

Intervals come from the persisted per-entry spans, are merged defensively (touching and
overlapping sessions are one continuous stretch), and are measured between merged
stretches. Time before a resource's first session and after its last is not a gap. Each
instructor and group row carries `total_gap_minutes`, `max_gap_minutes` (the largest
single gap) and `average_gap_minutes_per_active_day`.

### Quality figures

`quality` reports raw, interpretable quantities and deliberately computes **no
composite score**, because a single opaque "82/100" would hide which of them is bad:

| Field | Meaning |
| --- | --- |
| `total_preference_penalty`, `average_preference_penalty_per_session` | sum of the stored `ScheduleEntry.penalty` values, the score the placement was accepted with — never recomputed from today's preference windows |
| `total_instructor_gap_minutes`, `average_instructor_gap_minutes` | dead time instructors carry, averaged per instructor |
| `total_student_group_gap_minutes`, `average_student_group_gap_minutes` | dead time students carry, averaged per group |
| `sessions_by_weekday` | sessions per weekday, with every weekday present so two reports compare position by position |
| `sessions_by_start_hour` | sessions per distinct start time |
| `max_sessions_for_one_instructor_day`, `max_sessions_for_one_group_day` | the heaviest single weekday for one resource |

Averages divide by the population they describe (sessions, instructors, groups) and
report `0.0` rather than an undefined value when that population is empty.

### Snapshot-stable and current-configuration figures

Only one family of figures is not historical, and the contract says so explicitly:

| Category | Source | Fields |
| --- | --- | --- |
| Snapshot-stable | the version's entries and snapshot columns | everything except the denominator: counts, workloads, groups, gaps, penalties |
| Current-configuration | today's rooms, availability and time grid | `available_minutes`, `available_hours`, `utilization_percent`, `configuration_mismatch` |

Renaming a course, room, department, instructor or group changes nothing in a report:
the display values are the ones the version stored. Changing the calendar grid or a
room's availability changes utilization only, and the `utilization_basis` label names
that basis on every row.

### Who may read analytics

`GET /api/schedule-versions/{id}/analytics/` needs the same access the version already
had — the draft read scoping, so a department user cannot analyse a college draft or
another department's draft, and an out-of-scope version answers `404` rather than
disclosing that it exists. An instructor or an abnormally scoped account is refused
with `403`.

`GET /api/published-schedules/current/analytics/?semester=<id>` is a management view
over the officially published timetable, so it follows the published-table endpoint's
scoping but not its audience:

| Caller | Report |
| --- | --- |
| college administrator or superuser | the whole published timetable, `scope: COLLEGE` |
| department administrator, scheduler or viewer | the entries that department manages plus the joint sessions it attends, `scope: DEPARTMENT` |
| instructor | `403` — the published timetable endpoint is the instructor-facing source, and this phase adds no instructor analytics dashboard |
| department-scoped account with no department | `403`: summaries cannot be narrowed, so the request fails closed |
| semester with no publication | `404`, matching the published timetable endpoint |
| missing or unknown `semester` | `400` |

The analysed version is the schedule's `published_version` pointer, never whichever
version carries `status = PUBLISHED`: earlier publications keep that status as history,
and only the pointer says which timetable is official.

### Reused by Phase 15

Report generation is a service first and an endpoint second.
`ScheduleAnalyticsService.for_version(version)` and
`ScheduleAnalyticsService.for_published(schedule, department=...)` return value objects
that render straight to JSON, and the Phase 15 exports consume both the report and its
scoped entry facts instead of re-deriving numbers from the ORM.

### Not in Phase 14

- no PDF, Excel or CSV export, and no download endpoint (both arrive in Phase 15);
- no composite quality score, ranking or recommendation;
- no instructor analytics dashboard;
- no stored report: analytics are computed per request and never persisted;
- no new model, no new field and no migration;
- no writes of any kind, no caching layer and no background job.

## Schedule export (Excel and PDF)

```
GET /api/schedule-versions/{id}/export/xlsx/
GET /api/schedule-versions/{id}/export/pdf/

GET /api/published-schedules/current/export/xlsx/?semester=<id>
GET /api/published-schedules/current/export/pdf/?semester=<id>
```

A download is a *representation* of a report, not a new analysis. Both export routes use
the Phase 14 service directly, in-process:

* the version routes call `ScheduleAnalyticsService.for_version(...)`, exactly as
  `GET /api/schedule-versions/{id}/analytics/` does;
* the published routes call `ScheduleAnalyticsService.for_published(...)`, which reads the
  schedule's authoritative `published_version` pointer and narrows a department's entry
  set *before* aggregation.

The export layer never recomputes a count, workload, gap or quality figure, so a workbook
cannot disagree with the analytics endpoint it came from. The timetable rows come from the
same scoped entry facts, so the file and the report always describe one entry set.

Access is the access the source already had, and the source is chosen before the document
is built:

| Route | Who | Result |
| --- | --- | --- |
| Version export | the roles that may read schedule drafts (`COLLEGE_ADMIN`, `DEPARTMENT_ADMIN`, `SCHEDULER`, `VIEWER`), scoped to versions they may read | out of scope answers `404`, and no draft visibility widens because a file exists |
| Published export | the published analytics roles (the same four; `INSTRUCTOR` is refused with `403`) | college administrator: the whole college; department user: the entries their department manages plus the joint sessions it attends; a department-scoped account without a department fails closed |
| Either published route | a semester with no publication | `404`, never a draft fallback |

Files are built in memory and returned as an attachment with a sanitized filename
(`schedule_semester-3_version-4.xlsx`, `published_schedule_semester-3_department-BIO.pdf`).
Every export is read-only: repeated calls create no schedule, version, entry, workflow or
academic change.

### The Excel workbook

Seven sheets, in this order, every time:

| Sheet | Content |
| --- | --- |
| `Timetable` | one row per persisted placement: managing department, course code and name, offering, component type and label, session, weekday, start, end, occupied periods, room code and name, instructors, student groups, penalty |
| `Analytics Summary` | document metadata (scope, semester, schedule, version, status, source, created, published, department, generated) followed by the headline counts and, for a department report, the managed/participating split |
| `Department Load` | per managing department: components, sessions, minutes, hours, courses, instructors, rooms, groups, joint sessions |
| `Instructor Workload` | per instructor: sessions, primary/assistant split, minutes, hours, active days, busiest day, departments, gap figures |
| `Room Utilization` | per room: sessions, occupied minutes/periods/days, `utilization_basis`, available minutes, utilization percent, configuration mismatch |
| `Student Group Load` | per group: sessions, minutes, hours, active days, managing departments, gap figures |
| `Quality` | preference penalty, gap totals and averages, sessions per weekday and start time, busiest day per instructor and per group |

Periods are joined into one cell rather than expanded into extra rows, so one placement is
one row. Every sheet of a department-scoped workbook reflects only that department's scoped
entry set: nothing is generated for the whole college and then hidden.

Presentation is deliberately simple - bold headers, a frozen header row, an auto-filter,
readable column widths, wrapped long text and two-decimal hour formats - with no formulas
and no macros, so the file opens the same way in Microsoft Excel, LibreOffice and Google
Sheets.

### Snapshot semantics

Descriptive values come from the version's snapshot columns: course code and name, offering
code, component type and label, managing department code and name, room code and name,
instructor names, group codes, names and departments, and period labels and times. Renaming
a live course, room, department, instructor or group after publication does not change a
historical export.

Room utilization is the one figure whose denominator cannot come from the snapshot, so it
is labelled instead of silently mixed: `utilization_basis` is
`CURRENT_ROOM_AVAILABILITY` on every room row, `available_minutes` and
`utilization_percent` are null when today's configuration cannot supply a denominator, and
a schedule that occupies more time than today's grid allows is reported above 100 with
`configuration_mismatch`.

### Formula injection protection

Everything a workbook receives is data. `sanitize_cell` neutralizes any string that begins
with `=`, `+`, `-`, `@`, a tab or a carriage return by prefixing it with an apostrophe, so a
spreadsheet cannot execute a course name, room name, department name, instructor name, group
name, note, code or label. Numbers stay numbers, and no export ever writes a formula of its
own.

### The PDF report

The PDF carries a title, the same document metadata, the same scoped timetable as a
paginated landscape table, and a concise analytics section: sessions, scheduled hours,
departments, instructors, rooms, student groups, preference penalty, gap totals and the
per-weekday distribution. No composite quality score is invented.

The timetable is a single flowable table, so ReportLab splits it across pages and the header
row repeats: a session is never dropped because it crosses a page boundary.

### Unicode and Arabic

ReportLab draws glyphs, it does not shape Arabic, so text that contains right-to-left
characters is reshaped with `arabic-reshaper` and reordered with `python-bidi` before it is
drawn (both are declared dependencies, never transitive). Before anything is drawn, the
resolved font is checked against every character the document will contain.

The font is resolved from `PDF_EXPORT_FONT_REGULAR` / `PDF_EXPORT_FONT_BOLD` when set, then
from the common open-source locations (DejaVu Sans, Liberation Sans, FreeSerif, Noto). When
no usable font exists - or the font cannot draw a character the document contains - the
endpoint answers `503` with the reason instead of producing a document with empty boxes.

> **Deployment note.** A PDF export needs a Unicode-capable TrueType font that covers
> Latin plus Arabic, including the Arabic presentation forms produced by reshaping.
> `DejaVuSans.ttf` and `DejaVuSans-Bold.ttf` satisfy this and are used by default in
> development. A host without them must set `DJANGO_PDF_EXPORT_FONT_REGULAR` and
> `DJANGO_PDF_EXPORT_FONT_BOLD` to an open-source font it ships. No proprietary font is
> bundled, and Railway configuration is not part of Phase 15.

## Semester teaching plan import

```
GET  /api/imports/semester-plan/template/
POST /api/imports/semester-plan/validate/      (multipart: department, semester, file)
POST /api/imports/semester-plan/apply/         (multipart: department, semester, file)
```

The import prepares **one department for one semester**: the academic teaching plan, not a
timetable. It creates courses, student groups, course offerings, teaching components,
component/group links, teaching assignments and room requirements, and it never touches the
scheduling side of the system.

### The one multipart exception

The API is JSON-only everywhere else, and it stays that way: `DEFAULT_PARSER_CLASSES` is
unchanged and only these three endpoints declare `MultiPartParser`. Every other endpoint
still rejects a form body with `415`.

The file is optional for the template route and required, with `department` and `semester`,
for the other two. The scope comes from the request body - never from the workbook - so a
spreadsheet cannot choose to import into another department or another semester.

### Workbook schema

Nine sheets, fixed: `README`, `Courses`, `StudentGroups`, `CourseOfferings`,
`TeachingComponents`, `ComponentGroups`, `TeachingAssignments`, `RoomRequirements`,
`RequirementCapabilities`. The `README` sheet documents the template and is ignored while
parsing data; the other eight must be present, and any other sheet is refused, so a
mistyped tab cannot hide rows.

| Sheet | Required columns | Optional columns |
| --- | --- | --- |
| `Courses` | `course_ref`, `code`, `name` | `description` |
| `StudentGroups` | `group_ref`, `program_code`, `stage_number`, `code`, `name` | `student_count`, `parent_group_ref` |
| `CourseOfferings` | `offering_ref`, `course_ref` | `offering_code` (default `MAIN`) |
| `TeachingComponents` | `component_ref`, `offering_ref`, `component_type`, `weekly_hours`, `session_duration_hours` | `label` |
| `ComponentGroups` | `component_ref`, `group_ref` | - |
| `TeachingAssignments` | `component_ref`, `staff_code` | `assignment_role` (default `PRIMARY`) |
| `RoomRequirements` | `component_ref` | `required_room_type_code`, `minimum_capacity` |
| `RequirementCapabilities` | `component_ref`, `capability_code` | - |

A `*_ref` column is a label that exists only inside the workbook (`C01`, `G01`, `O01`,
`TC01`): database ids never appear in a template, and the workbook's own rows are connected
by those refs. Columns such as `program_code`, `stage_number`, `staff_code`,
`required_room_type_code` and `capability_code` reference **existing** records by their
stable code, because those records have owners and sharing rules of their own.

Surrounding whitespace is trimmed from every cell; that is the whole of the normalization.
Enum values are matched case-insensitively and stored canonically (`THEORY`, `PRACTICAL`,
`PRIMARY`, `ASSISTANT`).

### What the import may change

It creates only:

```
Course, StudentGroup, CourseOffering, TeachingComponent,
TeachingComponentGroup, TeachingAssignment,
TeachingComponentRoomRequirement, TeachingComponentCapabilityRequirement
```

It references, and never creates or edits: `StudyProgram`, `StudyStage`,
`InstructorProfile`, `RoomType`, `RoomCapability`, `Semester`, `Department`.

It never touches: schedules, versions, entries, workflow status, the publication pointer,
sharing grants, instructor or room availability, the calendar and time grid, rooms
themselves, instructor profiles themselves, or any account, password or role. Instructors
are referenced by `staff_code` and rooms only by `room_type_code`/`capability_code`, which is
what keeps the Phase 4 and Phase 5 ownership rules intact: a department spreadsheet cannot
create a foreign instructor, grant itself sharing, or pick a specific room.

### Validate, then apply

`validate/` performs the complete reading and validation and creates **zero** rows, so it can
be called as often as needed. It answers `200` with `valid`, a summary and the issue list:

```json
{
  "valid": false,
  "summary": { "sheets": 8, "rows": 54, "errors": 3, "warnings": 1 },
  "issues": [
    {
      "sheet": "TeachingAssignments",
      "row": 7,
      "column": "staff_code",
      "code": "INSTRUCTOR_NOT_FOUND",
      "severity": "ERROR",
      "message": "No instructor profile with staff code 'I-900' exists. ...",
      "details": {}
    }
  ]
}
```

`apply/` re-reads and fully re-validates the same upload against **current** database state
immediately before writing: there is no validated-token flow, and a response from an earlier
request is never trusted. With one blocking issue nothing is written and the answer is `400`
with the blocking issues. Otherwise every record is created inside a single
`transaction.atomic()`, so a failure half way through rolls the whole import back, and the
answer is `200` with counts:

```json
{
  "applied": true,
  "department": { "id": 2, "code": "BIO", "name": "Biology" },
  "semester": { "id": 3, "number": 1, "academic_year": "2026-2027" },
  "created": {
    "courses": 5, "student_groups": 2, "offerings": 5, "components": 8,
    "component_group_links": 8, "teaching_assignments": 8,
    "room_requirements": 8, "requirement_capabilities": 6
  },
  "warnings": []
}
```

### Create-only, never overwrite

Phase 15 import policy is `CREATE_ONLY`. An object that already exists is a refusal, not an
update: `COURSE_ALREADY_EXISTS`, `GROUP_ALREADY_EXISTS` and `OFFERING_ALREADY_EXISTS` name
the conflict and nothing is written. Rows that are meant to be *references* - programs,
stages, instructors, room types, capabilities, the semester and the department - are looked
up and never created. That makes a spreadsheet safe to re-run: the second attempt fails
visibly instead of silently rewriting academic data.

### Validation rules

Every row is turned into an unsaved model instance and validated with the same `clean()`
rules the HTTP API uses, so a component whose weekly hours do not divide into whole sessions
is refused here for the same reason it is refused on `POST /api/teaching-components/`.
Instructor eligibility reuses `InstructorProfile.can_teach_in_department`, which is why a
workbook cannot assign an instructor the department could not assign through the API.

Cross-sheet validation covers unresolved references (`COURSE_REF_NOT_FOUND`,
`OFFERING_REF_NOT_FOUND`, `COMPONENT_REF_NOT_FOUND`, `GROUP_REF_NOT_FOUND`), duplicate
workbook refs (`DUPLICATE_REF`), duplicate relation rows (`DUPLICATE_RELATION`), parent
hierarchy problems (`PARENT_GROUP_SELF`, `PARENT_GROUP_NOT_IN_WORKBOOK`,
`PARENT_GROUP_DIFFERENT_STAGE`, `PARENT_GROUP_CYCLE`), the Phase 3 overlap rule
(`GROUP_HIERARCHY_OVERLAP`), one active primary per component
(`MULTIPLE_PRIMARY_INSTRUCTORS`), capability rows without a room requirement
(`ROOM_REQUIREMENT_MISSING`) and room types or capabilities that do not exist or are
inactive.

Two informational warnings do not block an apply, because a plan may legitimately be
completed later: `NO_PRIMARY_INSTRUCTOR` and `COMPONENT_WITHOUT_GROUP`. Neither replaces the
Phase 7 readiness report, and the import does not require a workbook to be schedule-ready.

Cross-department rows are the one capability that needs college-level authority: creating a
group under another department's program, or linking another department's students into a
course, is refused for a department administrator
(`PROGRAM_OUTSIDE_DEPARTMENT`, `CROSS_DEPARTMENT_LINK_REQUIRES_COLLEGE_ADMIN`) and allowed
for a college administrator, mirroring the Phase 3 rule that joint teaching across
departments is a college-level act.

Issues are ordered by sheet (in the documented sheet order), then row, then column, then
code, and exact duplicates are merged, so validating an unchanged workbook twice returns the
same list in the same order.

### Safety limits and file guards

| Guard | Value | Behavior |
| --- | --- | --- |
| File type | `.xlsx` only | `.xls`, `.xlsm`, `.csv`, archives and non-spreadsheet content are refused (`UNSUPPORTED_FILE_TYPE`, `NOT_A_WORKBOOK`) |
| Macros | none | a workbook containing `xl/vbaProject.bin` is refused (`MACRO_ENABLED_WORKBOOK`) |
| Upload size | 5 MB | refused before the file is buffered (`FILE_TOO_LARGE`) |
| Rows per sheet | 2000 data rows | `SHEET_ROW_LIMIT_EXCEEDED` |
| Rows per workbook | 10000 data rows | `TOTAL_ROW_LIMIT_EXCEEDED` |
| Scanned rows per sheet | 20000 spreadsheet rows | `SCANNED_ROW_LIMIT_EXCEEDED`, so a sheet formatted far past its data is refused rather than walked |
| Cells | data only | a formula is an error (`FORMULA_NOT_ALLOWED`); nothing is ever evaluated |
| Empty rows | ignored | blank rows, including formatted-but-empty trailing rows, are skipped |

All five limits are settings (see the configuration table), so a deployment can tighten them.
Nothing is read before the scope is authorized: role, department and semester are checked
before a single cell is examined. Malformed workbooks answer with issues, never with a `500`.

The download template is generated from the same schema constants the reader enforces, so it
cannot drift, and it is byte-identical between downloads (fixed document and archive
timestamps). The data sheets carry headers only, with the examples in the `README` sheet, so
validating the untouched template reports `8` sheets, `0` rows, `0` errors and applying it
writes nothing.

## Who may write what

| Role | Reads | Writes |
| --- | --- | --- |
| `COLLEGE_ADMIN` or Django superuser | everything | everything: colleges, academic years, semesters, joint-course group associations, instructor profiles, sharing grants, availability, preferences, assignments, room types, room capabilities, rooms, room grants, room capabilities and availability, teaching-component room requirements, working days, time slots, breaks and calendar exceptions; may run validation for the whole college or any department, and may generate a preview for any department |
| `DEPARTMENT_ADMIN` | own department plus joint components their students attend, instructors shared with them, rooms they may use, and calendar exceptions in their scope | own department: update it; manage programs, stages, groups, courses, offerings, components, component/group links (own groups only), instructor profiles, sharing grants, availability, preferences, assignments on components their department manages, own rooms with their grants, capabilities and availability, room requirements for components their department manages, and calendar exceptions for own-department resources; may run validation for **its own department only**, and may generate a preview for **its own department only** |
| `SCHEDULER` | own department plus joint components their students attend, instructors shared with them, rooms they may use, and the calendar grid and exceptions in their scope | none — every Phase 2–6 resource is read-only for this role, but it may run validation for **its own department only** and generate a preview for **its own department only** |
| `VIEWER`, `INSTRUCTOR` | own department plus joint components their students attend, instructors shared with them, rooms they may use, and the calendar grid and exceptions in their scope | none — every Phase 2–6 resource is read-only for these roles, and they may **not** run validation |

A department can never modify a shared instructor or room, inspect availability
that is not shared with it, grant itself access to a foreign instructor or room,
or assign an ineligible instructor or an unsuitable room requirement — sharing
changes are always made by the owning department (or a college administrator).

Every endpoint requires authentication. Department-scoped reads return only what
the caller's department owns **or participates in**: out-of-scope detail requests
answer `404` rather than revealing that a record exists, and a department-scoped
user with no department sees an empty result set. Writes are authorised from
`request.user` and the persisted relationships, so a client cannot move a
course, offering, component or instructor into another department — or attach a
foreign student group or ineligible instructor — by sending different
foreign-key ids. Such payloads answer `400`; existing records that are out of
scope answer `403` or `404`.

No endpoint exposes `DELETE`: detail routes answer `405` and lifecycle is managed
with `is_active` (`TeachingComponentGroup` is a relation rather than a lifecycle
record; it is currently maintained through the Django admin).

Permission classes live in `academics/permissions.py`
(`IsCollegeAdminOrReadOnly`, `CanManageDepartments`, `IsDepartmentScopedWriter`
and, for teaching and instructor resources, `IsDepartmentScopedManager` with the
`visible_*_filter` helpers). Instructor read visibility lives in
`resources/permissions.py`.

Phase 15 adds two narrower rules on top: the semester teaching plan import is limited to
`COLLEGE_ADMIN` and `DEPARTMENT_ADMIN` (`CanImportSemesterPlan`), because it writes academic
structure - `SCHEDULER` is refused here even though it may submit and edit drafts, and
`VIEWER`/`INSTRUCTOR` are refused as everywhere else. Exports add no authority of their own:
they reuse the read scoping of the version (Phase 11-14) or of the published timetable, so a
file can never show more than the API already would.

## Timezone

Django runs timezone-aware (`USE_TZ = True`) with `TIME_ZONE = "Asia/Baghdad"`.
Timestamps are stored normally and rendered in Baghdad local time; application
code never appends manual UTC offsets.

## Configuration

Settings are read from environment variables (optionally via `.env`):

| Variable                      | Default                                          |
| ----------------------------- | ------------------------------------------------ |
| `DJANGO_SECRET_KEY`           | dev-only fallback (required when `DEBUG=False`)   |
| `DJANGO_DEBUG`                | `True`                                           |
| `DJANGO_ALLOWED_HOSTS`        | `localhost,127.0.0.1`                            |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000`    |
| `DJANGO_PDF_EXPORT_FONT_REGULAR` | empty: search the default open-source font locations |
| `DJANGO_PDF_EXPORT_FONT_BOLD` | empty: search the default open-source font locations |
| `DJANGO_SEMESTER_PLAN_IMPORT_MAX_BYTES` | `5242880` (5 MB)                        |
| `DJANGO_SEMESTER_PLAN_IMPORT_MAX_SHEET_ROWS` | `2000`                            |
| `DJANGO_SEMESTER_PLAN_IMPORT_MAX_TOTAL_ROWS` | `10000`                           |
| `DJANGO_SEMESTER_PLAN_IMPORT_MAX_SCANNED_ROWS` | `20000`                         |

Other fixed settings: `AUTH_USER_MODEL = "accounts.User"`,
`TIME_ZONE = "Asia/Baghdad"`, `USE_I18N = True`, `USE_TZ = True`, SQLite via
`db.sqlite3`. DRF uses SimpleJWT as its authentication class,
`IsAuthenticated` as the default permission and `JSONParser` as its only
parser; only the endpoints listed above opt out with `AllowAny`. CORS is
restricted to the configured origins — `CORS_ALLOW_ALL_ORIGINS` is deliberately
not used.

## Roadmap

- **Phase 1 (done)** — roles, reusable role/department permissions, JWT login
  and refresh, and `/api/me/`.
- **Phase 2 (done)** — academic structure: colleges, academic years, semesters,
  departments, study programs, stages and student groups.
- **Phase 3 (done)** — courses, offerings, teaching components and the group
  links that model practical subgroups and joint inter-department courses.
- **Phase 4 (done)** — instructors: `InstructorProfile`, sharing scopes and
  `InstructorDepartmentAccess`, weekly availability, soft preferences, workload
  limits, `TeachingAssignment` (`PRIMARY`/`ASSISTANT`) and
  `/api/me/teaching-assignments/`.
- **Phase 5 (done)** — rooms and laboratories, room capabilities, sharing and
  availability, and the room/capability requirements teaching components declare.
- **Phase 6 (done)** — calendar and time configuration: working days, teaching
  periods, breaks and dated calendar exceptions.
- **Phase 7 (done)** — pre-scheduling validation: a computed readiness report
  over the academic, resource and calendar data, with stable issue codes.
- **Phase 8 (done)** — the generic CP-SAT scheduling engine: session demands,
  placement candidates, hard resource conflicts, optional reservations and a
  weighted candidate objective, with no API and no persistence.
- **Phase 9 (done)** — the department scheduler: the Django problem builder,
  session expansion, exact slot blocks, preference penalties and the preview
  endpoint. Preview only, nothing persisted.
- **Phase 10 (done)** — college-wide generation: one CP-SAT problem covering every
  department of the semester, with shared instructors, shared rooms and joint
  student groups constrained globally. College administrators only, preview only.
- **Phase 11 (done)** — schedule persistence and versioning: `Schedule`,
  `ScheduleVersion`, `ScheduleEntry` and the snapshot child tables, an explicit
  generate-and-persist endpoint per scope, and read-only history APIs. Drafts only,
  nothing published.
- **Phase 12 (done)** — validated manual editing of a draft: a validation endpoint and
  a copy-on-write apply endpoint that append a `MANUAL_EDIT` version. No workflow yet.
- **Phase 13 (done)** — workflow and official publication: submit, review, approve and
  publish with full revalidation, and the authoritative published timetable readable
  by departments and instructors.
- **Phase 14 (done)** — schedule reports and analytics: read-only management and published
  analytics over persisted versions, with snapshot-stable counts, workloads, gaps and
  quality figures, and utilization labelled as current-configuration.
- **Phase 15 (done)** — Excel/PDF export and controlled Excel import: read-only timetable
  and report downloads over persisted versions and the published timetable, a generated
  import template, and a validate-then-apply semester teaching plan import.
- **Phase 16 (planned)** — the next phase; its scope is not fixed in this repository yet.
- **Later** — reservations and department regeneration from an authoritative version,
  PostgreSQL, background jobs, Railway deployment.
- **Flutter instructor app** — after the web application, using
  `/api/me/teaching-assignments/` as one of its first endpoints.
