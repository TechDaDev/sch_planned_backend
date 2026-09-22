"""``manage.py verify_operational_integrity`` - check the stored data, write nothing.

The command reports structural invariants the schema cannot express: connectivity, applied
migrations, the publication pointer, version numbering and lineage, entry completeness and
period ordering, and duplicate session identifiers.

It never repairs anything, never runs a migration and never changes a status. A healthy
database exits 0; any detected inconsistency exits non-zero with stable issue codes, so the
command can be a routine check or a monitoring hook.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from scheduling.services.operations import run_integrity_checks


class Command(BaseCommand):
    help = (
        "Verify operational integrity (read-only): migrations, publication pointer, version "
        "lineage, entry structure and duplicate sessions. Exits non-zero when it finds an "
        "inconsistency."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the report as JSON instead of text.",
        )

    def handle(self, *args, **options) -> None:
        report = run_integrity_checks()

        if options["json"]:
            self.stdout.write(json.dumps(report.as_dict(), indent=2, default=str))
        else:
            self.stdout.write("Operational integrity report")
            for line in report.summary_lines():
                self.stdout.write(line)
            self.stdout.write(
                "This command is read-only: nothing was repaired, migrated or changed."
            )

        if not report.ok:
            raise CommandError(
                "Operational integrity found "
                f"{len(report.issues)} structural issue(s). See the report above; nothing "
                "was repaired."
            )
        self.stdout.write(self.style.SUCCESS("Operational integrity: ok."))
