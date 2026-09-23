"""Give every stored file the metadata and licence the application expects.

Each entry of a ``file-list`` value carries four localised metadata fields
(``altText``, ``title``, ``attribution``, ``description``) and a ``license``.
``FileListDataType.append_to_document`` walks ``f[field].keys()`` unguarded,
so ``python manage.py es index_resources`` dies with::

    AttributeError: 'NoneType' object has no attribute 'keys'

on the first entry whose metadata is ``None``. Entries written outside the
upload widget, including by the Arches CSV/ETL import, lack them.

The command completes every entry through
:func:`manuspectrum.utils.file_entries.normalize_metadata`, the single rule
server-side writers also use: missing metadata becomes empty strings, a
missing ``license`` becomes ``--license`` (default: the catalogue default of
:mod:`manuspectrum.constants.licenses`). Nothing already stored is replaced.

Dry-run by default; pass ``--apply`` to write.
"""

from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from arches.app.models.models import Node, TileModel

from manuspectrum.constants.licenses import (
    CUSTOM_LICENSE_ID,
    DEFAULT_LICENSE_ID,
    LICENSE_KEY,
    LICENSES,
)
from manuspectrum.utils.file_entries import METADATA_FIELDS, normalize_metadata


class Command(BaseCommand):
    help = (
        "Fill in missing localised metadata and licences on stored files "
        "(dry-run by default, pass --apply to write)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes (default is a dry-run report).",
        )
        parser.add_argument(
            "--language",
            default=None,
            help="Restrict to one language code (default: every configured language).",
        )
        parser.add_argument(
            "--license",
            dest="license_id",
            default=DEFAULT_LICENSE_ID,
            help=(
                "SPDX id of the licence given to files that have none "
                f"(default: {DEFAULT_LICENSE_ID})."
            ),
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        language_code = options["language"]
        file_license = self.catalogue_license(options["license_id"])

        file_nodes = list(Node.objects.filter(datatype="file-list"))
        if not file_nodes:
            self.stdout.write("No file-list node in this graph set.")
            return

        node_names = {str(node.nodeid): node.name for node in file_nodes}

        by_node = Counter()
        fields_filled = 0
        licenses_set = 0
        tiles_changed = 0
        files_changed = 0

        tiles = TileModel.objects.filter(
            nodegroup_id__in={node.nodegroup_id for node in file_nodes}
        )

        for tile in tiles.iterator():
            touched = False
            for node_id, node_name in node_names.items():
                entries = tile.data.get(node_id)
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    had_license = isinstance(entry, dict) and LICENSE_KEY in entry
                    filled = normalize_metadata(entry, language_code, file_license)
                    if filled:
                        if isinstance(entry, dict) and not had_license:
                            licenses_set += 1
                            filled -= 1
                        fields_filled += filled
                        files_changed += 1
                        by_node[node_name] += 1
                        touched = True

            if touched:
                tiles_changed += 1
                if apply_changes:
                    # A plain UPDATE: this restores metadata the widget would
                    # have written, it is not a curatorial edit. It must not run
                    # functions, write an edit-log entry, or index — the reindex
                    # is the whole point and comes after.
                    TileModel.objects.filter(pk=tile.tileid).update(data=tile.data)

        self.stdout.write("")
        for name, count in sorted(by_node.items()):
            self.stdout.write(f"  {name}: {count} file(s)")
        self.stdout.write(
            f"  {fields_filled} field(s) across {', '.join(METADATA_FIELDS)}"
        )
        self.stdout.write(f"  {licenses_set} licence(s) set to {file_license['id']}")

        summary = (
            f"{files_changed} file(s) across {tiles_changed} tile(s) "
            f"{'repaired' if apply_changes else 'would be repaired'}"
        )
        self.stdout.write("")
        if apply_changes:
            self.stdout.write(self.style.SUCCESS(summary))
            self.stdout.write("Now run:  python manage.py es index_resources")
        else:
            self.stdout.write(self.style.WARNING(summary + " (dry run)"))
            self.stdout.write("Pass --apply to write.")

    @staticmethod
    def catalogue_license(license_id):
        """``{"id", "url"}`` of a catalogue licence; the custom entry is refused."""
        for entry in LICENSES:
            if entry["id"] == license_id and license_id != CUSTOM_LICENSE_ID:
                return {"id": entry["id"], "url": entry["url"]}
        raise CommandError(
            f"{license_id!r} is not a catalogue licence; choose one of "
            + ", ".join(e["id"] for e in LICENSES if e["id"] != CUSTOM_LICENSE_ID)
        )
