# College Academic Schedule Planner — Backend

Django REST Framework backend for the College Academic Schedule Planner.
Provides the project foundation (configuration package, domain app skeletons,
custom user model, API/OpenAPI plumbing) that later phases build on.

- Current phase: **Phase 6 — calendar and time configuration** (working days,
  teaching periods, breaks and calendar exceptions). No timetable generation,
  schedule entries or actual room/time assignment yet; pre-scheduling validation
  is Phase 7.

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
├── scheduling/        # calendar and time configuration
│   ├── models.py      # WorkingDay, TimeSlot, BreakPeriod, CalendarException,
│   │                  # ExceptionType, ExceptionScope
│   ├── permissions.py # calendar-exception read visibility and write rules
│   ├── serializers.py # read/write serializers + nested summaries
│   ├── views.py       # viewsets for the time grid and exceptions
│   ├── urls.py        # /api/working-days/, /api/time-slots/, ...
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
absences) that remove availability. Timetable generation (OR-Tools), schedule
entries, actual room and time assignment, pre-scheduling validation and reports
come later. The Flutter instructor app follows the web application.

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

## Who may write what

| Role | Reads | Writes |
| --- | --- | --- |
| `COLLEGE_ADMIN` or Django superuser | everything | everything: colleges, academic years, semesters, joint-course group associations, instructor profiles, sharing grants, availability, preferences, assignments, room types, room capabilities, rooms, room grants, room capabilities and availability, teaching-component room requirements, working days, time slots, breaks and calendar exceptions |
| `DEPARTMENT_ADMIN` | own department plus joint components their students attend, instructors shared with them, rooms they may use, and calendar exceptions in their scope | own department: update it; manage programs, stages, groups, courses, offerings, components, component/group links (own groups only), instructor profiles, sharing grants, availability, preferences, assignments on components their department manages, own rooms with their grants, capabilities and availability, room requirements for components their department manages, and calendar exceptions for own-department resources |
| `SCHEDULER`, `VIEWER`, `INSTRUCTOR` | own department plus joint components their students attend, instructors shared with them, rooms they may use, and the calendar grid and exceptions in their scope | none — every Phase 2–6 resource is read-only for these roles |

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
- **Phase 7 (planned)** — pre-scheduling validation.
- **Later** — timetable generation (OR-Tools), schedule entries, actual room and
  time assignment, reports/export, PostgreSQL, background jobs, Railway
  deployment.
- **Flutter instructor app** — after the web application, using
  `/api/me/teaching-assignments/` as one of its first endpoints.
