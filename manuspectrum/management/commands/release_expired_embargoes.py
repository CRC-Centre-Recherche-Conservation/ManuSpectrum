"""Run the embargo pass by hand: record restrictions, send notices, lift expired ones.

Dry-run by default: it lists what the daily pass would do and writes and sends
nothing. ``--apply`` runs the pass as the beat task does (same lock, same mail,
same metrics).
"""

from django.core.management.base import BaseCommand

from manuspectrum.accounts.embargo import run_pass


class Command(BaseCommand):
    help = (
        "Record, warn about and lift expired embargoes (dry-run by default, "
        "pass --apply to run the pass)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Run the pass: write, send the notices and lift.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what the pass would do (the default).",
        )

    def handle(self, *args, apply=False, dry_run=False, **options):
        if apply and dry_run:
            self.stderr.write("--apply and --dry-run exclude each other.")
            return
        report = run_pass(apply=apply)
        if report.locked:
            self.stdout.write("Another embargo pass is running: nothing done.")
            return
        prefix = "" if apply else "would be "
        for label, ids in (
            ("recorded", report.detected),
            ("released by hand", report.released),
            ("noticed", report.noticed),
            (
                "due" if not apply else "lifted",
                report.due if not apply else report.lifted,
            ),
            ("incomplete", report.incomplete),
            ("kept (end date extended)", report.skipped_extended),
            ("failed", report.failed),
        ):
            if ids:
                self.stdout.write(f"{len(ids)} {prefix}{label}")
                for resource_id in ids:
                    self.stdout.write(f"  {resource_id}")
        self.stdout.write(
            f"{report.undated} restrictions without an end date (never lifted)."
        )
        if not apply:
            self.stdout.write("Dry run: nothing written or sent. Pass --apply to run.")
