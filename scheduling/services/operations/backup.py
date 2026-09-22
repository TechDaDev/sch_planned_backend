"""Local SQLite backup, verification and restore.

Scope is deliberately narrow: **SQLite only**, called only from management commands, never
from HTTP. This is the tooling an operator runs on the development or single-server
database. PostgreSQL and any hosted database belong to deployment work with their own
native tooling, so every entry point here refuses a non-SQLite vendor instead of guessing
that copying a file is equivalent.

Three properties matter more than convenience:

* **the source is never copied while live.** The snapshot is taken with SQLite's own online
  backup API, which reads a consistent database even while the application has the file
  open. ``shutil.copy`` on a live SQLite file can capture a torn state.
* **nothing is trusted without proof.** Creation runs ``PRAGMA integrity_check`` before
  archiving; verification re-checks the archive shape, the manifest, the byte size, the
  SHA-256, the SQLite integrity verdict and the migration fingerprint.
* **replacement is atomic and preceded by a safety backup.** Restore writes the verified
  database to a controlled temporary file, then ``os.replace``s it, and if the result does
  not verify it restores the safety copy it took first.

Nothing here logs or returns a secret: the artifacts, their checksums, their paths and the
migration fingerprint are the whole vocabulary.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import django
from django.conf import settings
from django.db import connections

from scheduling.services.operations.manifest import (
    ALLOWED_MEMBERS,
    DATABASE_MEMBER,
    FORMAT_VERSION,
    MANIFEST_MEMBER,
    ManifestIssue,
    build_manifest,
    manifest_bytes,
    migration_fingerprint,
    migration_names,
    parse_manifest,
    utc_timestamp,
)

#: Vendor this tooling supports.
SUPPORTED_VENDOR = "sqlite"

#: Confirmation word a destructive restore requires.
RESTORE_CONFIRMATION = "RESTORE"

#: Suffix applied to a pre-restore safety archive, so it is never mistaken for a routine
#: backup.
SAFETY_LABEL = "pre-restore"

#: Directory and file permissions for the backup directory and the archives in it. The
#: database holds account and timetable data, so the artefacts are owner-only.
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600


class BackupError(Exception):
    """A refused backup operation.

    ``code`` is a stable identifier for the operator (and for tests); the message is meant
    to be printed.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BackupIssue:
    """One failed verification check."""

    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class BackupCreation:
    """A backup that was written and verified before it was placed."""

    path: Path
    manifest: dict[str, Any]
    created_at: datetime

    @property
    def size(self) -> int:
        return int(self.manifest["database_size"])

    @property
    def checksum(self) -> str:
        return str(self.manifest["database_sha256"])

    @property
    def fingerprint(self) -> str:
        return str(self.manifest["migration_fingerprint"])


@dataclass(frozen=True)
class BackupVerification:
    """The outcome of verifying one archive."""

    path: Path
    checks: dict[str, bool] = field(default_factory=dict)
    issues: tuple[BackupIssue, ...] = ()
    manifest: dict[str, Any] | None = None
    database_sha256: str = ""
    migration_fingerprint: str = ""

    @property
    def ok(self) -> bool:
        """True only when every required check passed."""
        return not self.issues and all(self.checks.values()) and bool(self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": str(self.path),
            "checks": dict(self.checks),
            "issues": [issue.as_dict() for issue in self.issues],
            "manifest": self.manifest,
        }


@dataclass(frozen=True)
class RestoreResult:
    """The outcome of one restore attempt."""

    ok: bool
    dry_run: bool
    target: Path
    verification: BackupVerification
    safety_backup: Path | None = None
    message: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    issues: tuple[BackupIssue, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "target": str(self.target),
            "safety_backup": (
                None if self.safety_backup is None else str(self.safety_backup)
            ),
            "checks": dict(self.checks),
            "issues": [issue.as_dict() for issue in self.issues],
            "message": self.message,
            "verification": self.verification.as_dict(),
        }


# --- connection facts ---------------------------------------------------------


def resolve_sqlite_path(connection=None) -> Path:
    """The file this project's SQLite database lives in, or a refusal.

    A non-SQLite vendor or a non-file SQLite database is refused here, once, so no other
    function has to guess what "the database file" means.
    """
    connection = connection or connections["default"]
    vendor = connection.vendor
    if vendor != SUPPORTED_VENDOR:
        raise BackupError(
            "LOCAL_BACKUP_UNSUPPORTED_VENDOR",
            (
                f"Local SQLite backup tooling does not support database vendor "
                f"'{vendor}'. Use database-native {vendor} backup tooling during "
                "deployment."
            ),
        )
    name = str(connection.settings_dict.get("NAME") or "")
    if not name or name == ":memory:" or name.startswith("file:"):
        raise BackupError(
            "LOCAL_BACKUP_UNSUPPORTED_DATABASE",
            (
                "This database is not a file-backed SQLite database "
                f"(NAME={name!r}), so it cannot be backed up or restored as a file."
            ),
        )
    return Path(name)


def current_migration_fingerprint() -> str:
    """Fingerprint of the migrations applied to the running database."""
    return migration_fingerprint(migration_names())


def default_backup_directory() -> Path:
    """The configured backup directory, created with owner-only permissions."""
    directory = Path(settings.LOCAL_BACKUP_DIR)
    ensure_private_directory(directory)
    return directory


def ensure_private_directory(directory: Path) -> None:
    """Create the directory if needed and restrict it to its owner."""
    directory.mkdir(parents=True, exist_ok=True)
    _restrict_directory(directory)


def _restrict_directory(directory: Path) -> None:
    if os.name != "posix":
        # POSIX modes do not exist here; there is nothing to restrict.
        return
    try:
        os.chmod(directory, DIRECTORY_MODE)
    except OSError as exc:
        raise BackupError(
            "LOCAL_BACKUP_PERMISSION_FAILED",
            f"The backup directory {directory} could not be restricted: {exc}",
        ) from exc


def _restrict_file(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        os.chmod(path, FILE_MODE)
    except OSError as exc:
        raise BackupError(
            "LOCAL_BACKUP_PERMISSION_FAILED",
            f"The backup file {path} could not be restricted: {exc}",
        ) from exc


# --- creation -----------------------------------------------------------------


def create_backup(
    *,
    source: Path | None = None,
    directory: Path | None = None,
    created_at: datetime | None = None,
    label: str = "",
) -> BackupCreation:
    """Snapshot the SQLite database into a verified archive and place it atomically.

    Every step happens in a temporary directory and the final archive is moved into place
    with ``os.replace``, so a failure leaves no file that looks like a finished backup.
    """
    source_path = Path(source) if source is not None else resolve_sqlite_path()
    if not source_path.is_file():
        raise BackupError(
            "LOCAL_BACKUP_SOURCE_MISSING",
            f"The database file {source_path} does not exist, so nothing was backed up.",
        )

    directory = Path(directory) if directory is not None else default_backup_directory()
    ensure_private_directory(directory)

    workdir = Path(tempfile.mkdtemp(prefix="sch_planner_backup_"))
    try:
        snapshot = workdir / DATABASE_MEMBER
        _snapshot_sqlite(source_path, snapshot)
        verdict = sqlite_integrity_check(snapshot)
        if verdict != "ok":
            raise BackupError(
                "LOCAL_BACKUP_INTEGRITY_FAILED",
                (
                    f"The database snapshot failed its integrity check ({verdict}), so no "
                    "backup was written."
                ),
            )

        size = snapshot.stat().st_size
        checksum = sha256_file(snapshot)
        manifest = build_manifest(
            database_size=size,
            database_sha256=checksum,
            applied_migrations=_migration_names_of(snapshot),
            integrity_check=verdict,
            django_version=django.get_version(),
            app_timezone=str(settings.TIME_ZONE),
            created_at=created_at,
        )
        (workdir / MANIFEST_MEMBER).write_bytes(manifest_bytes(manifest))

        stamp = utc_timestamp(created_at).replace("-", "").replace(":", "")
        suffix = f"_{label}" if label else ""
        filename = f"sch_planner_{stamp}_scheduler{suffix}_{checksum[:10]}.zip"
        _write_archive(workdir, directory / filename)

        return BackupCreation(
            path=directory / filename,
            manifest=manifest,
            created_at=created_at or datetime.now().astimezone(),
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _snapshot_sqlite(source: Path, destination: Path) -> None:
    """Copy a live SQLite database using the online backup API.

    The source is opened read-only and copied page by page by SQLite itself, so a
    concurrent writer cannot produce a torn snapshot the way a byte copy can.
    """
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin:
            with sqlite3.connect(destination) as target:
                origin.backup(target)
    except sqlite3.Error as exc:
        raise BackupError(
            "LOCAL_BACKUP_READ_FAILED",
            f"The database could not be read for backup: {exc}",
        ) from exc


def _migration_names_of(database: Path) -> tuple[str, ...]:
    """Applied migrations recorded inside an SQLite file."""
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            cursor = connection.execute(
                "SELECT app, name FROM django_migrations ORDER BY app, name"
            )
            return tuple(sorted(f"{app}.{name}" for app, name in cursor.fetchall()))
    except sqlite3.Error as exc:
        raise BackupError(
            "LOCAL_BACKUP_MIGRATIONS_UNREADABLE",
            f"The migration state could not be read from the snapshot: {exc}",
        ) from exc


def _write_archive(workdir: Path, destination: Path) -> None:
    """Zip exactly the two members and move the result into place atomically."""
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for member in ALLOWED_MEMBERS:
                archive.write(workdir / member, arcname=member)
        os.replace(temporary, destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise BackupError(
            "LOCAL_BACKUP_WRITE_FAILED",
            f"The backup archive could not be written to {destination}: {exc}",
        ) from exc
    _restrict_file(destination)


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in chunks so a large database does not fill memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sqlite_integrity_check(database: Path) -> str:
    """``PRAGMA integrity_check`` verdict of one SQLite file."""
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        return f"unreadable: {exc}"
    if not row:
        return "no result"
    return str(row[0])


__all__ = [
    "DIRECTORY_MODE",
    "FILE_MODE",
    "RESTORE_CONFIRMATION",
    "SAFETY_LABEL",
    "SUPPORTED_VENDOR",
    "BackupCreation",
    "BackupError",
    "BackupIssue",
    "BackupVerification",
    "RestoreResult",
    "create_backup",
    "current_migration_fingerprint",
    "default_backup_directory",
    "ensure_private_directory",
    "resolve_sqlite_path",
    "restore_backup",
    "sha256_file",
    "sqlite_integrity_check",
    "verify_backup",
]


# --- verification -------------------------------------------------------------


def verify_backup(
    archive: Path,
    *,
    expected_fingerprint: str | None = None,
    check_schema: bool = True,
) -> BackupVerification:
    """Verify an archive without extracting anything to a permanent location.

    Every check is independent and recorded, so an operator sees exactly what passed. The
    archive is opened read-only, the database member is extracted to a temporary file for
    the SQLite verdict, and the temporary file is removed afterwards. A traversal attempt,
    an unexpected member, a wrong checksum or a foreign schema all fail the verification.
    """
    archive = Path(archive)
    checks: dict[str, bool] = {}
    issues: list[BackupIssue] = []
    manifest: dict[str, Any] | None = None
    checksum = ""
    fingerprint = ""

    if not archive.is_file():
        return BackupVerification(
            path=archive,
            checks={"archive_exists": False},
            issues=(
                BackupIssue("BACKUP_MISSING", f"No such backup archive: {archive}"),
            ),
        )
    checks["archive_exists"] = True

    try:
        with zipfile.ZipFile(archive) as bundle:
            names = [info.filename for info in bundle.infolist() if not info.is_dir()]
            checks["archive_readable"] = True
            checks["members_expected"] = sorted(names) == sorted(ALLOWED_MEMBERS)
            checks["member_names_safe"] = all(_safe_member_name(name) for name in names)
            checks["no_duplicate_members"] = len(names) == len(set(names))
            if not checks["members_expected"]:
                issues.append(
                    BackupIssue(
                        "BACKUP_MEMBERS_UNEXPECTED",
                        (
                            "The archive must contain exactly "
                            f"{', '.join(ALLOWED_MEMBERS)}; found "
                            f"{', '.join(sorted(names)) or 'nothing'}."
                        ),
                    )
                )
            if not checks["member_names_safe"]:
                issues.append(
                    BackupIssue(
                        "BACKUP_MEMBER_PATH_UNSAFE",
                        (
                            "The archive contains an absolute or traversing member name, "
                            "so it was refused without extracting anything."
                        ),
                    )
                )
            if not checks["no_duplicate_members"]:
                issues.append(
                    BackupIssue(
                        "BACKUP_MEMBER_DUPLICATE",
                        "The archive contains a duplicate member name.",
                    )
                )

            manifest = _verify_manifest_member(bundle, checks, issues)
            verdict, checksum, fingerprint = _verify_database_member(
                bundle, manifest, checks, issues
            )
    except zipfile.BadZipFile as exc:
        return BackupVerification(
            path=archive,
            checks={"archive_readable": False},
            issues=(
                BackupIssue(
                    "BACKUP_UNREADABLE", f"The archive is not a readable zip file: {exc}"
                ),
            ),
        )

    if manifest is not None and check_schema:
        expected = expected_fingerprint or current_migration_fingerprint()
        compatible = bool(fingerprint) and fingerprint == expected
        checks["schema_compatible"] = compatible
        if not compatible:
            issues.append(
                BackupIssue(
                    "BACKUP_SCHEMA_MISMATCH",
                    (
                        "The archive was taken from a different schema: its migration "
                        f"fingerprint is {fingerprint or 'missing'}, this installation "
                        f"expects {expected}. Restore is refused."
                    ),
                )
            )

    return BackupVerification(
        path=archive,
        checks=checks,
        issues=tuple(issues),
        manifest=manifest,
        database_sha256=checksum,
        migration_fingerprint=fingerprint,
    )


def _safe_member_name(name: str) -> bool:
    """True when a member name stays inside the archive."""
    if not name or name.startswith(("/", "\\")) or "\\" in name:
        return False
    parts = Path(name).parts
    return bool(parts) and ".." not in parts and not Path(name).is_absolute()


def _verify_manifest_member(
    bundle: zipfile.ZipFile, checks: dict[str, bool], issues: list[BackupIssue]
) -> dict[str, Any] | None:
    """Read and shape-check the manifest member."""
    if MANIFEST_MEMBER not in bundle.namelist():
        checks["manifest_present"] = False
        issues.append(
            BackupIssue("MANIFEST_MISSING", f"The archive has no {MANIFEST_MEMBER}.")
        )
        return None
    checks["manifest_present"] = True
    data = bundle.read(MANIFEST_MEMBER)
    manifest, manifest_issues = parse_manifest(data)
    checks["manifest_readable"] = manifest is not None
    checks["manifest_fields"] = not any(
        issue.code.startswith("MANIFEST_FIELD") for issue in manifest_issues
    )
    checks["manifest_format_supported"] = not any(
        issue.code == "MANIFEST_FORMAT_UNSUPPORTED" for issue in manifest_issues
    )
    checks["manifest_vendor_supported"] = not any(
        issue.code == "MANIFEST_VENDOR_UNSUPPORTED" for issue in manifest_issues
    )
    checks["manifest_integrity_recorded_ok"] = not any(
        issue.code == "MANIFEST_INTEGRITY_NOT_OK" for issue in manifest_issues
    )
    checks["manifest_fingerprint_consistent"] = not any(
        issue.code == "MANIFEST_FINGERPRINT_MISMATCH" for issue in manifest_issues
    )
    for issue in manifest_issues:
        issues.append(BackupIssue(issue.code, issue.message))
    return manifest


def _verify_database_member(
    bundle: zipfile.ZipFile,
    manifest: dict[str, Any] | None,
    checks: dict[str, bool],
    issues: list[BackupIssue],
) -> tuple[str, str, str]:
    """Extract the database member to a temporary file and verify its contents."""
    if DATABASE_MEMBER not in bundle.namelist():
        checks["database_present"] = False
        issues.append(
            BackupIssue("BACKUP_DATABASE_MISSING", f"The archive has no {DATABASE_MEMBER}.")
        )
        return "missing", "", ""

    checks["database_present"] = True
    workdir = Path(tempfile.mkdtemp(prefix="sch_planner_verify_"))
    try:
        extracted = workdir / DATABASE_MEMBER
        with bundle.open(DATABASE_MEMBER) as source, open(extracted, "wb") as target:
            shutil.copyfileobj(source, target)

        size = extracted.stat().st_size
        checksum = sha256_file(extracted)

        # A tampered, truncated or foreign member may not be a SQLite database at all.
        # That is a verification result rather than an exception: the operator must see
        # which check failed, and nothing is extracted permanently either way. The
        # remaining checks still run, so the report names every reason the archive was
        # refused instead of only the first one.
        try:
            migration_names = _migration_names_of(extracted)
        except BackupError as exc:
            checks["database_readable"] = False
            fingerprint = ""
            issues.append(BackupIssue("BACKUP_DATABASE_UNREADABLE", exc.message))
        else:
            checks["database_readable"] = True
            fingerprint = migration_fingerprint(migration_names)

        if manifest is None:
            checks["database_size_matches"] = False
            checks["database_checksum_matches"] = False
            return "unknown", checksum, fingerprint

        size_matches = int(manifest.get("database_size", -1)) == size
        checks["database_size_matches"] = size_matches
        if not size_matches:
            issues.append(
                BackupIssue(
                    "BACKUP_SIZE_MISMATCH",
                    (
                        f"The database member is {size} bytes but the manifest records "
                        f"{manifest.get('database_size')}."
                    ),
                )
            )

        recorded = str(manifest.get("database_sha256", ""))
        checksum_matches = bool(recorded) and recorded == checksum
        checks["database_checksum_matches"] = checksum_matches
        if not checksum_matches:
            issues.append(
                BackupIssue(
                    "BACKUP_CHECKSUM_MISMATCH",
                    (
                        "The database member does not match the SHA-256 recorded in the "
                        "manifest, so the archive was modified or damaged."
                    ),
                )
            )

        verdict = sqlite_integrity_check(extracted)
        checks["sqlite_integrity_ok"] = verdict == "ok"
        if verdict != "ok":
            issues.append(
                BackupIssue(
                    "BACKUP_SQLITE_INTEGRITY_FAILED",
                    f"SQLite reported the database member as {verdict}.",
                )
            )
        return verdict, checksum, fingerprint
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --- restore -------------------------------------------------------------------


def restore_backup(
    *,
    archive: Path,
    target: Path | None = None,
    confirm: str | None = None,
    dry_run: bool = False,
    directory: Path | None = None,
    expected_fingerprint: str | None = None,
) -> RestoreResult:
    """Replace the SQLite database with a verified backup.

    Order is fixed and deliberately conservative: verify the archive, require an identical
    migration fingerprint, take a safety backup of the current database, extract and
    integrity-check the replacement, close the application's connections, replace the file
    atomically, and verify the result. A restore whose result does not verify is rolled
    back from the safety copy.
    """
    archive = Path(archive)
    target_path = Path(target) if target is not None else resolve_sqlite_path()
    directory = Path(directory) if directory is not None else default_backup_directory()

    verification = verify_backup(archive, expected_fingerprint=expected_fingerprint)
    if not verification.ok:
        return RestoreResult(
            ok=False,
            dry_run=dry_run,
            target=target_path,
            verification=verification,
            message="The archive failed verification, so nothing was replaced.",
            checks=dict(verification.checks),
            issues=verification.issues,
        )

    if dry_run:
        return RestoreResult(
            ok=True,
            dry_run=True,
            target=target_path,
            verification=verification,
            message=(
                "Dry run: the archive is verified and schema-compatible. Nothing was "
                "replaced."
            ),
            checks=dict(verification.checks),
        )

    if str(confirm or "") != RESTORE_CONFIRMATION:
        raise BackupError(
            "LOCAL_RESTORE_CONFIRMATION_REQUIRED",
            (
                "Restoring replaces the live database and cannot be undone. Re-run with "
                f"--confirm {RESTORE_CONFIRMATION} to proceed, or use --dry-run to check "
                "the archive first."
            ),
        )

    safety = create_backup(
        source=target_path,
        directory=directory,
        label=SAFETY_LABEL,
    )

    workdir = Path(tempfile.mkdtemp(prefix="sch_planner_restore_"))
    checks: dict[str, bool] = dict(verification.checks)
    issues: list[BackupIssue] = []
    try:
        prepared = workdir / DATABASE_MEMBER
        with zipfile.ZipFile(archive) as bundle:
            with bundle.open(DATABASE_MEMBER) as source, open(prepared, "wb") as sink:
                shutil.copyfileobj(source, sink)
        checks["extracted_integrity_ok"] = sqlite_integrity_check(prepared) == "ok"
        if not checks["extracted_integrity_ok"]:
            raise BackupError(
                "LOCAL_RESTORE_EXTRACT_FAILED",
                "The extracted database failed its integrity check, so nothing was replaced.",
            )

        _close_connections(target_path)
        os.replace(prepared, target_path)
        checks["replaced"] = True

        checks["restored_integrity_ok"] = sqlite_integrity_check(target_path) == "ok"
        checks["restored_fingerprint_matches"] = (
            migration_fingerprint(_migration_names_of(target_path))
            == verification.migration_fingerprint
        )
        if not (checks["restored_integrity_ok"] and checks["restored_fingerprint_matches"]):
            issues.append(
                BackupIssue(
                    "RESTORE_VERIFICATION_FAILED",
                    (
                        "The restored database did not verify, so the automatically created "
                        "safety backup was put back."
                    ),
                )
            )
            _roll_back(target_path=target_path, safety=safety.path, workdir=workdir)
            checks["rolled_back_from_safety"] = True
            return RestoreResult(
                ok=False,
                dry_run=False,
                target=target_path,
                verification=verification,
                safety_backup=safety.path,
                message="The restore was rolled back from the safety backup.",
                checks=checks,
                issues=tuple(issues),
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return RestoreResult(
        ok=True,
        dry_run=False,
        target=target_path,
        verification=verification,
        safety_backup=safety.path,
        message="The database was replaced with the verified backup.",
        checks=checks,
        issues=tuple(issues),
    )


def _close_connections(target_path: Path) -> None:
    """Close the connections that point at the file being replaced.

    Only the affected connection is closed: the file must not be swapped under an open
    handle, while an unrelated connection has no reason to be disturbed. The connection is
    reopened automatically - against the replacement file - on the next query.
    """
    resolved = target_path.resolve()
    for alias in list(connections):
        connection = connections[alias]
        name = str(connection.settings_dict.get("NAME") or "")
        if not name or name == ":memory:":
            continue
        try:
            matches = Path(name).resolve() == resolved
        except OSError:  # pragma: no cover - an unresolvable path cannot be the target
            matches = False
        if matches:
            connection.close()


def _roll_back(*, target_path: Path, safety: Path, workdir: Path) -> None:
    """Put the safety backup back in place of a failed restore."""
    replacement = workdir / f"safety_{DATABASE_MEMBER}"
    with zipfile.ZipFile(safety) as bundle:
        with bundle.open(DATABASE_MEMBER) as source, open(replacement, "wb") as sink:
            shutil.copyfileobj(source, sink)
    _close_connections(target_path)
    os.replace(replacement, target_path)
    _close_connections(target_path)
