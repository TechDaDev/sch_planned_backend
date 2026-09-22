# Final backend architecture

College Academic Schedule Planner — backend release candidate (`1.0.0`).

This document is a map, not a tutorial. The README explains behavior in detail per
feature; this file explains how the pieces fit together and which invariants must hold for
the backend to be correct.

## Layer model

```
HTTP clients (web app, future Flutter app, operators)
        |
        v
URL routing            config/api_urls.py, <app>/urls.py
        |
        v
Views / viewsets       authorization, scoping, (de)serialization only
        |
        v
Serializers            request/response contracts, strict field validation
        |
        v
Services               the actual domain work, one package per concern
        |
        +--> Pure solver (scheduling/services/solver) - no Django imports
        |            ^
        |            |
        |    Generation builders (services/generation) translate ORM state
        |    into solver inputs and back
        |
        v
Django ORM             models, constraints, transactions
        |
        v
SQLite (development, tests) / PostgreSQL (deployment target, not yet exercised)
```

The dependency direction is strictly downward. A view never contains domain logic, a
model never calls a service, and the pure solver never imports Django. That is what keeps
the CP-SAT engine testable without a database and keeps the HTTP layer replaceable.

## Application packages

| Package | Responsibility |
| --- | --- |
| `config` | settings, root URLconf, health probes, API exception handler |
| `accounts` | custom `User`, roles, JWT login/refresh, `/api/me/` |
| `academics` | college → department → program → stage → group, and course → offering → component → group link |
| `resources` | instructor profiles, sharing and availability, rooms, room sharing and capabilities, teaching assignments, room requirements |
| `scheduling` | calendar and time grid, validation, generation, persistence, manual editing, workflow, publication, analytics, exports, imports, audit, operations |
| `reports` | reserved placeholder; Phase 15 exports live in `scheduling/services/exports` |

## Feature phases

| Phase | Added |
| --- | --- |
| 0 | project skeleton, settings, JWT plumbing, `/api/health/`, OpenAPI |
| 1 | roles, permissions, authentication |
| 2 | academic structure |
| 3 | courses, offerings, teaching components, joint teaching |
| 4 | instructors: sharing, availability, preferences, assignments |
| 5 | rooms, capabilities, requirements |
| 6 | calendar grid: working days, periods, breaks, exceptions |
| 7 | pre-scheduling validation (readiness report) |
| 8 | pure CP-SAT engine, no Django, no persistence |
| 9 | department scheduler preview |
| 10 | college-wide scheduler preview |
| 11 | schedule persistence: `Schedule`, `ScheduleVersion`, `ScheduleEntry`, snapshots |
| 12 | validated manual editing (copy-on-write) |
| 13 | workflow and official publication |
| 14 | analytics over persisted versions and the publication |
| 15 | Excel/PDF export and controlled Excel import |
| 16 | audit trail, local SQLite backup, operational integrity |
| 17 | production settings hardening, health probes, error hardening, docs exposure, release documentation |

## Five invariants

1. **History is snapshot-based.** Every persisted placement stores the display values it
   was created with (`*_snapshot` columns). Renaming a live course, room, department,
   instructor or group never changes a published timetable, an analytics report or an
   export. Only room utilization is current-configuration, and it says so per row.
2. **Versions are immutable.** A version's entries, periods, instructors, groups and
   snapshots are written once by persistence or by a copy-on-write manual edit. Workflow
   transitions change status and stage metadata only.
3. **Scoping fails closed.** Out-of-scope rows answer `404` rather than confirming they
   exist, a department-scoped account without a department sees nothing (or is refused),
   and every mutation is authorized from `request.user` plus persisted relationships, never
   from a client-supplied id.
4. **Read paths do not write.** Validation, previews, analytics, exports, published reads
   and the integrity command perform reads only. This is asserted by tests, including an
   audit-row count that must not move.
5. **Concurrency-critical writes are serialized** by `select_for_update()` inside short
   transactions, with the solver run outside the transaction. On PostgreSQL this is real
   row locking; on SQLite it is weaker (see `POSTGRESQL_READINESS.md`).

## Cross-cutting behavior

- **Authentication**: SimpleJWT bearer tokens (access 30 minutes, refresh 7 days).
  `IsAuthenticated` is the DRF default, so a new endpoint is protected unless it opts out.
- **Authorization**: role gates in `<app>/permissions.py` plus `visible_*_filter` helpers
  that scope querysets. Role decides reachability, scoping decides visibility.
- **Parsers**: JSON only, except the three Phase 15 import endpoints, which declare
  `MultiPartParser` locally.
- **Audit**: eight named successful operations write an `AuditEvent` inside the same
  transaction as the mutation. Reads are never audited.
- **Errors**: documented DRF errors keep their bodies; an unhandled exception answers
  generic JSON with a request id and is logged server-side with the traceback.
- **Observability**: `X-Request-ID` is accepted (sanitized, length-capped), generated when
  absent, echoed on every response, attached to audit rows and included in error bodies.
- **Documentation exposure**: `/api/schema/` and `/api/docs/` are registered only when
  `API_DOCS_ENABLED` is true (development default). The `spectacular` management command
  works in either mode.

## Operational tooling

| Tool | Boundary |
| --- | --- |
| `create_local_backup` | SQLite files only; refuses any other vendor; operator-only |
| `verify_local_backup` | independent checks of archive shape, manifest, checksum, SQLite integrity, migration fingerprint |
| `restore_local_backup` | requires `--confirm RESTORE`, creates a safety backup first, replaces atomically, refuses schema mismatch |
| `verify_operational_integrity` | read-only structural checks; never repairs |

No backup or restore capability is exposed over HTTP, and there is no generic ORM history
framework: the audit trail records eight named operations, nothing more.
