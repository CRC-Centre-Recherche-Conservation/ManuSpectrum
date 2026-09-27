"""What the IIIF documents of a Document or a Component say, read once and filtered by the reader.

``document_facts`` reads, for one reader, in a fixed number of queries: the
subject (a Document, or a Component and its Document), the source manifest of
the Document (``doc_manifest`` role, through ``sources.manifest_json``), the
analyses observing the subject that ``visible_set(reader).analyses`` keeps
(restrictions and D33 decided there) through a relation nodegroup the reader
may read, and of each analysis the tiles of the nodegroups the reader may
read: its zones (``zones.annotation_features``), every file of every file-list
tile, its name, technique, dates, operators, instrument, conditions, projects,
dataset and imaging manifests. Nothing here depends on the request language:
names and labels are language maps.

Names of resources come from ``resource_instances.descriptors`` (every
language holding a non-empty name), else from their ``label_of_name`` tile
when the reader may read it. People, instruments, projects and dates carry no
stored language and go under ``none``.

A file is kept only when its ``File`` row hangs from the tile that lists it;
nothing is ever read from a path written in tile data. A zone on a canvas the
source manifest does not list leaves its analysis unlocated.
"""

import html
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import nh3
from django.conf import settings
from django.db.models import Q

from arches.app.models.models import File, IIIFManifest, ResourceInstance, TileModel
from arches.app.utils.permission_backend import user_can_read_resource

from manuspectrum.iiif import language as lang
from manuspectrum.iiif.constants import MEDIA_TYPE_BY_EXTENSION, OCTET_STREAM
from manuspectrum.iiif.sources import (
    absolute_url,
    canvas_index,
    canvases_of,
    manifest_json,
)
from manuspectrum.iiif.zones import annotation_features
from manuspectrum.utils.public_visibility import (
    hidden_resource_ids,
    readable_graph_ids,
    readable_nodegroup_ids,
    visible_set,
)
from manuspectrum.utils.role_links import graph_id_of, role_node
from manuspectrum.utils.roles import ROLES
from manuspectrum.views.explorer.values import dataset_of, rewrite_legacy_url
from manuspectrum.views.summary_service import GraphIndex, _date, _resource_id

ANALYSIS_KEYS = (
    "technique",
    "operators",
    "start",
    "end",
    "files",
    "micro",
    "imaging",
    "dataset",
    "statement_type",
    "statement_content",
    "instrument",
    "analysis_by_project",
    "component_observed",
)
FILE_KINDS = (("files", "measurement"), ("micro", "micro-imaging"))
_MEDIA_TYPE = re.compile(r"^[a-z]+/[a-z0-9.+-]+$")
_EMPTY = (None, "", [], {})
_SPACES = re.compile(r"\s+")


class Refused:
    """The resource exists; the reader may not read it."""


REFUSED = Refused()


@dataclass(frozen=True)
class Zone:
    """One located zone: its feature id, canvas id, 1-based canvas position and pixel shape."""

    feature: str
    canvas: str
    position: int
    shape: dict | None


@dataclass(frozen=True)
class FileFact:
    """One file of a file-list tile; *kind* is ``measurement`` or ``micro-imaging``.

    ``entry`` keeps the licence and attribution the tile stores for it.
    """

    id: str
    name: str
    extension: str
    media_type: str
    kind: str
    config_id: str | None
    entry: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisFact:
    id: str
    name: dict
    zones: tuple
    files: tuple
    imaging: tuple
    technique: dict
    dates: dict
    operators: dict
    instrument: dict
    conditions: dict
    projects: dict
    document: dict
    component: dict
    dataset: dict | None
    draft: bool
    materials: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentFacts:
    """The subject (Document or Component), its Document's source manifest and its analyses.

    ``canvases`` and ``canvas_labels`` list the canvases of the source manifest
    in order; page *n* is canvas ``n - 1``.
    """

    document_id: str
    name: dict
    manifest_url: str | None
    canvases: tuple
    canvas_labels: tuple
    analyses: tuple
    characterizations: tuple = ()


def media_type(name, stored):
    """True media type of a file: by extension, else its stored type when it is a plain ``type/subtype``, else octet-stream.

    Raw instrument formats (``RAW_INSTRUMENT_EXTENSIONS``) are octet-stream;
    a ``text/x-*`` type is never trusted.
    """
    extension = os.path.splitext(name or "")[1].lower()
    if extension in MEDIA_TYPE_BY_EXTENSION:
        return MEDIA_TYPE_BY_EXTENSION[extension]
    if extension in {e.lower() for e in settings.RAW_INSTRUMENT_EXTENSIONS}:
        return OCTET_STREAM
    stored = str(stored or "").strip().lower()
    if _MEDIA_TYPE.match(stored) and not stored.startswith("text/x-"):
        return stored
    return OCTET_STREAM


def _tiles(resource_ids, keys, readable):
    """``{rid: {key: [(tile id, value, tile data)]}}`` of the roles *keys*, readable nodegroups only.

    Tiles come in ``sortorder, tileid`` order; empty values are skipped.
    """
    by_group = defaultdict(list)
    for key in keys:
        node = role_node(*ROLES[key])
        if node is not None and node.nodegroup_id in readable:
            by_group[node.nodegroup_id].append((key, node))
    found = defaultdict(lambda: defaultdict(list))
    if not by_group or not resource_ids:
        return found
    rows = (
        TileModel.objects.filter(
            resourceinstance_id__in=list(resource_ids),
            nodegroup_id__in=list(by_group),
        )
        .order_by("sortorder", "tileid")
        .values_list("tileid", "resourceinstance_id", "nodegroup_id", "data")
    )
    for tile_id, rid, nodegroup_id, data in rows:
        data = data or {}
        for key, node in by_group[str(nodegroup_id)]:
            value = data.get(node.nodeid)
            if value not in _EMPTY:
                found[str(rid)][key].append((str(tile_id), value, data))
    return found


def _refs(value):
    """Resource ids of a resource-instance value (one reference or a list)."""
    items = value if isinstance(value, list) else [value]
    return [r for r in (_resource_id(item) for item in items) if r]


def _referencing(key, targets, readable):
    """``(source id, target id)`` of the tiles whose role *key* names one of *targets*.

    Nothing when the role is unresolved or its nodegroup is not readable.
    """
    node = role_node(*ROLES[key])
    if node is None or node.nodegroup_id not in readable or not targets:
        return []
    names = Q()
    for target in targets:
        names |= Q(**{f"data__{node.nodeid}__contains": [{"resourceId": target}]})
        names |= Q(**{f"data__{node.nodeid}__contains": {"resourceId": target}})
    found = []
    for source, value in (
        TileModel.objects.filter(nodegroup_id=node.nodegroup_id)
        .filter(names)
        .values_list("resourceinstance_id", f"data__{node.nodeid}")
    ):
        for target in _refs(value):
            if target in targets:
                found.append((str(source), target))
    return found


def names_of(resource_ids, readable):
    """``{id: language map}`` of the existing resources among *resource_ids*.

    Descriptor names first; a resource without one gives its ``label_of_name``
    values when that nodegroup is readable; else ``{}``.
    """
    ids = [str(i) for i in resource_ids if i]
    found, missing = {}, defaultdict(list)
    for rid, graph_id, descriptors in ResourceInstance.objects.filter(
        pk__in=ids
    ).values_list("resourceinstanceid", "graph_id", "descriptors"):
        names = lang.descriptor_names(descriptors)
        found[str(rid)] = names
        if not names:
            missing[str(graph_id)].append(str(rid))
    for graph_id, rids in missing.items():
        index = GraphIndex.for_graph(graph_id)
        node = index.nodes.get("label_of_name") if index else None
        if node is None or node.nodegroup_id not in readable:
            continue
        for rid, value in (
            TileModel.objects.filter(
                resourceinstance_id__in=rids, nodegroup_id=node.nodegroup_id
            )
            .order_by("sortorder", "tileid")
            .values_list("resourceinstance_id", f"data__{node.nodeid}")
        ):
            if not found[str(rid)]:
                found[str(rid)] = lang.string_map(value)
    return found


def plain_text(markup):
    """Rich text of the Arches editor as one line of plain text."""
    text = html.unescape(nh3.clean(markup or "", tags=set()))
    return _SPACES.sub(" ", text).strip()


def _slug_of(graph_id):
    for slug in ("document", "component", "analysis"):
        if graph_id_of(slug) == str(graph_id):
            return slug
    return None


def _subject(resource_id, reader, visible):
    """``(slug, document id)`` of a Document or Component *reader* may see; None otherwise.

    A Component leads to its first visible Document through a readable link.
    """
    row = (
        ResourceInstance.objects.filter(pk=resource_id)
        .values_list("graph_id", flat=True)
        .first()
    )
    slug = _slug_of(row) if row else None
    rid = str(resource_id)
    if slug == "document" and rid in visible.documents:
        document = rid
    elif slug == "component" and rid in visible.components:
        tiles = _tiles(
            [rid], ["item_visual_is_part_of_document"], readable_nodegroup_ids(reader)
        )
        parents = [
            d
            for _, value, _ in tiles[rid]["item_visual_is_part_of_document"]
            for d in _refs(value)
            if d in visible.documents
        ]
        if not parents:
            return None
        document = parents[0]
    else:
        return None
    if not user_can_read_resource(reader, resourceid=rid):
        return None
    return slug, document


def _analysis_ids(slug, subject, document, visible, readable):
    """Analyses observing *subject* (and, for a Document, its visible Components), visible to the reader."""
    targets = {subject}
    if slug == "document":
        targets |= {
            component
            for component, _ in _referencing(
                "item_visual_is_part_of_document", {document}, readable
            )
            if component in visible.components
        }
    return sorted(
        {
            analysis
            for analysis, _ in _referencing("component_observed", targets, readable)
            if analysis in visible.analyses
        }
    )


def _file_entries(values):
    """``(tile id, kind, entry)`` of every file of every file-list tile read."""
    candidates = []
    for key, kind in FILE_KINDS:
        for tile_id, value, _ in values.get(key, ()):
            for entry in value if isinstance(value, list) else []:
                if isinstance(entry, dict) and entry.get("file_id"):
                    candidates.append((tile_id, kind, entry))
    return candidates


def _one(values):
    """The first text of each language map, joined into one ``none`` string."""
    return lang.none(
        ", ".join(t for t in (lang.first_text(v) for v in values if v) if t)
    )


def _conditions(values):
    maps = []
    type_node = role_node(*ROLES["statement_type"])
    for _, value, data in values.get("statement_content", ()):
        texts = {
            code: plain_text(text[0])
            for code, text in lang.string_map(value).items()
            if plain_text(text[0])
        }
        if not texts:
            continue
        kind = lang.reference_labels(data.get(type_node.nodeid)) if type_node else {}
        if kind:
            texts = {
                code: f"{lang.text_in(kind, code)}: {text}"
                for code, text in texts.items()
            }
        maps.append(lang.from_texts(texts))
    return lang.joined(maps, sep="; ")


def _imaging(values):
    """``(absolute url, label map)`` of each imaging manifest; the label is the stored manifest's, when local."""
    urls = []
    for _, value, _ in values.get("imaging", ()):
        for item in value if isinstance(value, list) else [value]:
            url = rewrite_legacy_url(
                item if isinstance(item, str) else (item or {}).get("url", "")
            )
            if url:
                urls.append(url)
    labels = {}
    paths = {u: urlsplit(u).path for u in urls}
    for url, label in IIIFManifest.objects.filter(
        url__in=[*urls, *paths.values()]
    ).values_list("url", "label"):
        labels[url] = label
    return tuple(
        (
            absolute_url(url) or url,
            lang.none(labels.get(url) or labels.get(paths[url]) or ""),
        )
        for url in urls
    )


def document_facts(resource_id, reader, only=None):
    """``DocumentFacts`` of a Document or Component for *reader*; None when unknown or unreadable.

    *only*, a set of analysis ids, keeps those analyses alone.
    """
    visible = visible_set(reader)
    subject = _subject(resource_id, reader, visible)
    if subject is None:
        return None
    slug, document = subject
    readable = readable_nodegroup_ids(reader)
    analysis_ids = _analysis_ids(slug, str(resource_id), document, visible, readable)
    if only is not None:
        analysis_ids = [a for a in analysis_ids if a in only]
    return _build(str(resource_id), document, analysis_ids, reader, visible, readable)


def subject_of(resource_id, reader):
    """``(slug, document id)`` of a Document or Component *reader* may see; None otherwise."""
    return _subject(resource_id, reader, visible_set(reader))


def analysis_access(analysis_id, reader):
    """``(observed object id, (slug, document id))`` of an analysis *reader* may read.

    None when *analysis_id* is not an analysis; ``REFUSED`` when the reader
    may not read it (outside ``visible_set(reader).analyses``, or refused by
    ``user_can_read_resource``), or when none of its observed objects leads
    the reader to a visible Document.
    """
    graph_id = (
        ResourceInstance.objects.filter(pk=analysis_id)
        .values_list("graph_id", flat=True)
        .first()
    )
    if graph_id is None or _slug_of(graph_id) != "analysis":
        return None
    visible = visible_set(reader)
    aid = str(analysis_id)
    if aid not in visible.analyses or not user_can_read_resource(
        reader, resourceid=aid
    ):
        return REFUSED
    readable = readable_nodegroup_ids(reader)
    for _, value, _ in _tiles([aid], ["component_observed"], readable)[aid][
        "component_observed"
    ]:
        for target in _refs(value):
            subject = _subject(target, reader, visible)
            if subject is not None:
                return target, subject
    return REFUSED


def analysis_fact(analysis_id, reader):
    """``(DocumentFacts, AnalysisFact)`` of one analysis; None when unknown, ``REFUSED`` when unreadable (``analysis_access``).

    The document facts are those of the first observed object leading to a
    visible Document.
    """
    access = analysis_access(analysis_id, reader)
    if access is None or access is REFUSED:
        return access
    target, (_, document) = access
    visible = visible_set(reader)
    readable = readable_nodegroup_ids(reader)
    doc = _build(target, document, [str(analysis_id)], reader, visible, readable)
    return doc, doc.analyses[0]


def _build(subject_id, document, analysis_ids, reader, visible, readable):
    doc_tiles = _tiles([document], ["doc_manifest"], readable)[document]
    url = next(
        (
            rewrite_legacy_url(v if isinstance(v, str) else (v or {}).get("url", ""))
            for _, v, _ in doc_tiles.get("doc_manifest", ())
        ),
        "",
    )
    listed = canvases_of(manifest_json(url)) if url else []
    position = {c["id"]: n for n, c in enumerate(listed, start=1)}
    dims = canvas_index(listed)

    zones = defaultdict(list)
    for rid, feature, canvas, shape in annotation_features(
        role_node(*ROLES["zone"]), analysis_ids, dims, readable
    ):
        if canvas in position:
            zones[rid].append(Zone(str(feature), canvas, position[canvas], shape))

    values = _tiles(analysis_ids, ANALYSIS_KEYS, readable)
    candidates = {
        aid: _file_entries(values[aid]) for aid in analysis_ids if aid in values
    }
    owners = dict(
        File.objects.filter(
            fileid__in=[e["file_id"] for c in candidates.values() for _, _, e in c]
        ).values_list("fileid", "tile_id")
    )
    owners = {str(k): str(v) for k, v in owners.items() if v}

    hidden = hidden_resource_ids(reader)
    graphs = readable_graph_ids(reader)
    people = set()
    for aid in analysis_ids:
        for key in (
            "operators",
            "instrument",
            "analysis_by_project",
            "component_observed",
        ):
            for _, value, _ in values[aid].get(key, ()):
                people.update(_refs(value))
    shown = {
        str(rid)
        for rid, graph_id in ResourceInstance.objects.filter(
            pk__in=list(people | {subject_id, document})
        ).values_list("resourceinstanceid", "graph_id")
        if str(rid) not in hidden and str(graph_id) in graphs
    }
    name_of = names_of(shown | set(analysis_ids), readable)

    analyses = []
    for aid in analysis_ids:
        v = values[aid]
        files = []
        for tile_id, kind, entry in candidates.get(aid, ()):
            file_id = str(entry["file_id"])
            if owners.get(file_id) != tile_id:
                continue
            name = str(entry.get("name") or "")
            files.append(
                FileFact(
                    id=file_id,
                    name=name,
                    extension=os.path.splitext(name)[1].lower(),
                    media_type=media_type(name, entry.get("type")),
                    kind=kind,
                    config_id=entry.get("rendererConfig") or None,
                    entry={
                        k: entry[k] for k in ("license", "attribution") if k in entry
                    },
                )
            )

        def refs(key, keep=lambda r: r in shown):
            return [
                r for _, value, _ in v.get(key, ()) for r in _refs(value) if keep(r)
            ]

        observed = refs("component_observed")
        start = next(
            (_date(x) for _, x, _ in v.get("start", ()) if isinstance(x, str)), ""
        )
        end = next((_date(x) for _, x, _ in v.get("end", ()) if isinstance(x, str)), "")
        dataset = next(
            (dataset_of(x) for _, x, _ in v.get("dataset", ()) if dataset_of(x)), None
        )
        analyses.append(
            AnalysisFact(
                id=aid,
                name=name_of.get(aid, {}),
                zones=tuple(sorted(zones.get(aid, ()), key=lambda z: z.feature)),
                files=tuple(files),
                imaging=_imaging(v),
                technique=lang.joined(
                    lang.reference_labels(x) for _, x, _ in v.get("technique", ())
                ),
                dates=lang.none(
                    " – ".join(dict.fromkeys(d for d in (start, end) if d))
                ),
                operators=_one([name_of.get(r, {}) for r in refs("operators")]),
                instrument=_one([name_of.get(r, {}) for r in refs("instrument")]),
                conditions=_conditions(v),
                projects=_one(
                    [
                        name_of.get(r, {})
                        for r in refs(
                            "analysis_by_project",
                            lambda r: r in shown and r in visible.projects,
                        )
                    ]
                ),
                document=name_of.get(document, {}),
                component=lang.joined(
                    name_of.get(r, {}) for r in observed if r in visible.components
                ),
                dataset=dataset,
                draft=aid in visible.unpublished,
            )
        )
    return DocumentFacts(
        document_id=subject_id,
        name=name_of.get(subject_id, {}),
        manifest_url=(absolute_url(url) or url) if url else None,
        canvases=tuple(c["id"] for c in listed),
        canvas_labels=tuple(c["label"] for c in listed),
        analyses=tuple(analyses),
    )
