"""Print the activity of one calendar month as one line of JSON: counts per model, workflow and ETL module.

Read-only (`manuspectrum.observability.activity`); no user and no resource id is
printed. Used by `make -C deploy monthly-report`.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from manuspectrum.observability import activity


class Command(BaseCommand):
    help = "Print the content, workflow and ETL activity of a month (YYYY-MM) as JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--month", required=True, help="Calendar month, YYYY-MM (UTC)."
        )

    def handle(self, *args, **options):
        try:
            summary = activity.monthly_summary(options["month"])
        except ValueError as error:
            raise CommandError(str(error))
        self.stdout.write(json.dumps(summary, sort_keys=True))
