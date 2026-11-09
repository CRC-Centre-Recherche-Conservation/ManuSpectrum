"""Complete the reference values that lack a prefLabel in a site language.

A value of the ``reference`` datatype (arches-controlled-lists) stores the
labels of its list item, not just a pointer to it::

    [{"uri": ..., "list_id": ..., "labels": [{"id", "value", "language_id",
                                              "valuetype_id", "list_item_id"}]}]

The ``reference-select`` widget of arches-controlled-lists 1.2 renders the
prefLabel stored in the value for the ACTIVE language, with no fallback
(``getPrefLabel`` in ``media/js/viewmodels/reference-select.js``): a value
without an ``fr`` prefLabel shows "Unlabeled Item" under ``/fr/`` even though
its list item has one. A value picked from the list carries every label of the
item; a value written by other means may not. The data package shipped 22
reference widget defaults with the English prefLabel only (issue #290), and a
resource saved with such a default stores the English-only value in its tile.

:func:`complete_value` replaces each reference of a value that lacks a prefLabel
in a language of ``settings.LANGUAGES`` by what its list item gives today, in
the shape of ``ListItem.build_tile_value()``. A complete reference is left as
stored, whatever its list item says now; a reference whose list item is gone is
reported and left alone. Its users:

- :func:`repair_reference_defaults` (the ``repair_reference_defaults`` command,
  run by ``init`` after ``load_package``, and migration
  ``0017_reference_default_labels`` for existing databases): the default values
  of the reference widgets;
- the ``refresh_reference_labels`` command: the values stored in tiles;
- the ``manuspectrum.W007`` system check, through :func:`incomplete_defaults`.
"""

import copy
import json
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections, transaction

#: Node datatype of arches-controlled-lists references.
REFERENCE_DATATYPE = "reference"

# Rows of `cards_x_nodes_x_widgets` whose node is a reference and whose default
# is a list. Read with SQL because `config` is an I18n_JSONField: through the
# ORM it comes back as an `I18n_JSON` and is written back through its
# per-language `jsonb_set` logic, while only `defaultValue` is wanted here.
# No `jsonb_array_length` here: PostgreSQL does not promise to test the type
# first, and a default of "" or null would abort the query.
_DEFAULTS_SQL = """
    SELECT w.id, w.config -> 'defaultValue', n.name, COALESCE(g.slug, g.graphid::text)
    FROM cards_x_nodes_x_widgets w
    JOIN nodes n ON n.nodeid = w.nodeid
    JOIN graphs g ON g.graphid = n.graphid
    WHERE n.datatype = %s
      AND jsonb_typeof(w.config -> 'defaultValue') = 'array'
    ORDER BY 4, 3, w.id
"""

_UPDATE_DEFAULT_SQL = """
    UPDATE cards_x_nodes_x_widgets
    SET config = jsonb_set(config, '{defaultValue}', %s::jsonb)
    WHERE id = %s
"""


def site_languages():
    """The language codes of ``settings.LANGUAGES``, in their order."""
    return [code for code, _name in settings.LANGUAGES]


def _labels(reference):
    labels = reference.get("labels") if isinstance(reference, dict) else None
    return [label for label in labels or [] if isinstance(label, dict)]


def missing_languages(reference, languages):
    """The codes of ``languages`` for which ``reference`` holds no prefLabel."""
    present = {
        label.get("language_id")
        for label in _labels(reference)
        if label.get("valuetype_id") == "prefLabel" and label.get("value")
    }
    return [code for code in languages if code not in present]


def list_item_id(reference):
    """The id of the list item a reference points at, or None.

    Every label of a reference carries it (``ReferenceDataType`` refuses labels
    of two items); the reference itself has no other pointer to the item.
    """
    for label in _labels(reference):
        if label.get("list_item_id"):
            return str(label["list_item_id"])
    return None


def is_incomplete(reference, languages):
    return isinstance(reference, dict) and bool(missing_languages(reference, languages))


def _label_order(label):
    # prefLabels first, then a stable order: the value is compared with the one
    # stored, so the same item must always give the same list.
    return (
        label["valuetype_id"] != "prefLabel",
        label["valuetype_id"] or "",
        label["language_id"] or "",
        label["value"],
        label["id"],
    )


def tile_values(item_ids, using=DEFAULT_DB_ALIAS):
    """``{list item id: tile value}`` for the given items that carry a label.

    The tile value has the shape of ``ListItem.build_tile_value()`` (every
    prefLabel and altLabel of the item, its ``uri`` and its ``list_id``), with
    the labels in a fixed order. It is built from named columns rather than by
    calling that method, so migration 0017 does not depend on columns that a
    later version of arches-controlled-lists may add. An id that is not a UUID,
    or names no item, or an item without labels, is absent from the result.
    """
    from arches_controlled_lists.models import ListItem, ListItemValue

    ids = set()
    for item_id in item_ids:
        try:
            ids.add(str(uuid.UUID(str(item_id))))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}

    labels = {}
    values = ListItemValue.objects.using(using).filter(
        list_item_id__in=ids, valuetype__category="label"
    )
    for value_id, valuetype, language, text, item_id in values.values_list(
        "id", "valuetype_id", "language_id", "value", "list_item_id"
    ):
        labels.setdefault(str(item_id), []).append(
            {
                "id": str(value_id),
                "valuetype_id": valuetype,
                "language_id": language,
                "value": text,
                "list_item_id": str(item_id),
            }
        )

    found = {}
    items = ListItem.objects.using(using).filter(pk__in=ids)
    for item_id, uri, list_id in items.values_list("id", "uri", "list_id"):
        item_labels = labels.get(str(item_id))
        if not item_labels:
            continue
        found[str(item_id)] = {
            "uri": uri or ListItem(id=item_id).generate_uri(),
            "labels": sorted(item_labels, key=_label_order),
            "list_id": str(list_id),
        }
    return found


class TileValueCache:
    """:func:`tile_values` memoised per item id, for one run over many values."""

    def __init__(self, using=DEFAULT_DB_ALIAS):
        self._known = {}
        self._using = using

    def get(self, item_id):
        # tile_values() keys its result by the canonical form of the UUID; a
        # label may hold another spelling of it (upper case, no hyphens).
        try:
            key = str(uuid.UUID(str(item_id)))
        except (TypeError, ValueError):
            return None
        if key not in self._known:
            self._known[key] = tile_values([key], self._using).get(key)
        return self._known[key]


@dataclass
class Completion:
    """What :func:`complete_value` did to one value."""

    #: The value to store: the same object when nothing was replaced.
    value: object
    #: Whether a reference was replaced.
    changed: bool = False
    #: Ids of the list items of incomplete references that could not be
    #: resolved (None for a reference with no label to name its item).
    unresolved: list = field(default_factory=list)
    #: ``{item id: languages}`` still missing after the replacement: the list
    #: item itself has no prefLabel in those languages.
    still_missing: dict = field(default_factory=dict)


def complete_value(value, languages, lookup):
    """Replace each reference of ``value`` that lacks a prefLabel in one of
    ``languages`` by the tile value of its list item (``lookup.get(item id)``).

    ``value`` is a reference value (a list); anything else is returned as is.
    The input is never mutated.
    """
    result = Completion(value=value)
    if not isinstance(value, list):
        return result
    completed = []
    for reference in value:
        if not is_incomplete(reference, languages):
            completed.append(reference)
            continue
        item_id = list_item_id(reference)
        fresh = lookup.get(item_id) if item_id else None
        if fresh is None:
            result.unresolved.append(item_id)
            completed.append(reference)
            continue
        still = missing_languages(fresh, languages)
        if still:
            result.still_missing[item_id] = still
        if fresh != reference:
            result.changed = True
            completed.append(copy.deepcopy(fresh))
        else:
            completed.append(reference)
    if result.changed:
        result.value = completed
    return result


def _reference_defaults(using):
    with connections[using].cursor() as cursor:
        cursor.execute(_DEFAULTS_SQL, [REFERENCE_DATATYPE])
        rows = cursor.fetchall()
    for row_id, default, node_name, graph in rows:
        if isinstance(default, str):  # Django has the driver return jsonb as text
            default = json.loads(default)
        if default:
            yield row_id, default, node_name, graph


def incomplete_defaults(languages=None, using=DEFAULT_DB_ALIAS):
    """``[(graph slug, node name, missing languages)]`` of the reference widget
    defaults (``cards_x_nodes_x_widgets``) lacking a prefLabel in a language."""
    languages = languages or site_languages()
    found = []
    for _row_id, default, node_name, graph in _reference_defaults(using):
        missing = sorted(
            {
                code
                for reference in default
                if isinstance(reference, dict)
                for code in missing_languages(reference, languages)
            },
            key=languages.index,
        )
        if missing:
            found.append((graph, node_name, missing))
    return found


def _complete_serialized_graph(serialized, languages, lookup, report):
    """Complete the reference defaults of one serialized graph, in place.

    The reference nodes are read from the serialized graph itself, as the
    resource editor builds its cards from it. Returns True when one changed.
    """
    if not isinstance(serialized, dict):
        return False
    reference_nodes = {
        str(node.get("nodeid"))
        for node in serialized.get("nodes") or []
        if isinstance(node, dict) and node.get("datatype") == REFERENCE_DATATYPE
    }
    # "widgets" is the key of graphs published before Arches 7.6, which
    # `GraphModel.get_card_x_node_x_widgets` still reads.
    widgets = serialized.get("cards_x_nodes_x_widgets")
    if widgets is None:
        widgets = serialized.get("widgets")
    changed = False
    for widget in widgets or []:
        if not isinstance(widget, dict):
            continue
        if str(widget.get("node_id")) not in reference_nodes:
            continue
        config = widget.get("config")
        if not isinstance(config, dict):
            continue
        completion = complete_value(config.get("defaultValue"), languages, lookup)
        report.add(completion)
        if completion.changed:
            config["defaultValue"] = completion.value
            changed = True
    return changed


@dataclass
class DefaultsReport:
    """What :func:`repair_reference_defaults` found and changed."""

    widget_rows: int = 0
    published_graphs: int = 0
    unresolved: set = field(default_factory=set)
    still_missing: dict = field(default_factory=dict)

    def add(self, completion):
        self.unresolved.update(completion.unresolved)
        self.still_missing.update(completion.still_missing)


def repair_reference_defaults(languages=None, dry_run=False, using=DEFAULT_DB_ALIAS):
    """Complete the default values of the reference widgets from their list items.

    Rewrites, in place and in one transaction:

    - ``config.defaultValue`` of every ``cards_x_nodes_x_widgets`` row of a
      reference node (draft graphs included, so a later publication keeps the
      fix). Only that key changes; the row is updated with SQL so Arches'
      ``post_save`` signal does not flag the graph as having unpublished changes;
    - the same defaults in the ``serialized_graph`` of every language of the
      CURRENT publication of each graph, which is what the resource editor
      reads. No new publication is made: resources keep the publication they
      are pinned to and stay editable (#288, #289). Older publications are
      history and are left alone.

    Idempotent: a complete default is never rewritten, and a default whose list
    item also lacks a language is rewritten once, then equals its replacement.
    """
    from arches.app.models.models import GraphModel, PublishedGraph

    languages = languages or site_languages()
    report = DefaultsReport()
    lookup = TileValueCache(using)
    with transaction.atomic(using=using):
        for row_id, default, _node_name, _graph in list(_reference_defaults(using)):
            completion = complete_value(default, languages, lookup)
            report.add(completion)
            if not completion.changed:
                continue
            report.widget_rows += 1
            if not dry_run:
                with connections[using].cursor() as cursor:
                    cursor.execute(
                        _UPDATE_DEFAULT_SQL, [json.dumps(completion.value), row_id]
                    )

        current = GraphModel.objects.using(using).filter(publication__isnull=False)
        published = (
            PublishedGraph.objects.using(using)
            .filter(publication_id__in=current.values("publication_id"))
            .order_by("pk")
            .values_list("pk", "serialized_graph")
        )
        for pk, serialized in published.iterator(chunk_size=8):
            if not _complete_serialized_graph(serialized, languages, lookup, report):
                continue
            report.published_graphs += 1
            if not dry_run:
                PublishedGraph.objects.using(using).filter(pk=pk).update(
                    serialized_graph=serialized
                )
    return report
