# Backend release checklist

Backend release candidate `1.0.0`. Run every command from the repository root with the
virtual environment active. Nothing here claims a deployment has happened.

## 1. Gate commands

```bash
# System and schema
python manage.py check
python manage.py makemigrations --check      # must print "No changes detected"
python manage.py migrate                     # expected: no migrations to apply
python manage.py verify_operational_integrity

# Contract
python manage.py spectacular --file /tmp/sch_planner_phase17_schema.yaml --validate

# Dependencies and compilation
python -m pip check
python -m compileall -q accounts academics resources scheduling config

# Tests
pytest -q
pytest -q tests/test_phase8_solver_engine.py tests/test_phase8_solver_acceptance.py
```

Expected at the last verified state: full suite green (325 tracked tests including the
Phase 17 hardening file), solver pair `54 passed`, integrity `ok` and exit `0`,
`makemigrations --check` clean.

## 2. Production configuration check

```bash
DJANGO_DEBUG=false \
DJANGO_SECRET_KEY='<test-only value, 50+ chars, not committed>' \
DJANGO_ALLOWED_HOSTS=example.test \
DJANGO_CORS_ALLOWED_ORIGINS=https://frontend.example.test \
DJANGO_CSRF_TRUSTED_ORIGINS=https://frontend.example.test \
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=true \
python manage.py check --deploy
```

Result at the last verified state: **one** warning remains.

`security.W021` (HSTS preload not enabled) is intentional. Preload is a browser-level,
effectively irreversible commitment for a whole registrable domain, and this repository
does not know which hostnames a deployment will serve. Enable
`DJANGO_SECURE_HSTS_PRELOAD=true` only deliberately, after the domain and all subdomains
are decided.

`security.W009` must not appear: it means the secret is a placeholder or too short. Always
run this check with a realistic test-only secret.

## 3. Environment variables

| Variable | Development default | Production |
| --- | --- | --- |
| `DJANGO_DEBUG` | `true` | `false` |
| `DJANGO_SECRET_KEY` | dev-only fallback | **required**, no fallback |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | **required**, no default |
| `DJANGO_CORS_ALLOWED_ORIGINS` | local frontend origins | empty until configured |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | empty until configured |
| `DJANGO_API_DOCS_ENABLED` | `true` | `false` |
| `DJANGO_SECURE_SSL_REDIRECT` | `false` | `true` |
| `DJANGO_SESSION_COOKIE_SECURE` / `DJANGO_CSRF_COOKIE_SECURE` | `false` | `true` |
| `DJANGO_SESSION_COOKIE_SAMESITE` / `DJANGO_CSRF_COOKIE_SAMESITE` | `Lax` | `Lax` |
| `DJANGO_X_FRAME_OPTIONS` | `DENY` | `DENY` |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` | `3600` |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | `false` | deliberate choice |
| `DJANGO_SECURE_HSTS_PRELOAD` | `false` | deliberate choice |
| `DJANGO_TRUST_X_FORWARDED_PROTO` | not set | `true` only behind a proxy that sets it |
| `DJANGO_LOCAL_BACKUP_DIR` | `<project>/var/backups` | operator choice |
| `DJANGO_SEMESTER_PLAN_IMPORT_MAX_*` | Phase 15 defaults | tighten as needed |
| `DJANGO_PDF_EXPORT_FONT_REGULAR` / `_BOLD` | searched automatically | set when the host lacks DejaVu |

Development defaults keep the local workflow unchanged: debug on, localhost allowed, local
frontend origins allowed, docs and the browsable API available, SQLite as the database.

## 4. Health endpoints

| Endpoint | Auth | Behavior |
| --- | --- | --- |
| `GET /api/health/` | public | Phase 0 compatibility probe |
| `GET /api/health/live/` | public | liveness, no database query |
| `GET /api/health/ready/` | public | `200 {"status":"ok"}` or `503 {"status":"unavailable"}` |

Point orchestration liveness at `/live/` and readiness at `/ready/`. Readiness answers
`503` when it cannot run `SELECT 1`, and never names the database, its vendor or the error.

## 5. Deployment prerequisites

- **HTTPS**: terminate TLS upstream and set `DJANGO_TRUST_X_FORWARDED_PROTO=true` when the
  proxy sets `X-Forwarded-Proto`; `SECURE_SSL_REDIRECT` then applies.
- **CORS/CSRF**: list the exact frontend origins. Never enable `CORS_ALLOW_ALL_ORIGINS`.
- **Static files**: `STATIC_ROOT` is `<project>/staticfiles`; run `collectstatic` during
  deployment. No CDN or WhiteNoise configuration exists yet.
- **PDF export font**: a Unicode-capable TrueType font covering Latin and Arabic must exist
  on the host, otherwise PDF export answers `503`. Set the two font variables if the host
  has no DejaVu.
- **Database**: PostgreSQL for production, with database-native backups. The local
  `*_local_backup` commands refuse non-SQLite vendors by design.
- **Docs exposure**: `/api/schema/` and `/api/docs/` are absent (ordinary `404`) unless
  `DJANGO_API_DOCS_ENABLED=true`.

## 6. Operational checks after deployment

```bash
python manage.py migrate --check      # via the platform's release task
python manage.py verify_operational_integrity --json
curl -fsS https://<host>/api/health/ready/
```

Keep `DJANGO_DEBUG=false` in the deployed environment: debug mode leaks stack traces and
configuration.

## 7. Known observations

- `WorkflowVersionValidator` still spends a small constant number of queries per entry
  (room suitability reads the room's capability grants and sharing through related
  managers rather than their prefetch caches). Measured: 24 queries for a 2-entry version
  and 36 for an 8-entry version. Published reads, analytics, exports, entry lists and audit
  listing are flat. This is documented, bounded and non-blocking; it is a candidate for a
  future optimization, not a release blocker.
- `security.W021` as described above.
- PostgreSQL has been reviewed statically only; see `POSTGRESQL_READINESS.md`.

## 8. Not done in Phase 17

Railway configuration, PostgreSQL provisioning, container images, CI pipelines, tags and
GitHub releases. Deployment preparation starts only after the backend is accepted, and it
must not reuse SQLite as the production database.
