"""Delete the rows of the data-version ledger ``ms_data_change`` older than ``--days``.

Celery beat runs the same prune once a day (``CELERY_BEAT_SCHEDULE``); this
command is for a deployment without beat, or to prune by hand.
"""

from django.core.management.base import BaseCommand

from manuspectrum.utils.data_version import PRUNE_AFTER_DAYS, prune_data_changes


class Command(BaseCommand):
    help = "Delete the data-version ledger rows older than --days (default 7)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=PRUNE_AFTER_DAYS)

    def handle(self, *args, days, **options):
        deleted = prune_data_changes(days)
        self.stdout.write(f"{deleted} ledger row(s) older than {days} day(s) deleted.")
