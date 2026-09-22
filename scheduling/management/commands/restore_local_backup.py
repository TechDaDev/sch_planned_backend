"""``manage.py restore_local_backup <archive> --confirm RESTORE`` - replace the local SQLite database.

This is the only destructive Phase 16 tool, so it is deliberately hard to run by accident:

1. the archive is verified completely (members, manifest, checksum, SQLite integrity);
2. the migration fingerprint must match this installation, or the restore is refused;
3. a safety backup of the current database is created automatically - if that fails, the
   restore does not happen;
4. the database is extracted to a temporary file, integrity-checked, and only then moved
   over the live file with ``os.replace``;
5. the restored file is verified, and a failure rolls back to the safety backup.

``--dry-run`` performs steps 1-2 and stops, which is the safe way to check an archive before
committing to a restore. There is no flag that skips verification or the safety backup.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from scheduling.services.operations import (
    RESTORE_CONFIRMATION,
    BackupError,
    restore_backup,
)


class Command(BaseCommand):
    help = (
        "Replace the local SQLite database with a verified backup. Requires "
        f"--confirm {RESTORE_CONFIRMATION}; a pre-restore safety backup is always created. "
        "SQLite only."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("archive", help="Path to the backup .zip archive.")
        parser.add_argument(
            "--confirm",
            default="",
            help=(
                f"Must be exactly {RESTORE_CONFIRMATION}. Without it nothing is replaced."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Verify the archive and stop. Nothing is replaced and no confirmation is needed.",
        )
        parser.add_argument(
            "--target",
            default="",
            help=(
                "SQLite file to replace. Defaults to the configured database; intended for "
                "tests and for restoring into a copy."
            ),
        )
        parser.add_argument(
            "--directory",
            default="",
            help="Directory for the automatic safety backup. Defaults to LOCAL_BACKUP_DIR.",
        )

    def handle(self, *args, **options) -> None:
        archive = Path(options["archive"])
        target = Path(options["target"]) if options["target"] else None
        directory = Path(options["directory"]) if options["directory"] else None
        dry_run = bool(options["dry_run"])

        try:
            result = restore_backup(
                archive=archive,
                target=target,
                confirm=options["confirm"],
                dry_run=dry_run,
                directory=directory,
            )
        except BackupError as exc:
            raise CommandError(f"[{exc.code}] {exc.message}") from exc

        for name, passed in result.checks.items():
            self.stdout.write(f"  {name}: {'ok' if passed else 'FAILED'}")

        if result.safety_backup is not None:
            self.stdout.write(f"safety_backup: {result.safety_backup}")

        if not result.ok:
            for issue in result.issues:
                self.stderr.write(f"  [{issue.code}] {issue.message}")
            raise CommandError(result.message or "The restore did not complete.")

        self.stdout.write(self.style.SUCCESS(result.message))
        if dry_run:
            self.stdout.write(
                "Re-run with --confirm "
                f"{RESTORE_CONFIRMATION} to perform the replacement."
            )
