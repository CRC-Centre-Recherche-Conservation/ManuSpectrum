"""
REFRESH REFERENCE LABELS

Completes the reference values stored in tiles that lack a prefLabel in a
language of `settings.LANGUAGES`, from their list items (issue #290).

CONTEXT & PROBLEM:
A reference value stores the labels of its list item, and the reference-select
widget renders the prefLabel stored for the active language with no fallback.
Until `repair_reference_defaults` ran, 22 reference widget defaults carried the
English prefLabel only: a resource saved with such a default keeps an
English-only value and shows "Unlabeled Item" under /fr/, even once the
default is fixed.

WHAT IT DOES:
Each reference of a tile value that lacks a prefLabel in a site language is
replaced by its list item's labels (`ListItem.build_tile_value()` shape: every
prefLabel and altLabel). A complete reference is left as stored. See
`manuspectrum.utils.reference_labels`.

The write is a plain UPDATE of that node's key, made only if the stored value
is still the one read (a value edited meanwhile is skipped and reported): this
restores labels the widget would have written, it is not a curatorial edit, so
it runs no tile function and writes no edit-log entry. For each resource it
changed, it then recomputes the descriptors (name, description, map popup),
since a reference node can feed them, and reindexes the resource, since its
labels are search terms.

SAFETY:
Idempotent: once complete, a value is never rewritten. A reference whose list
item is gone is reported and left alone; a list item that itself lacks a
language is reported (add the label in the Controlled List Manager, then run it
again). Provisional edits are not touched.

OPTIONS:
--dry-run: reports what would change, changes nothing (run this first)
"""

import copy
import json
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from arches.app.models.models import (
    FunctionXGraph,
    Node,
    ResourceInstance,
    TileModel,
)

from manuspectrum.utils.reference_labels import (
    REFERENCE_DATATYPE,
    TileValueCache,
    complete_value,
    site_languages,
)

# Compare-and-set on one node of one tile: nothing is written when the value
# changed since it was read.
_UPDATE_SQL = """
    UPDATE tiles
    SET tiledata = jsonb_set(tiledata, ARRAY[%s], %s::jsonb)
    WHERE tileid = %s AND tiledata -> %s = %s::jsonb
"""

# The descriptors Arches' Resource.save_descriptors() computes.
_DESCRIPTORS = ("name", "description", "map_popup")


def refresh_descriptors(resource, functions_by_graph):
    """Recompute the descriptors of ``resource`` in every site language and
    store them. Returns True when they changed.

    A reference node can feed a descriptor (a resource's name, say). Under a
    language its stored value lacked, the descriptor holds the label that
    ``ListItem.find_best_label_from_set`` fell back to, and
    ``Resource.index()`` copies the stored descriptors into the search
    document without recomputing them.

    The computation is the one of Arches' ``Resource.save_descriptors()``: the
    graph's single ``primarydescriptors`` function, for each language of
    ``settings.LANGUAGES``. Only the ``descriptors`` and ``name`` columns are
    written, with an UPDATE, because ``save_descriptors()`` ends with
    ``ResourceInstance.save()``. That save rewrites the whole row and moves
    the resource onto its graph's current publication, which only a
    migration of its data may do (#289). A graph without exactly one
    descriptor function is left alone (``save_descriptors()`` would blank
    the descriptors).

    ``functions_by_graph`` caches the descriptor functions per graph id across
    calls.
    """
    graph_id = resource.graph_id
    if graph_id not in functions_by_graph:
        functions_by_graph[graph_id] = list(
            FunctionXGraph.objects.filter(
                graph_id=graph_id, function__functiontype="primarydescriptors"
            ).select_related("function")
        )
    functions = functions_by_graph[graph_id]
    if len(functions) != 1:
        return False
    module = functions[0].function.get_class_module()()
    descriptor_types = (functions[0].config or {}).get("descriptor_types") or {}

    stored = resource.descriptors if isinstance(resource.descriptors, dict) else {}
    descriptors = copy.deepcopy(stored)
    stored_names = dict(resource.name.raw_value) if resource.name is not None else {}
    names = dict(stored_names)
    # One context per resource: the function caches its graph nodes and the
    # resource's tiles in it, and reads the language from it.
    context = {}
    for language in site_languages():
        context["language"] = language
        computed = dict(descriptors.get(language) or {})
        for descriptor in _DESCRIPTORS:
            if descriptor not in descriptor_types:
                continue
            value = module.get_primary_descriptor_from_nodes(
                resource, descriptor_types[descriptor], context, descriptor
            )
            computed[descriptor] = value
            if descriptor == "name" and value is not None:
                names[language] = value
        descriptors[language] = computed

    if descriptors == stored and names == stored_names:
        return False
    ResourceInstance.objects.filter(pk=resource.pk).update(
        descriptors=descriptors, name=names
    )
    # Resource.index() reads the descriptors of the instance in memory.
    resource.descriptors = descriptors
    return True


class Command(BaseCommand):
    help = (
        "Complete the reference values stored in tiles that lack a prefLabel "
        "in a site language, from their list items"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report what would change without touching the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        languages = site_languages()

        nodes_by_group = defaultdict(list)
        for node_id, nodegroup_id in Node.objects.filter(
            datatype=REFERENCE_DATATYPE
        ).values_list("nodeid", "nodegroup_id"):
            nodes_by_group[str(nodegroup_id)].append(str(node_id))
        if not nodes_by_group:
            self.stdout.write("No reference node. Nothing to do.")
            return

        lookup = TileValueCache()
        planned = []  # (tile id, resource id, node id, stored value, new value)
        unresolved, still_missing = set(), {}
        tiles = (
            TileModel.objects.filter(nodegroup_id__in=nodes_by_group)
            .order_by("pk")
            .values_list("tileid", "resourceinstance_id", "nodegroup_id", "data")
        )
        for tile_id, resource_id, nodegroup_id, data in tiles.iterator(chunk_size=500):
            for node_id in nodes_by_group[str(nodegroup_id)]:
                stored = (data or {}).get(node_id)
                completion = complete_value(stored, languages, lookup)
                unresolved.update(completion.unresolved)
                still_missing.update(completion.still_missing)
                if completion.changed:
                    planned.append(
                        (tile_id, resource_id, node_id, stored, completion.value)
                    )

        self.stdout.write(f"Site languages: {', '.join(languages)}")
        self.stdout.write(
            f"  reference values to complete: {len(planned)} in "
            f"{len({row[0] for row in planned})} tile(s) of "
            f"{len({row[1] for row in planned})} resource(s)"
        )
        for item_id in sorted(unresolved, key=str):
            self.stdout.write(
                f"  [unresolved] list item {item_id or '(none named)'} not found: "
                "value left as it is"
            )
        for item_id, missing in sorted(still_missing.items()):
            self.stdout.write(
                f"  [list item] {item_id} has no prefLabel in {', '.join(missing)}: "
                "add it in the Controlled List Manager, then run this again"
            )
        if dry_run:
            self.stdout.write("Dry run: nothing was changed.")
            return
        if not planned:
            self.stdout.write(
                "Every stored reference value is complete. Nothing to do."
            )
            return

        written, skipped, resources = 0, 0, set()
        with transaction.atomic(), connection.cursor() as cursor:
            for tile_id, resource_id, node_id, stored, value in planned:
                cursor.execute(
                    _UPDATE_SQL,
                    [node_id, json.dumps(value), tile_id, node_id, json.dumps(stored)],
                )
                if cursor.rowcount:
                    written += 1
                    resources.add(resource_id)
                else:
                    skipped += 1
        self.stdout.write(f"Completed {written} reference value(s).")
        if skipped:
            self.stdout.write(
                f"  {skipped} value(s) changed since they were read and were "
                "left alone: run this again"
            )
        self.refresh_resources(resources)

    def refresh_resources(self, resource_ids):
        """Recompute the descriptors of the changed resources, then reindex
        them: a reference can feed a descriptor, and labels are search terms."""
        from arches.app.models.resource import Resource

        functions_by_graph = {}
        described, indexed, failed = 0, 0, []
        for resource in Resource.objects.filter(pk__in=resource_ids).order_by("pk"):
            try:
                if refresh_descriptors(resource, functions_by_graph):
                    described += 1
                resource.index()
            except Exception as error:  # noqa: BLE001 — the values are already saved
                failed.append(f"{resource.pk} ({type(error).__name__}: {error})")
            else:
                indexed += 1
        self.stdout.write(f"Descriptors updated for {described} resource(s).")
        self.stdout.write(f"Reindexed {indexed} resource(s).")
        for line in failed:
            self.stdout.write(f"  [not reindexed] {line}")
        if failed:
            self.stdout.write("Then run:  python manage.py es index_resources")
