# PostgreSQL readiness

**Status: statically reviewed. Runtime verification against PostgreSQL has not been
performed.** No PostgreSQL server was installed, no driver was added, and no deployment
configuration was created in Phase 17. This document records what was checked, what is
expected to work, and what must be verified in the deployment environment.

## Current state

- Development and test databases are SQLite (`db.sqlite3`, in-memory for tests).
- All application persistence goes through the Django ORM. There is no raw SQL on any
  request path.
- SQLite-specific code is confined to `scheduling/services/operations/` (local backup,
  manifest, integrity) and is explicitly vendor-gated: the backup commands read
  `connection.vendor` and refuse anything that is not `sqlite`.
- The declared settings contain no vendor-specific tuning, and `DATABASES` is a single
  default alias.

## Static portability review

| Area | Finding |
| --- | --- |
| Raw SQL | None in application code. The only SQL literals are `SELECT 1` (readiness probe) and `PRAGMA integrity_check` (backup verification), both portable or explicitly SQLite-gated. The integrity command uses the ORM exclusively. |
| `sqlite3` imports | Only in the operations package (`scheduling/services/operations/backup.py`) and in test helpers. No request path imports it. |
| File-path assumptions | Only the backup tooling resolves a database file path, and it refuses non-file SQLite configurations (`:memory:`, `file:` URIs) as well as non-SQLite vendors. |
| Partial unique constraints | `UniqueConstraint(..., condition=Q(...))` (for example one active primary instructor per component). Supported by PostgreSQL; SQLite supports partial indexes too. |
| `CheckConstraint` with `condition=Q(...)` | Portable to PostgreSQL. |
| `JSONField` | Django's `JSONField` maps to `jsonb` on PostgreSQL; the values written are small, sanitized dictionaries. |
| `select_for_update()` | Portable, and **stronger** on PostgreSQL: see the concurrency section below. |
| Transactions | `transaction.atomic()` with savepoints; no SQLite-only transaction assumptions in application code. |
| Decimals | `DecimalField` with explicit `max_digits`/`decimal_places`; no float currency or hour arithmetic. |
| Time handling | `USE_TZ = True`, `TIME_ZONE = "Asia/Baghdad"`, timezone-aware datetimes; no naive datetimes are stored. |
| `auto_now`/`auto_now_add` | Standard, portable. |
| Sorting and collation | Ordering is by explicit columns, never by locale-dependent collation behavior. |
| Case sensitivity | Lookups are exact matches on codes; no `iexact` reliance in authorization paths. |

## Concurrency: what changes on PostgreSQL

`select_for_update()` is used to serialize workflow transitions and persistence writes
inside short transactions, with the CP-SAT solve kept outside the transaction.

- **PostgreSQL**: row-level locks are real. Two concurrent writers of the same schedule
  serialize, the second sees the committed state and correctly reports staleness or
  conflict.
- **SQLite**: locking is database-wide and coarser. The same code path works for a single
  local process, but it does not provide the same multi-process guarantee, and a write
  transaction blocks other writers for the duration.

The production target is PostgreSQL, and no custom distributed locking is implemented for
SQLite. Test suites are single-process, so they exercise the logic, not the lock
contention.

## Local backup tooling boundary

`create_local_backup`, `verify_local_backup` and `restore_local_backup` intentionally
refuse PostgreSQL:

```
Local SQLite backup tooling does not support database vendor 'postgresql'.
```

A file-level copy of a PostgreSQL database is not a backup. Deployment must use
database-native tooling (`pg_dump`/`pg_basebackup` or the managed platform's equivalent,
plus point-in-time recovery where available). Phase 16's manifest, checksum and
verification ideas remain valid, but the archive format is SQLite-specific.

## What runtime verification must cover

1. `python manage.py migrate` against a fresh PostgreSQL database, with no schema drift and
   a `makemigrations --check` that stays clean.
2. The full test suite against PostgreSQL (the suite is written against the ORM, so it
   should pass; deviations must be treated as real findings).
3. `select_for_update()` behavior under two concurrent writers on the same schedule.
4. Index usage for the hot reads: published timetable, version entries, analytics, audit
   listing.
5. `verify_operational_integrity` against the migrated database.
6. Backup and restore using PostgreSQL-native tools, plus a documented restore drill.
7. Connection settings for the platform: pooling, timeouts, and `CONN_MAX_AGE`.

## Not claimed

- PostgreSQL has **not** been executed against this code.
- No PostgreSQL driver is pinned in `requirements.txt` yet.
- No Railway, container, or managed-database configuration exists in this repository.

PostgreSQL driver and connection configuration belong to deployment preparation, after the
backend is accepted.
