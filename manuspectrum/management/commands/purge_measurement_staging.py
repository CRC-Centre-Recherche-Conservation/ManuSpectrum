"""Run the measurement-files staging purge by hand.

Dry run by default: it lists the runs whose staging and rows would go and the
orphan stored names that would be removed, and writes nothing. ``--apply`` runs
the pass as the beat task does (same lock, same gauge).
"""

from django.core.management.base import BaseCommand, CommandError

from manuspectrum.measurement_files.purge import purge


class Command(BaseCommand):
    help = (
        "Remove the old staging of measurement-files runs (dry run by default, "
        "pass --apply to run the pass)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Run the pass: remove and stamp."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what the pass would do (the default).",
        )

    def handle(self, *args, apply=False, dry_run=False, **options):
        if apply and dry_run:
            raise CommandError("--apply and --dry-run exclude each other.")
        report = purge(apply=apply)
        if report.locked:
            self.stdout.write("Another purge is running: nothing done.")
            return
        prefix = "" if apply else "would be "
        for label, values in (
            ("run staging removed", report.staging_removed),
            ("run deleted", report.runs_deleted),
            ("orphan stored name removed", report.orphans),
            ("failed", report.failed),
        ):
            if values:
                self.stdout.write(f"{len(values)} {prefix}{label}")
                for value in values:
                    self.stdout.write(f"  {value}")
        if not apply:
            self.stdout.write("Dry run: nothing written. Pass --apply to run.")
