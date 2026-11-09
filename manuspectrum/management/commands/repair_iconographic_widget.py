"""
REPAIR ICONOGRAPHIC WIDGET

Gives the Component node « Iconographic representation » the Biblissima
concept widget (`biblissima-concept-widget`) in place of the generic URL widget
the data package assigns (#289), in the database and in every language of the
graph's current publication, without publishing a new graph version: existing
resources keep their publication and stay editable. What is written, and what
is left alone, is described in `manuspectrum/utils/iconographic_widget.py`.

    manage.py repair_iconographic_widget [--dry-run]

`init` runs it after the data package is loaded and checked, and the
development setup in README.md after `load_package`; migration
`0017_iconographic_widget` does the same on existing databases. Idempotent: a
second run reports that there is nothing to do. Exits 1 when the widget is not
registered (`manage.py project update` registers the project's widgets).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from manuspectrum.utils.iconographic_widget import (
    CONCEPT_WIDGET_ID,
    NODE_ID,
    URL_WIDGET_ID,
    repair,
)

NODE = f"Iconographic representation ({NODE_ID})"


class Command(BaseCommand):
    help = (
        "Give the Component node « Iconographic representation » the Biblissima "
        "concept widget, in place (no new graph publication)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change and write nothing",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        with transaction.atomic():
            outcome = repair(connection)
            if dry_run:
                transaction.set_rollback(True)

        if outcome.status == "absent":
            self.stdout.write(
                f"{NODE} is not in the database (the data package is not loaded): "
                "nothing to do"
            )
            return
        if outcome.status == "unregistered":
            raise CommandError(
                f"The widget biblissima-concept-widget ({CONCEPT_WIDGET_ID}) is not "
                "registered: run manage.py project update, then this command again"
            )
        if outcome.status == "other":
            self.stdout.write(
                f"{NODE} uses the widget {outcome.widget_id}, neither the URL widget "
                f"({URL_WIDGET_ID}) nor biblissima-concept-widget: left unchanged"
            )
            return
        if not outcome.changed:
            self.stdout.write(
                f"{NODE} already uses biblissima-concept-widget in the database and in "
                "every language of its current publication: nothing to do"
            )
            return

        languages = ", ".join(outcome.languages) or "none"
        changes = (
            f"biblissima-concept-widget: {outcome.rows} card-node-widget row(s); "
            f"publication {outcome.publication_id}, languages: {languages} "
            "(in place, no new publication)"
        )
        if dry_run:
            self.stdout.write(f"Dry run, nothing written: {NODE} would use {changes}")
        else:
            self.stdout.write(self.style.SUCCESS(f"{NODE} now uses {changes}"))
