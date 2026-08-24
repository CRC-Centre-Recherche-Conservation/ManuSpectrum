"""Give every stored file the localised metadata the search indexer expects.

Arches 8 added ``altText``, ``title``, ``attribution`` and ``description`` to
each entry of a ``file-list`` value. Files uploaded before that — and files
written by paths that never went through the widget — carry ``None`` for them.

The widget hides this: it hydrates missing metadata client-side on load. The
indexer does not, and ``FileListDataType.append_to_document`` walks
``f[field].keys()`` unguarded, so ``python manage.py es index_resources`` dies
with::

    AttributeError: 'NoneType' object has no attribute 'keys'

on the first such file — one malformed entry stops the entire reindex.

The repair itself lives in :func:`manuspectrum.utils.file_entries.normalize_metadata`,
which is also what server-side writers should use when creating an entry, so
this command and the conversion workflow cannot drift apart.

Dry-run by default; pass ``--apply`` to write.
"""

from collections import Counter

from django.core.management.base import BaseCommand

from arches.app.models.models import Node, TileModel

from manuspectrum.utils.file_entries import METADATA_FIELDS, normalize_metadata


class Command(BaseCommand):
    help = (
        "Fill in missing localised metadata on stored files so the search "
        "indexer can walk them (dry-run by default, pass --apply to write)."
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
            help="Language code for the empty entries (default: LANGUAGE_CODE).",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        language_code = options["language"]

        file_nodes = list(Node.objects.filter(datatype="file-list"))
        if not file_nodes:
            self.stdout.write("No file-list node in this graph set.")
            return

        node_names = {str(node.nodeid): node.name for node in file_nodes}

        by_node = Counter()
        fields_filled = 0
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
                    filled = normalize_metadata(entry, language_code)
                    if filled:
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
