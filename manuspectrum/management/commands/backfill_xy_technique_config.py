"""Apply technique-derived XY configurations to measurement files already stored.

:mod:`manuspectrum.functions.xy_technique_config` fills in a file's renderer and
viewer configuration as it is saved. Files uploaded *before* that function
existed never went through it: at the time of writing, 65 of 71 measurement
files carried no renderer at all, because Arches only matches a renderer at
upload time and only on an exact extension match.

This command replays the same mapping over the existing store. It applies the
identical rules — a file entry is touched only when it has no configuration and
no provenance marker, and an analysis whose techniques disagree is left alone —
so running it can never contradict what the function would have done, nor
overwrite a curator's choice.

Dry-run by default; pass ``--apply`` to write.
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from arches.app.models.models import TileModel
from arches.app.models.tile import Tile

from manuspectrum.constants.xy_presets import (
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    XY_PRESETS,
)
from manuspectrum.functions.xy_technique_config import (
    apply_config_to_file_entries,
    is_xy_text_file,
    resolve_config_id,
)

#: config id -> preset key, so the report names families rather than UUIDs.
PRESET_NAMES = {preset["config_id"]: key for key, preset in XY_PRESETS.items()}


class Command(BaseCommand):
    help = (
        "Apply the technique-derived XY viewer configuration to measurement "
        "files already in store (dry-run by default, pass --apply to write)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes (default is a dry-run report).",
        )
        parser.add_argument(
            "--resource",
            dest="resource_id",
            help="Restrict to a single Analysis resource instance id.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        resource_id = options.get("resource_id")

        tiles = TileModel.objects.filter(nodegroup_id=DATA_FILE_NODEGROUP_ID)
        if resource_id:
            tiles = tiles.filter(resourceinstance_id=resource_id)

        by_preset = Counter()
        skipped = Counter()
        tiles_changed = 0
        files_changed = 0

        # One lookup per analysis, not per tile: an analysis commonly holds
        # several measurement files and they all share its technique.
        config_cache = {}

        for tile in tiles.iterator():
            entries = tile.data.get(DATA_FILE_NODE_ID) or []
            if not entries:
                continue

            resource_key = str(tile.resourceinstance_id)
            if resource_key not in config_cache:
                config_cache[resource_key] = resolve_config_id(tile.resourceinstance_id)
            config_id = config_cache[resource_key]

            if not config_id:
                for entry in entries:
                    if isinstance(entry, dict) and not entry.get("rendererConfig"):
                        skipped["no technique, or techniques disagree"] += 1
                continue

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("rendererConfig"):
                    skipped["already configured"] += 1
                elif not is_xy_text_file(entry):
                    skipped["not an XY text format"] += 1

            changed = apply_config_to_file_entries(entries, config_id)
            if not changed:
                continue

            tiles_changed += 1
            files_changed += changed
            by_preset[PRESET_NAMES.get(config_id, config_id)] += changed

            if apply_changes:
                with transaction.atomic():
                    # The proxy re-enters the function, which finds every entry
                    # now marked and skips it — so this converges in one pass.
                    # index=False: a bulk backfill should not fan out one
                    # Elasticsearch write per tile.
                    proxy = Tile.objects.get(pk=tile.tileid)
                    proxy.data = tile.data
                    proxy.save(index=False)

        self.stdout.write("")
        for preset, count in sorted(by_preset.items()):
            self.stdout.write(f"  {preset:<14} {count} file(s)")
        for reason, count in sorted(skipped.items()):
            self.stdout.write(f"  skipped: {reason} — {count} file(s)")

        summary = (
            f"{files_changed} file(s) across {tiles_changed} tile(s) "
            f"{'updated' if apply_changes else 'would be updated'}"
        )
        self.stdout.write("")
        if apply_changes:
            self.stdout.write(self.style.SUCCESS(summary))
            if files_changed:
                self.stdout.write(
                    "Reindex the Analysis model so the changes reach search:\n"
                    "  python manage.py es index_resources"
                )
        else:
            self.stdout.write(self.style.WARNING(summary + " (dry run)"))
            self.stdout.write("Pass --apply to write.")
