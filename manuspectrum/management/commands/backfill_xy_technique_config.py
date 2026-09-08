"""Re-run the XY configuration trigger over measurement files already stored.

The ``ms_xy_stamp_file_config`` trigger fires on every write, so a file saved
after it was installed is already configured. What it cannot reach is stock
written before it, or before a technique was added to ``TECHNIQUE_PRESETS``.
Touching those rows is enough: the trigger applies its usual rule, and never
touches an entry a curator has configured or cleared.

Dry-run by default; pass ``--apply`` to keep the changes.
"""

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from manuspectrum.constants.xy_presets import (
    CONFIG_SOURCE_AUTO,
    CONFIG_SOURCE_KEY,
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
)

COUNT_AUTO_ENTRIES = """
    SELECT count(*)
    FROM tiles, jsonb_array_elements(tiledata -> %(node)s) AS entry
    WHERE nodegroupid = %(nodegroup)s::uuid
      AND jsonb_typeof(tiledata -> %(node)s) = 'array'
      AND entry ->> %(source_key)s = %(auto)s
"""

TOUCH_FILE_TILES = """
    UPDATE tiles SET tiledata = tiledata
    WHERE nodegroupid = %(nodegroup)s::uuid
"""


class Command(BaseCommand):
    help = (
        "Apply the technique-derived XY viewer configuration to measurement "
        "files already in store (dry-run by default, pass --apply to write)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Keep the changes (default is a dry-run report).",
        )
        parser.add_argument(
            "--resource",
            dest="resource_id",
            help="Restrict to a single Analysis resource instance id.",
        )

    def handle(self, *args, **options):
        params = {
            "node": DATA_FILE_NODE_ID,
            "nodegroup": DATA_FILE_NODEGROUP_ID,
            "source_key": CONFIG_SOURCE_KEY,
            "auto": CONFIG_SOURCE_AUTO,
        }
        scope = ""
        if options["resource_id"]:
            params["resource"] = options["resource_id"]
            scope = " AND resourceinstanceid = %(resource)s::uuid"

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(COUNT_AUTO_ENTRIES + scope, params)
            (before,) = cursor.fetchone()
            cursor.execute(TOUCH_FILE_TILES + scope, params)
            tiles = cursor.rowcount
            cursor.execute(COUNT_AUTO_ENTRIES + scope, params)
            (after,) = cursor.fetchone()
            if not options["apply"]:
                transaction.set_rollback(True)

        changed = after - before
        summary = f"{changed} file(s) configured, {tiles} tile(s) touched"
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(summary))
            if changed:
                self.stdout.write(
                    "Reindex the Analysis model so the changes reach search:\n"
                    "  python manage.py es index_resources"
                )
        else:
            self.stdout.write(self.style.WARNING(summary + " (dry run)"))
            self.stdout.write("Pass --apply to write.")
