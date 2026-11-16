"""A Document's or Component's summary fields as IIIF ``metadata`` entries.

The fields are those of the summary configuration of the resource's model (the
public « fiche essentielle »), in configuration order.

- The subject's tiles are read from the database (``TileModel``, readable
  nodegroups of the reader only) and shaped as the summary's document
  (``{"tiles": [{"nodegroup_id", "sortorder", "data"}]}``); Elasticsearch is
  not read.
- ``extract_fields`` runs once per code of ``lang.languages()``; its fields are
  merged by ``key``: ``label`` is ``{code: [field label]}`` and ``value`` is
  ``{code: [one string per value]}``. A field whose values are the same
  strings in every language goes under ``none``.
- ``text`` values are the strings ``extract_fields`` gives as plain text
  (``facts.plain_text``: rich text loses its markup); ``date`` and ``chip``
  values are its strings as given; ``number`` values are ``str()`` of the number; a ``link`` value is
  one ``lang.linked`` HTML link to ``ids.report`` per resource the reader may
  see (not hidden, readable model: the ``shown`` rule of ``facts._build``),
  named in the languages of its name map; an ``image`` field yields no entry.
- A model without configuration, or an unknown one, gives ``[]``. Values
  beyond ``max_values`` are not counted.
"""

from arches.app.models.models import ResourceInstance, TileModel

from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.facts import names_of, plain_text
from manuspectrum.utils.public_visibility import (
    hidden_resource_ids,
    readable_graph_ids,
    readable_nodegroup_ids,
)
from manuspectrum.views.summary_service import (
    GraphIndex,
    extract_fields,
    load_summary_config,
)


def _document(resource_id, readable):
    rows = (
        TileModel.objects.filter(
            resourceinstance_id=resource_id, nodegroup_id__in=list(readable)
        )
        .order_by("sortorder", "tileid")
        .values_list("nodegroup_id", "sortorder", "data")
    )
    return {
        "tiles": [
            {"nodegroup_id": str(group), "sortorder": order, "data": data or {}}
            for group, order, data in rows
        ]
    }


def _shown(link_ids, reader):
    hidden = hidden_resource_ids(reader)
    graphs = readable_graph_ids(reader)
    return {
        str(rid)
        for rid, graph_id in ResourceInstance.objects.filter(
            pk__in=list(link_ids)
        ).values_list("resourceinstanceid", "graph_id")
        if str(rid) not in hidden and str(graph_id) in graphs
    }


def _link_values(field_ids, names):
    """One language map: the links of *field_ids* joined per language, in order."""
    merged = {}
    for rid in field_ids:
        for code, texts in lang.linked(names.get(rid) or {}, ids.report(rid)).items():
            merged.setdefault(code, []).extend(texts)
    return merged


def record_metadata(resource_id, graph_id, reader):
    """The summary fields of *resource_id* (a resource of *graph_id*) as IIIF metadata."""
    config = load_summary_config(graph_id)
    index = GraphIndex.for_graph(graph_id)
    if not config or index is None:
        return []
    readable = readable_nodegroup_ids(reader)
    doc = _document(resource_id, readable)
    per_language = {
        code: extract_fields(doc, config, index, code) for code in lang.languages()
    }
    link_ids = []
    for _, found, _ in per_language.values():
        link_ids.extend(i for i in found if i not in link_ids)
    shown = _shown(link_ids, reader) if link_ids else set()
    names = names_of(shown, readable) if shown else {}

    merged = {}
    for code, (fields, _, _) in per_language.items():
        for field in fields:
            if field["style"] == "image":
                continue
            entry = merged.setdefault(
                field["key"], {"style": field["style"], "labels": {}, "values": {}}
            )
            entry["labels"][code] = [field["label"]]
            if field["style"] == "link":
                entry["ids"] = [v["id"] for v in field["values"] if v["id"] in shown]
            elif field["style"] == "number":
                entry["values"][code] = [str(v) for v in field["values"]]
            elif field["style"] == "text":
                entry["values"][code] = [
                    t for t in (plain_text(v) for v in field["values"]) if t
                ]
            else:
                entry["values"][code] = list(field["values"])

    entries = []
    for entry in merged.values():
        if entry["style"] == "link":
            value = _link_values(entry["ids"], names)
        else:
            value = entry["values"]
            distinct = {tuple(v) for v in value.values()}
            if len(value) == len(per_language) and len(distinct) == 1:
                value = {lang.NONE: list(next(iter(distinct)))}
        if value and any(value.values()):
            entries.append({"label": entry["labels"], "value": value})
    return entries
