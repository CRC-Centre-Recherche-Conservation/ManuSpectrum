"""Run the abandoned-workflow pass by hand: notices and cleanup of idle runs.

Dry-run by default: it lists the runs that would be noticed and cleaned, with
the resources that would be deleted and kept, and writes and sends nothing.
``--apply`` runs the pass as the beat task does (same lock, same mail, same
metrics). ``--workflow <id>`` restricts the pass to one run.
"""

import uuid

from django.core.management.base import BaseCommand, CommandError

from manuspectrum.accounts.workflows import run_pass


class Command(BaseCommand):
    help = (
        "Warn about and clean abandoned workflow runs (dry-run by default, "
        "pass --apply to run the pass)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Run the pass: write, send the notices and clean.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what the pass would do (the default).",
        )
        parser.add_argument(
            "--workflow",
            action="append",
            default=[],
            help="Restrict the pass to this workflow id (repeatable).",
        )

    def handle(self, *args, apply=False, dry_run=False, workflow=(), **options):
        if apply and dry_run:
            raise CommandError("--apply and --dry-run exclude each other.")
        try:
            only = [uuid.UUID(value) for value in workflow]
        except ValueError as exc:
            raise CommandError("--workflow takes a workflow id (UUID).") from exc
        report = run_pass(apply=apply, only=only or None)
        if report.locked:
            self.stdout.write("Another workflow pass is running: nothing done.")
            return
        prefix = "" if apply else "would be "
        for label, ids in (
            ("noticed", report.noticed),
            ("undelivered (will be retried)", report.undelivered),
            ("cleaned" if apply else "cleaned (see below)", report.cleaned),
            ("cleaned with resources kept", report.kept_resources),
            ("failed", report.failed),
        ):
            if ids:
                self.stdout.write(f"{len(ids)} {prefix}{label}")
                for workflow_id in ids:
                    self.stdout.write(f"  {workflow_id}")
        for workflow_id, plan in report.plans.items():
            self.stdout.write(
                f"{workflow_id}: {len(plan.deletable)} to delete, "
                f"{len(plan.kept)} to keep, {len(plan.reused)} reused or linked"
            )
        if apply:
            self.stdout.write(f"{report.deleted} deleted, {report.kept} kept.")
        else:
            self.stdout.write("Dry run: nothing written or sent. Pass --apply to run.")
