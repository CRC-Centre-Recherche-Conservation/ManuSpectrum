"""
NORMALIZE FROLLO URIS

CONTEXT & PROBLEM:
The two controlled lists drawn from the Frollo TAPAC thesaurus
(``manuspectrum.constants.frollo.FROLLO_LIST_IDS``) were loaded from SKOS files
whose ``dcterms:identifier`` holds the bare Opentheso concept id, ``61296``.
arches-controlled-lists takes ``dcterms:identifier`` as the item URI
(``arches_controlled_lists/utils/skos.py``), so the items store ``61296`` as
their URI, and the reference datatype copies that URI into every tile that
cites the item. The report of a resource links a reference to its URI as is,
so the browser resolved ``61296`` against the report page and FORS pointed to
``/fr/report/61296`` (issue #294). Every other list of the package holds an
absolute URI, ``ListItem.uri`` is a ``URLField``, and the RO-Crate export and
the IIIF annotations use the URI as an identifier: a bare number is wrong in
all of them.

OBJECTIVE:
Give each of these items the address of its concept on Frollo,
``https://frollo.notre-dame.science/opentheso/?idc=<id>&idt=th12``, and give
the same string to every copy of it in tiles. The search and the Analysis
Explorer compare the tile copy with the item URI, so both move together.

HOW IT WORKS:
1. ``lists``: the items of the Frollo lists whose URI is digits only.
2. ``tiles``: every reference value (an object holding ``uri`` and
   ``list_id``) whose list is a Frollo list and whose URI is digits only, in
   ``tiles.tiledata`` and in ``tiles.provisionaledits`` (pending edits keep
   copies of the tile data).
   Rows are written with ``QuerySet.update`` in one transaction: no
   ``save()``, no Arches function, no edit log entry. The database triggers do
   run (``ms_data_change``, and ``ms_xy_reapply_on_technique`` on technique
   tiles, which re-applies a configuration keyed by list item id, not URI).
3. After the commit, the searchable Frollo lists whose items changed are
   reindexed (the ``references`` index holds item URIs), then the resources
   whose tiles changed: Elasticsearch keeps copies of both, and the search
   for a TAPAC term compares the item URIs with the indexed copies. A reindex
   failure leaves the database rewritten and prints the command that finishes
   the job.

A URI made of anything other than digits (an AAT or ManuSpectrum URI on a few
TAPAC items, an address written by hand) and every other list are left alone.

OPTIONS:
--dry-run: reports the counts, writes and indexes nothing (run this first)

The command is idempotent: once rewritten, a second run finds nothing to do.
It runs after the package is loaded on a fresh installation
(``deploy/docker/entrypoint.sh``, ``init``), where it does nothing once the
package itself carries the addresses.
"""

import re
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q, TextField
from django.db.models.functions import Cast

from arches.app.models.models import TileModel
from arches.app.models.resource import Resource
from arches.app.utils.index_database import index_resources_using_singleprocessing
from arches_controlled_lists.models import List, ListItem

from manuspectrum.constants.frollo import FROLLO_LIST_IDS, frollo_concept_url

BARE_ID = re.compile(r"[0-9]+")
BATCH = 500


def concept_url(uri):
    """The Frollo address for *uri* when it is a bare concept id, else None."""
    if isinstance(uri, str) and BARE_ID.fullmatch(uri.strip()):
        return frollo_concept_url(uri.strip())
    return None


def canonical_id(value):
    """*value* as a canonical UUID string, or None when it is not one."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


def rewrite(value, list_ids):
    """``(new_value, rewritten_count)``: the reference URIs of *value* fixed.

    A reference is any object holding ``uri`` and ``list_id``, wherever it
    sits in the JSON (a tile's node value, or a pending edit's copy of it).
    """
    if isinstance(value, list):
        pairs = [rewrite(item, list_ids) for item in value]
        return [new for new, _ in pairs], sum(n for _, n in pairs)
    if not isinstance(value, dict):
        return value, 0
    if "uri" in value and canonical_id(value.get("list_id")) in list_ids:
        new_uri = concept_url(value["uri"])
        if new_uri is not None:
            return {**value, "uri": new_uri}, 1
        return value, 0
    pairs = {key: rewrite(item, list_ids) for key, item in value.items()}
    return (
        {key: new for key, (new, _) in pairs.items()},
        sum(n for _, n in pairs.values()),
    )


class Command(BaseCommand):
    help = (
        "Replace the bare Opentheso ids of the Frollo TAPAC list items by the "
        "concepts' Frollo addresses, in the lists and in tiles (--dry-run "
        "reports counts only)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report the counts without touching the database or the index",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.list_ids = {str(uuid.UUID(list_id)) for list_id in FROLLO_LIST_IDS}
        self.resource_ids = set()
        self.changed_lists = set()
        verb = "would rewrite" if self.dry_run else "rewrote"

        with transaction.atomic():
            items = self.do_lists()
            tile_rows, references = self.do_tiles()

        self.stdout.write(f"lists: {verb} {items} item URI(s)")
        self.stdout.write(
            f"tiles: {verb} {references} reference(s) in {tile_rows} row(s)"
        )
        if self.dry_run:
            self.stdout.write("dry-run: run without --dry-run to write.")
            return
        if self.changed_lists or self.resource_ids:
            self.reindex()

    def do_lists(self):
        """Rewrite the bare ids of the Frollo list items; returns their number."""
        items = list(
            ListItem.objects.filter(
                list_id__in=self.list_ids, uri__regex=r"^\s*[0-9]+\s*$"
            ).only("pk", "uri")
        )
        for item in items:
            item.uri = concept_url(item.uri)
            self.changed_lists.add(item.list_id)
        if items and not self.dry_run:
            ListItem.objects.bulk_update(items, ["uri"], batch_size=BATCH)
        return len(items)

    def do_tiles(self):
        """Rewrite the reference copies in tiles; returns ``(rows, references)``."""
        rows = references = 0
        for field in ("data", "provisionaledits"):
            mentions = Q()
            for list_id in self.list_ids:
                mentions |= Q(text__icontains=list_id)
            candidates = (
                TileModel.objects.annotate(text=Cast(field, TextField()))
                .filter(mentions)
                .values_list("pk", flat=True)
            )
            pks = list(candidates)
            for start in range(0, len(pks), BATCH):
                chunk = TileModel.objects.filter(pk__in=pks[start : start + BATCH])
                for pk, resource_id, value in chunk.values_list(
                    "pk", "resourceinstance_id", field
                ):
                    new, count = rewrite(value, self.list_ids)
                    if not count:
                        continue
                    rows += 1
                    references += count
                    self.resource_ids.add(resource_id)
                    if not self.dry_run:
                        TileModel.objects.filter(pk=pk).update(**{field: new})
        return rows, references

    def reindex(self):
        """Push the rewritten URIs to Elasticsearch: lists, then resources.

        The rewrite is committed by then. A step that fails does not stop the
        other one, and the output names the command that finishes the job.
        """
        failures = []
        lists = 0
        try:
            for controlled_list in List.objects.filter(
                pk__in=self.changed_lists, searchable=True
            ):
                controlled_list.index()
                lists += 1
        except Exception as error:
            failures.append(("lists", error))
        try:
            self.index_resources(sorted(self.resource_ids, key=str))
        except Exception as error:
            failures.append(("resources", error))
        for what, error in failures:
            self.stderr.write(
                self.style.ERROR(
                    f"Reindexing the {what} failed "
                    f"({error.__class__.__name__}: {error})."
                )
            )
        if failures:
            self.stderr.write(
                "The database is rewritten; finish with: "
                "python manage.py es reindex_database"
            )
            return
        self.stdout.write(
            f"index: reindexed {len(self.resource_ids)} resource(s) "
            f"and {lists} list(s)"
        )

    def index_resources(self, resource_ids):
        """Reindex *resource_ids* (documents and terms), as ``es index_resources`` does."""
        if not resource_ids:
            return
        index_resources_using_singleprocessing(
            Resource.objects.filter(pk__in=resource_ids), quiet=True
        )
