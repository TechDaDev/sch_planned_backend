"""The backup manifest and the migration fingerprint.

An archive carries a manifest so it can be verified without the database it came from.
The manifest describes *what* was backed up and *how to prove it is intact*: byte size,
SHA-256, the SQLite integrity verdict, the applied migrations and a fingerprint of those
migrations.

The fingerprint is the compatibility contract. It is the SHA-256 of the canonical
``app.migration`` list, sorted, so two installations with the same applied migrations agree
and a backup taken against a different schema can be refused before anything is replaced.

Nothing secret is written: no secret key, no credentials, no environment, no user data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from django.db import connections
from django.db.migrations.recorder import MigrationRecorder

#: Manifest format version. Bumped only for an incompatible manifest change, because the
#: verifier refuses a format it does not know how to read.
FORMAT_VERSION = 1

#: Archive member names. Exactly these two members are allowed.
MANIFEST_MEMBER = "manifest.json"
DATABASE_MEMBER = "database.sqlite3"
ALLOWED_MEMBERS = (MANIFEST_MEMBER, DATABASE_MEMBER)

#: Project identifier written into every manifest.
PROJECT_NAME = "sch_planner_backend"

#: Required manifest keys and their expected primitive types.
REQUIRED_FIELDS = {
    "format_version": int,
    "created_at": str,
    "project": str,
    "database_vendor": str,
    "django_version": str,
    "database_size": int,
    "database_sha256": str,
    "applied_migrations": list,
    "migration_fingerprint": str,
    "integrity_check": str,
}


@dataclass(frozen=True)
class ManifestIssue:
    """One reason a manifest cannot be trusted."""

    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def migration_names(*, connection=None) -> tuple[str, ...]:
    """Every applied migration as ``app.migration``, sorted.

    Read from the archive's own ``django_migrations`` table when a connection is given,
    otherwise from the default connection.
    """
    connection = connection or connections["default"]
    recorder = MigrationRecorder(connection)
    rows = recorder.migration_qs.values_list("app", "name")
    return tuple(sorted(f"{app}.{name}" for app, name in rows))


def migration_fingerprint(names: Iterable[str]) -> str:
    """SHA-256 of the canonical migration list.

    The list is sorted and newline-joined before hashing, so the fingerprint depends on
    *which* migrations are applied and not on the order they were read.
    """
    canonical = "\n".join(sorted(str(name) for name in names))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def utc_timestamp(moment: datetime | None = None) -> str:
    """ISO-8601 UTC timestamp with a trailing ``Z``."""
    moment = moment or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_manifest(
    *,
    database_size: int,
    database_sha256: str,
    applied_migrations: Sequence[str],
    integrity_check: str,
    django_version: str,
    database_vendor: str = "sqlite",
    created_at: datetime | None = None,
    app_timezone: str = "",
) -> dict[str, Any]:
    """Assemble the manifest of one backup."""
    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "created_at": utc_timestamp(created_at),
        "project": PROJECT_NAME,
        "database_vendor": database_vendor,
        "django_version": django_version,
        "database_size": int(database_size),
        "database_sha256": str(database_sha256),
        "applied_migrations": sorted(str(name) for name in applied_migrations),
        "migration_fingerprint": migration_fingerprint(applied_migrations),
        "integrity_check": str(integrity_check),
    }
    if app_timezone:
        manifest["app_timezone"] = str(app_timezone)
    return manifest


def manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Canonical JSON bytes: sorted keys, fixed indent, UTF-8.

    Canonical form keeps two backups of the same state byte-comparable and makes the
    manifest diffable by an operator.
    """
    return json.dumps(
        dict(manifest), sort_keys=True, indent=2, ensure_ascii=False
    ).encode("utf-8")


def parse_manifest(data: bytes) -> tuple[dict[str, Any] | None, tuple[ManifestIssue, ...]]:
    """Parse and shape-check a manifest.

    Returns the manifest and the issues found. A manifest with any issue must not be used:
    the caller decides whether that is a refusal (it always is).
    """
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, (
            ManifestIssue("MANIFEST_UNREADABLE", f"The manifest is not valid JSON: {exc}"),
        )

    if not isinstance(decoded, dict):
        return None, (
            ManifestIssue("MANIFEST_UNREADABLE", "The manifest is not a JSON object."),
        )

    issues: list[ManifestIssue] = []
    for field, expected in REQUIRED_FIELDS.items():
        if field not in decoded:
            issues.append(
                ManifestIssue("MANIFEST_FIELD_MISSING", f"Missing field '{field}'.")
            )
            continue
        if not isinstance(decoded[field], expected):
            issues.append(
                ManifestIssue(
                    "MANIFEST_FIELD_INVALID",
                    (
                        f"Field '{field}' must be {expected.__name__}, got "
                        f"{type(decoded[field]).__name__}."
                    ),
                )
            )
    if decoded.get("format_version") != FORMAT_VERSION:
        issues.append(
            ManifestIssue(
                "MANIFEST_FORMAT_UNSUPPORTED",
                (
                    f"Manifest format version {decoded.get('format_version')!r} is not "
                    f"supported; this build reads version {FORMAT_VERSION}."
                ),
            )
        )
    if decoded.get("database_vendor") and decoded.get("database_vendor") != "sqlite":
        issues.append(
            ManifestIssue(
                "MANIFEST_VENDOR_UNSUPPORTED",
                (
                    f"The archive was taken from database vendor "
                    f"'{decoded.get('database_vendor')}'; local SQLite tooling cannot "
                    "verify or restore it."
                ),
            )
        )
    if decoded.get("integrity_check") not in (None, "", "ok") and not issues:
        issues.append(
            ManifestIssue(
                "MANIFEST_INTEGRITY_NOT_OK",
                (
                    "The manifest records an unsuccessful SQLite integrity check: "
                    f"{decoded.get('integrity_check')!r}."
                ),
            )
        )
    if "applied_migrations" in decoded and isinstance(
        decoded["applied_migrations"], list
    ):
        expected_fingerprint = migration_fingerprint(decoded["applied_migrations"])
        if decoded.get("migration_fingerprint") != expected_fingerprint:
            issues.append(
                ManifestIssue(
                    "MANIFEST_FINGERPRINT_MISMATCH",
                    (
                        "The recorded migration fingerprint does not match the recorded "
                        "migration list, so the manifest was edited or damaged."
                    ),
                )
            )
    return decoded, tuple(issues)


__all__ = [
    "ALLOWED_MEMBERS",
    "DATABASE_MEMBER",
    "FORMAT_VERSION",
    "MANIFEST_MEMBER",
    "PROJECT_NAME",
    "REQUIRED_FIELDS",
    "ManifestIssue",
    "build_manifest",
    "manifest_bytes",
    "migration_fingerprint",
    "migration_names",
    "parse_manifest",
    "utc_timestamp",
]
