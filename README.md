# College Academic Schedule Planner — Backend

Django REST Framework backend for the College Academic Schedule Planner.
Provides the project foundation (configuration package, domain app skeletons,
custom user model, API/OpenAPI plumbing) that later phases build on.

- Current phase: **Phase 3 — courses and teaching structure** (no instructors,
  rooms or scheduling yet).

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
│   │                  # TeachingComponentGroup
│   ├── permissions.py # role, department and joint-teaching visibility rules
│   ├── serializers.py # read/write serializers + nested summaries
│   ├── views.py       # DRF viewsets (no hard delete)
│   ├── urls.py        # /api/colleges/, /api/departments/, /api/courses/, ...
│   └── migrations/    # 0001_initial, 0002_academic_structure,
│                      # 0003_teaching_structure
├── resources/         # rooms, time resources (empty until later phases)
├── scheduling/        # schedules and solving (empty until later phases)
├── reports/           # report exports (empty until later phases)
├── tests/             # pytest suite for the whole project
├── manage.py
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

Phase 3 adds the teaching structure (courses, offerings, teaching components
and the groups attending them). Instructors, instructor availability, rooms,
laboratories and scheduling are still unimplemented:
instructor assignment arrives in **Phase 4**, room/lab assignment in
**Phase 5**, timetable generation later.

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
| GET    | `/api/schema/`       | public        | OpenAPI 3 schema                   |
| GET    | `and Phase 3 resources expose the same five operations — `GET` list,
`GET` detail, `POST`, `PUT`, `PATCH`:

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
| Study stages      | `/api/stages/`          | `stage.program.department`            |
| Student groups    | `/api/student-groups/`  | `group.stage.program.department`      |

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

## Who may write what

| Role | Reads | Writes |
| --- | --- | --- |
| `COLLEGE_ADMIN` or Django superuser | everything | everything, including colleges, academic years, semesters and joint-course group associations |
| `DEPARTMENT_ADMIN` | own department plus joint components their students attend | own department: update it, and manage programs, stages, groups, courses, offerings, components and component/group links (only groups of their own department) |
| `SCHEDULER`, `VIEWER`, `INSTRUCTOR` | own department plus joint components their students attend | none — academic and teaching structure is read-only for these roles |

Every endpoint requires authentication. Department-scoped reads return only what
the caller's department owns **or participates in**: out-of-scope detail requests
answer `404` rather than revealing that a record exists, and a department-scoped
user with no department sees an empty result set. Writes are authorised from
`request.user` and the persisted relationships, so a client cannot move a
course, offering or component into another department — or attach a foreign
student group — by sending different foreign-key ids.

No endpoint exposes `DELETE`: detail routes answer `405` and lifecycle is managed
with `is_active` (`TeachingComponentGroup` is a relation rather than a lifecycle
record; it is currently maintained through the Django admin).

Permission classes live in `academics/permissions.py`:
`IsCollegeAdminOrReadOnly`, `CanManageDepartments`, `IsDepartmentScopedWriter`
and, for the Phase 3 teaching resources, `IsDepartmentScopedManager` together
with the `visible_*_filter` helpers.

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
  and refresh, `/api/me/`, minimal `Department`.
- **Phase 2 (done)** — `College`, expanded `Department`, `AcademicYear`,
  `Semester`, `StudyProgram`, `StudyStage`, `StudentGroup` with optional
  subgroups, plus the scoped REST API, permissions and admin.
- **Phase 3 (done)** — `Course`, `CourseOffering`, `TeachingComponent` and
  `TeachingComponentGroup`: theory/practical weekly hours, derived session
  counts, combined groups, practical subgroups and joint inter-department
  courses.
- **Phase 4 (planned)** — instructors: `InstructorProfile`,
  `InstructorDepartmentAccess`, availability and preferences, and instructor
  assignment to teaching components.
- **Phase 5 (planned)** — rooms and laboratories, room requirements and
  assignment.
- **Later** — timetable generation (OR-Tools), reports/export, PostgreSQL,
  background jobs, deployment.
