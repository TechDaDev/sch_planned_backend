# College Academic Schedule Planner — Backend

Django REST Framework backend for the College Academic Schedule Planner.
Provides the project foundation (configuration package, domain app skeletons,
custom user model, API/OpenAPI plumbing) that later phases build on.

- Current phase: **Phase 0 — backend foundation** (no academic scheduling yet).

## Architecture

```
sch_planner_backend/
├── config/            # Django project/configuration package
│   ├── settings.py    # environment-driven settings
│   ├── urls.py        # root URLconf: /admin/ and /api/
│   ├── api_urls.py    # /api/ namespace (health, schema, docs)
│   ├── views.py       # project-level API views (health probe)
│   ├── asgi.py
│   └── wsgi.py
├── accounts/          # custom user model (+ auth in later phases)
├── academics/         # departments, courses (empty in Phase 0)
├── resources/         # rooms, time resources (empty in Phase 0)
├── scheduling/        # schedules and solving (empty in Phase 0)
├── reports/           # report exports (empty in Phase 0)
├── tests/             # pytest suite for the whole project
├── manage.py
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

Domain apps are intentionally empty in Phase 0; they exist so later phases can
add models and URLs without restructuring the project.

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

## API endpoints (Phase 0)

| Method | Path           | Auth   | Purpose                          |
| ------ | -------------- | ------ | -------------------------------- |
| GET    | `/admin/`      | staff  | Django admin                     |
| GET    | `/api/health/` | public | Liveness probe                   |
| GET    | `/api/schema/` | public | OpenAPI 3 schema                 |
| GET    | `/api/docs/`   | public | Swagger UI for the schema        |

Health response:

```json
{ "status": "ok", "service": "sch_planner_backend" }
```

Swagger UI: <http://127.0.0.1:8000/api/docs/>

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
`db.sqlite3`. DRF uses SimpleJWT as its authentication class and
`IsAuthenticated` as the default permission (public endpoints opt out
explicitly, as `/api/health/` does). CORS is restricted to the configured
origins — `CORS_ALLOW_ALL_ORIGINS` is deliberately not used.

## Roadmap

- **Phase 1** — roles/permissions, JWT login and refresh endpoints,
  departments, instructors, courses, rooms.
- **Phase 2** — schedule generation (OR-Tools) and schedule APIs.
- **Phase 3** — reporting/export, PostgreSQL, background jobs.
