"""Rewrite the site announcement snapshot nginx serves while Django is down.

Run by the ``web`` entrypoint after ``migrate``, so a fresh volume holds the
current payload before the first save.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from manuspectrum.views.site_notice import refresh


class Command(BaseCommand):
    help = "Store the fresh site announcement payload in the memo and rewrite its snapshot."

    def handle(self, *args, **options):
        path = refresh()
        if not settings.SITE_NOTICE_SNAPSHOT_DIR:
            self.stdout.write("disabled")
        else:
            self.stdout.write(path or "failed: see the log")
