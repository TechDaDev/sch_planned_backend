"""``manage.py verify_local_backup <archive>`` - verify a local backup without restoring it.

Verification is independent of creation: archive shape and member names, manifest presence
and schema, format version, database vendor, byte size, SHA-256, the SQLite integrity
verdict and the migration fingerprint. A failure exits non-zero, so the command is usable
as a check in an operator's routine.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from scheduling.services.operations import BackupError, verify_backup


class Command(BaseCommand):
    help = (
        "Verify a local backup archive: members, manifest, checksum, SQLite integrity and "
        "schema compatibility. Nothing is extracted permanently and nothing is replaced."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("archive", help="Path to the backup .zip archive.")
        parser.add_argument(
            "--allow-schema-mismatch",
            action="store_true",
            help=(
                "Report the checks without failing on a different migration fingerprint. "
                "It only affects this report; restore still refuses a mismatched archive."
            ),
        )

    def handle(self, *args, **options) -> None:
        archive = Path(options["archive"])
        try:
            verification = verify_backup(
                archive, check_schema=not options["allow_schema_mismatch"]
            )
        except BackupError as exc:
            raise CommandError(f"[{exc.code}] {exc.message}") from exc

        self.stdout.write(f"archive: {verification.path}")
        for name, passed in verification.checks.items():
            marker = "ok" if passed else "FAILED"
            self.stdout.write(f"  {name}: {marker}")
        if verification.manifest is not None:
            self.stdout.write(
                f"manifest: format_version={verification.manifest['format_version']} "
                f"created_at={verification.manifest['created_at']} "
                f"vendor={verification.manifest['database_vendor']}"
            )
            self.stdout.write(
                f"database_sha256: {verification.database_sha256}\n"
                f"migration_fingerprint: {verification.migration_fingerprint}"
            )

        if not verification.ok:
            for issue in verification.issues:
                self.stderr.write(f"  [{issue.code}] {issue.message}")
            raise CommandError(
                f"Backup verification failed with {len(verification.issues)} issue(s)."
            )
        self.stdout.write(self.style.SUCCESS("Backup verified: all checks passed."))
