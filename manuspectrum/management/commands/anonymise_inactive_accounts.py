"""Run the account retention pass by hand: warn about and anonymise inactive accounts.

Dry-run by default: it lists, by user id, what the daily pass would do and
writes and sends nothing. ``--apply`` runs the pass as the beat task does (same
lock, same mail, same metrics). ``--as-of YYYY-MM-DD`` runs it as if it were
that day in Paris (rehearsals); with ``--apply`` it is refused when
``DEPLOY_ENVIRONMENT`` is ``production``.
"""

import os
from datetime import date, datetime, time

from django.core.management.base import BaseCommand, CommandError

from manuspectrum.accounts.embargo import LOCAL_TZ
from manuspectrum.accounts.retention import run_pass


class Command(BaseCommand):
    help = (
        "Warn about and anonymise accounts without sign-in (dry-run by default, "
        "pass --apply to run the pass)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Run the pass: write, send the notices and anonymise.",
        )
        parser.add_argument(
            "--as-of",
            metavar="YYYY-MM-DD",
            help="Rehearsal: run as if it were noon in Paris on that day.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what the pass would do (the default).",
        )

    def handle(self, *args, apply=False, dry_run=False, as_of=None, **options):
        if apply and dry_run:
            raise CommandError("--apply and --dry-run exclude each other.")
        now = None
        if as_of:
            if apply and os.environ.get("DEPLOY_ENVIRONMENT") == "production":
                raise CommandError(
                    "--as-of with --apply is a rehearsal and is refused when "
                    "DEPLOY_ENVIRONMENT is production."
                )
            try:
                day = date.fromisoformat(as_of)
            except ValueError:
                raise CommandError("--as-of expects a date as YYYY-MM-DD.")
            now = datetime.combine(day, time(12), tzinfo=LOCAL_TZ)
        report = run_pass(now, apply=apply)
        if report.locked:
            self.stdout.write("Another retention pass is running: nothing done.")
            return
        prefix = "" if apply else "would be "
        for label, ids in (
            ("notice sent", report.noticed),
            ("notice void (signed in since)", report.reset),
            ("anonymised", report.anonymised),
            ("superusers due for a decision (never anonymised)", report.superusers_due),
            ("failed", report.failed),
        ):
            if ids:
                verb = (
                    ""
                    if label.startswith(("notice void", "superusers", "failed"))
                    else prefix
                )
                self.stdout.write(f"{len(ids)} {verb}{label}")
                for user_id in ids:
                    self.stdout.write(f"  user {user_id}")
        if not apply:
            self.stdout.write("Dry run: nothing written or sent. Pass --apply to run.")
