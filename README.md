# College Academic Schedule Planner — Backend

Django REST Framework backend for the College Academic Schedule Planner.
Provides the project foundation (configuration package, domain app skeletons,
custom user model, API/OpenAPI plumbing) that later phases build on.

- Current phase: **Phase 9 — department schedule generation** (a preview timetable
  for one department, built from stored data and solved with CP-SAT). Nothing is
  persisted: no `Schedule` models exist, and college-wide generation is Phase 10.

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
├── scheduling/        # calendar, time configuration, validation and solver
│   ├── models.py      # WorkingDay, TimeSlot, BreakPeriod, CalendarException,
│   │                  # ExceptionType, ExceptionScope
│   ├── services/      # domain logic kept out of the views
│   │   ├── validation/# issues, time_grid, resources, validator
│   │   ├── solver/    # domain, validator, model_builder, solver, result
│   │   └── generation/# blocks, candidates, preferences, preview, service
│   ├── permissions.py # calendar visibility and validation scope rules
│   ├── serializers.py # resource, validation and generation contracts
│   ├── views.py       # time-grid viewsets + validation and generation endpoints
│   ├── urls.py        # /api/working-days/, /api/scheduling/generate/, ...
│   └── migrations/    # 0001_calendar_and_time_configuration
├── reports/           # report exports (empty until later phases)
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
- **Phase 11 (planned)** — `Schedule`/`ScheduleVersion`/`ScheduleEntry` persistence
  and versioning.
- **Later** — approval and publication, manual editing, reports/export,
  reservations and department regeneration from an authoritative version,
  PostgreSQL, background jobs, Railway deployment.
- **Flutter instructor app** — after the web application, using
  `/api/me/teaching-assignments/` as one of its first endpoints.
