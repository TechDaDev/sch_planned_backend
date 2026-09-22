"""``manage.py create_local_backup`` - snapshot the local SQLite database.

The command is a thin shell around :func:`scheduling.services.operations.create_backup`:
it resolves the destination, calls the service and prints what an operator needs to record
(the path, the size, the checksum and the migration fingerprint). No secret is printed.

SQLite only. A PostgreSQL database is refused with a clear message, because file copying is
not a backup strategy for it.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from scheduling.services.operations import BackupError, create_backup


class Command(BaseCommand):
    help = (
        "Create a verified local backup of the SQLite database (SQLite only). The archive "
        "contains manifest.json and database.sqlite3."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--directory",
            default="",
            help=(
                "Destination directory. Defaults to the LOCAL_BACKUP_DIR setting "
                "(<project>/var/backups)."
            ),
        )
        parser.add_argument(
            "--source",
            default="",
            help=(
                "SQLite file to back up. Defaults to the configured database; intended for "
                "tests and for backing up a copy."
            ),
        )

    def handle(self, *args, **options) -> None:
        directory = Path(options["directory"]) if options["directory"] else None
        source = Path(options["source"]) if options["source"] else None
        try:
            creation = create_backup(source=source, directory=directory)
        except BackupError as exc:
            raise CommandError(f"[{exc.code}] {exc.message}") from exc

        self.stdout.write(self.style.SUCCESS("Local backup created and verified."))
        self.stdout.write(f"archive: {creation.path}")
        self.stdout.write(f"created_at: {creation.manifest['created_at']}")
        self.stdout.write(f"database_size: {creation.size} bytes")
        self.stdout.write(f"database_sha256: {creation.checksum}")
        self.stdout.write(f"migration_fingerprint: {creation.fingerprint}")
        self.stdout.write(f"integrity_check: {creation.manifest['integrity_check']}")
        self.stdout.write(
            "Verify it independently with: manage.py verify_local_backup "
            f"{creation.path}"
        )
