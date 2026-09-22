"""Operational services: local SQLite backup, verification, restore and integrity checks.

These are operator tools, not application features. They are reachable only through Django
management commands - never through HTTP - because a restore replaces the whole database
and belongs on a shell with an explicit confirmation, not behind a token.

``manifest``
    the archive manifest and the migration fingerprint that makes schema compatibility
    checkable.
``backup``
    create, verify and restore: online SQLite snapshot, checksum, integrity verdict, zip
    safety, atomic replacement, automatic pre-restore safety backup.
``integrity``
    read-only structural verification of the stored data, with stable issue codes.

Scope is SQLite. PostgreSQL and hosted databases are refused with a clear message, because
their backup strategy belongs to deployment work with their own native tooling.
"""

from scheduling.services.operations.backup import (
    RESTORE_CONFIRMATION,
    SUPPORTED_VENDOR,
    BackupCreation,
    BackupError,
    BackupIssue,
    BackupVerification,
    RestoreResult,
    create_backup,
    current_migration_fingerprint,
    default_backup_directory,
    resolve_sqlite_path,
    restore_backup,
    sha256_file,
    sqlite_integrity_check,
    verify_backup,
)
from scheduling.services.operations.integrity import (
    IntegrityIssue,
    IntegrityReport,
    run_integrity_checks,
)
from scheduling.services.operations.manifest import (
    FORMAT_VERSION,
    build_manifest,
    migration_fingerprint,
    migration_names,
    parse_manifest,
)

__all__ = [
    "FORMAT_VERSION",
    "RESTORE_CONFIRMATION",
    "SUPPORTED_VENDOR",
    "BackupCreation",
    "BackupError",
    "BackupIssue",
    "BackupVerification",
    "IntegrityIssue",
    "IntegrityReport",
    "RestoreResult",
    "build_manifest",
    "create_backup",
    "current_migration_fingerprint",
    "default_backup_directory",
    "migration_fingerprint",
    "migration_names",
    "parse_manifest",
    "resolve_sqlite_path",
    "restore_backup",
    "run_integrity_checks",
    "sha256_file",
    "sqlite_integrity_check",
    "verify_backup",
]
