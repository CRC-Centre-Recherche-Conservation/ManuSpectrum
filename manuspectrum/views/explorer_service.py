"""Payloads of the Explorer's Corpus APIs (spec §5), built from ``visible_set``.

Every function takes the reader and the request language; nothing is memoised
in v1. Values are read off the tiles of the nodegroups the reader may read,
links off the tiles by role (D6), and a resource outside ``visible_set`` never
reaches a payload, a facet or a name.
"""

import logging
import re
import sys
import unicodedata
from collections import Counter, defaultdict

from django.conf import settings
from django.http import QueryDict
from django.urls import reverse

from arches.app.models.models import (
    IIIFManifest,
    ResourceInstance,
    TileModel,
    VwAnnotation,
)
from arches_controlled_lists.models import ListItem, ListItemValue

from manuspectrum.constants.licenses import effective_license
from manuspectrum.models import RendererConfig
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.utils.public_visibility import (
    hidden_resource_ids,
    readable_graph_ids,
    readable_nodegroup_ids,
    visible_set,
)
from manuspectrum.utils.role_links import readable_links, role_node
from manuspectrum.views.explorer_conditions import clean_html, conditions_of
from manuspectrum.views.explorer_values import (
    dataset_of,
    file_entries,
    label,
    name_of,
    reference_terms,
    rewrite_legacy_url,
    shape_of,
    string_texts,
    value_refs,
)
from manuspectrum.views.summary_service import GraphIndex, _date

ROLES = {
    "doc_name": ("document", "label_of_name"),
    "doc_manifest": ("document", "facsimiles"),
    "doc_owner": ("document", "current_owner"),
    "comp_zone": ("component", "location_in_document"),
    "an_name": ("analysis", "label_of_name"),
    "technique": ("analysis", "analysis_technique_used"),
    "operators": ("analysis", "performed_by_actor"),
    "start": ("analysis", "analysis_start_date"),
    "end": ("analysis", "analysis_end_date"),
    "files": ("analysis", "measurement_point_data"),
    "micro": ("analysis", "micro_macro_imaging"),
    "imaging": ("analysis", "chemical_imaging_manifest"),
    "zone": ("analysis", "literal_location_of_analysis"),
    "dataset": ("analysis", "dataset_url"),
    "bibliography": ("analysis", "bibliographic_title"),
    "statement_type": ("analysis", "type_of_statement"),
    "statement_content": ("analysis", "content_of_statement"),
    "instrument": ("analysis", "instrument"),
    "material": ("characterization", "identified_material"),
    "confidence": ("characterization", "material_confidence"),
    "colour": ("characterization", "color_aspect"),
    "layer": ("characterization", "layer_type"),
    "elements": ("characterization", "detected_elements"),
    "element_level": ("characterization", "element_level"),
    "ch_zone": ("characterization", "location_of_characterization"),
    "ch_note": ("characterization", "inference_making"),
    "ch_authors": ("characterization", "authors_of_inference"),
    "ch_start": ("characterization", "inference_making_start_date"),
    "ch_end": ("characterization", "inference_making_end_date"),
    "ch_source": ("characterization", "source_of_statement"),
}
FACET_KEYS = (
    "project",
    "technique",
    "part",
    "operator",
    "year",
    "colour",
    "material",
    "element",
    "layer",
)
_EMPTY = (None, "", [], {})

logger = logging.getLogger(__name__)


class Values:
    """Tile values of *resource_ids* for the roles *keys*, from readable nodegroups only.

    ``get`` flattens list values except references, whose list is one value;
    ``tiles`` keeps each tile's data for the roles read tile by tile
    (statements, material with its certainty). A role whose node is not
    resolved logs a warning and reads as empty.
    """

    def __init__(self, resource_ids, keys, user):
        nodes = {key: role_node(*ROLES[key]) for key in keys}
        for key, node in nodes.items():
            if node is None:
                logger.warning("explorer: role %s.%s is not resolved", *ROLES[key])
        self._nodes = {key: node for key, node in nodes.items() if node is not None}
        readable = readable_nodegroup_ids(user)
        by_group = defaultdict(list)
        for key, node in self._nodes.items():
            if node.nodegroup_id in readable:
                by_group[node.nodegroup_id].append((key, node))
        self._values = defaultdict(lambda: defaultdict(list))
        self._tiles = defaultdict(lambda: defaultdict(list))
        ids = [str(r) for r in resource_ids]
        if not ids or not by_group:
            return
        rows = (
            TileModel.objects.filter(
                resourceinstance_id__in=ids, nodegroup_id__in=list(by_group)
            )
            .order_by("sortorder", "tileid")
            .values_list("resourceinstance_id", "nodegroup_id", "data")
        )
        for rid, nodegroup_id, data in rows:
            rid, data = str(rid), data or {}
            for key, node in by_group.get(str(nodegroup_id), []):
                self._tiles[rid][key].append(data)
                raw = data.get(node.nodeid)
                if raw in _EMPTY:
                    continue
                if isinstance(raw, list) and node.datatype != "reference":
                    self._values[rid][key].extend(v for v in raw if v not in _EMPTY)
                else:
                    self._values[rid][key].append(raw)

    def node(self, key):
        return self._nodes.get(key)

    def get(self, rid, key):
        return self._values[str(rid)][key]

    def first(self, rid, key):
        values = self.get(rid, key)
        return values[0] if values else None

    def tiles(self, rid, key):
        return self._tiles[str(rid)][key]


def fold(text):
    """*text* without accents, casefolded, for free-text matching."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def names(resource_ids, language, user):
    """``{id: Label}`` of the existing resources among *resource_ids*, of any model.

    The name is read off ``label_of_name`` when its nodegroup is readable by
    *user*, else it is the ``name_of`` placeholder. An id without a resource
    is left out.
    """
    readable = readable_nodegroup_ids(user)
    by_graph = defaultdict(list)
    for rid, graph_id in ResourceInstance.objects.filter(
        pk__in=[str(i) for i in resource_ids]
    ).values_list("resourceinstanceid", "graph_id"):
        by_graph[str(graph_id)].append(str(rid))
    found = {}
    for graph_id, rids in by_graph.items():
        index = GraphIndex.for_graph(graph_id)
        node = index.nodes.get("label_of_name") if index else None
        values = defaultdict(list)
        if node and node.nodegroup_id in readable:
            for rid, value in (
                TileModel.objects.filter(
                    resourceinstance_id__in=rids, nodegroup_id=node.nodegroup_id
                )
                .order_by("sortorder", "tileid")
                .values_list("resourceinstance_id", f"data__{node.nodeid}")
            ):
                if value not in _EMPTY:
                    values[str(rid)].append(value)
        for rid in rids:
            found[rid] = name_of(
                values[rid], index.name if index else {}, rid, language
            )
    return found


def linkable(resource_ids, user):
    """The ids among *resource_ids* a linked reference may show, sorted.

    A kept id names an existing resource, outside ``hidden_resource_ids`` and
    of a model in ``readable_graph_ids``.
    """
    hidden = hidden_resource_ids(user)
    graphs = readable_graph_ids(user)
    wanted = {str(i) for i in resource_ids if i} - hidden
    if not wanted:
        return []
    return sorted(
        str(rid)
        for rid, graph_id in ResourceInstance.objects.filter(
            pk__in=list(wanted)
        ).values_list("resourceinstanceid", "graph_id")
        if str(graph_id) in graphs
    )


def _resource_refs(values):
    return {
        str(v.get("resourceId"))
        for v in values
        if isinstance(v, dict) and v.get("resourceId")
    }


def model_of(resource_ids):
    """``{id: model slug}``."""
    return {
        str(rid): GraphIndex.slug_of(graph_id) or ""
        for rid, graph_id in ResourceInstance.objects.filter(
            pk__in=[str(i) for i in resource_ids]
        ).values_list("resourceinstanceid", "graph_id")
    }


def ancestor_terms(item_ids):
    """``{item id: labels of its ancestors}``: a parent term found by free text brings its children (« XRF » → pXRF)."""
    parent_of, frontier = {}, {str(i) for i in item_ids}
    for _ in range(8):
        if not frontier:
            break
        rows = dict(
            (str(i), str(p) if p else None)
            for i, p in ListItem.objects.filter(pk__in=list(frontier)).values_list(
                "id", "parent_id"
            )
        )
        parent_of.update(rows)
        frontier = {p for p in rows.values() if p and p not in parent_of}
    ancestors = {}
    for item in item_ids:
        chain, current = [], parent_of.get(str(item))
        while current and current not in chain:
            chain.append(current)
            current = parent_of.get(current)
        ancestors[str(item)] = chain
    labels = defaultdict(set)
    wanted = {a for chain in ancestors.values() for a in chain}
    for item, value in ListItemValue.objects.filter(
        list_item_id__in=list(wanted), valuetype_id__in=("prefLabel", "altLabel")
    ).values_list("list_item_id", "value"):
        labels[str(item)].add(value)
    return {
        item: set().union(*(labels[a] for a in chain)) if chain else set()
        for item, chain in ancestors.items()
    }


_links = readable_links


def structure(visible, user):
    """``{analysis id: (document id, component id or None)}`` along the first visible chain, sorted."""
    readable = readable_nodegroup_ids(user)
    part_of = _links("component", "item_visual_is_part_of_document", readable)
    observed = _links("analysis", "component_observed", readable)
    found = {}
    for analysis in visible.analyses:
        for target in sorted(observed[analysis]):
            if target in visible.documents:
                found[analysis] = (target, None)
                break
            if target in visible.components:
                documents = sorted(d for d in part_of[target] if d in visible.documents)
                if documents:
                    found[analysis] = (documents[0], target)
                    break
    return found


def _canvas_of(annotation):
    for feature in (annotation or {}).get("features") or []:
        canvas = (feature.get("properties") or {}).get("canvas")
        if canvas:
            return canvas
    return None


def corpus_rows(user, language, chains=None):
    """One row per visible analysis: what search filters, counts and lists.

    *chains* skips a repeat of ``structure()`` when the caller already has it.
    """
    visible = visible_set(user)
    if chains is None:
        chains = structure(visible, user)
    analyses = sorted(chains)
    values = Values(
        analyses,
        [
            "an_name",
            "technique",
            "operators",
            "start",
            "files",
            "micro",
            "imaging",
            "zone",
        ],
        user,
    )
    readable = readable_nodegroup_ids(user)
    projects_of = _links("analysis", "analysis_by_project", readable)
    characterizations = Values(
        visible.characterizations, ["material", "colour", "layer", "elements"], user
    )
    cited_by = defaultdict(list)
    for characterization, evidence in visible.evidence.items():
        for analysis in evidence:
            cited_by[analysis].append(characterization)
    operators_of = {a: _resource_refs(values.get(a, "operators")) for a in analyses}
    shown_operators = set(
        linkable({o for ops in operators_of.values() for o in ops}, user)
    )
    analysis_index = GraphIndex.for_slug("analysis")
    analysis_model = analysis_index.name if analysis_index else {}
    technique_ids = {
        ref["id"]
        for a in analyses
        for ref in value_refs(values.first(a, "technique"), language)
    }
    ancestors = ancestor_terms(technique_ids)
    related = {d for d, _ in chains.values()} | {c for _, c in chains.values() if c}
    label_of = names(related, language, user)
    rows = []
    for a in analyses:
        document, component = chains[a]
        technique_value = values.first(a, "technique")
        techniques = value_refs(technique_value, language)
        technique = techniques[0] if techniques else None
        cited = sorted(cited_by[a])

        def refs_of(key):
            return [
                ref
                for c in cited
                for v in characterizations.get(c, key)
                for ref in value_refs(v, language)
            ]

        materials, colours = refs_of("material"), refs_of("colour")
        start = values.first(a, "start")
        date = _date(start) if isinstance(start, str) else None
        kinds = []
        if any(
            e.get("rendererConfig")
            for e in values.get(a, "files")
            if isinstance(e, dict)
        ):
            kinds.append("xy")
        if values.get(a, "imaging"):
            kinds.append("chemical-imaging")
        if values.get(a, "micro"):
            kinds.append("micro-imaging")
        if values.get(a, "files") and "xy" not in kinds:
            kinds.append("file")
        name = name_of(values.get(a, "an_name"), analysis_model, a, language)
        texts = [t for v in values.get(a, "an_name") for t in string_texts(v).values()]
        texts += [label_of[document]["value"]] + (
            [label_of[component]["value"]] if component else []
        )
        if technique:
            texts += list(reference_terms(technique_value)) + list(
                ancestors.get(technique["id"], ())
            )
        texts += [
            t
            for c in cited
            for key in ("material", "colour")
            for v in characterizations.get(c, key)
            for t in reference_terms(v)
        ]
        rows.append(
            {
                "id": a,
                "name": name,
                "technique": technique,
                "document": document,
                "component": component,
                "canvas": rewrite_legacy_url(_canvas_of(values.first(a, "zone")) or "")
                or None,
                "date": date,
                "year": int(date[:4]) if date and date[:4].isdigit() else None,
                "projects": sorted(p for p in projects_of[a] if p in visible.projects),
                "operators": sorted(operators_of[a] & shown_operators),
                "materials": _unique(materials),
                "colours": _unique(colours),
                "layers": _unique(refs_of("layer")),
                "elements": _unique(refs_of("elements")),
                "dataKinds": kinds,
                "unpublished": a in visible.unpublished,
                "text": fold(" ".join(texts)),
            }
        )
    return rows


def _unique(refs):
    seen, kept = set(), []
    for ref in refs:
        if ref["uri"] not in seen:
            seen.add(ref["uri"])
            kept.append(ref)
    return kept


def parse_filters(query):
    """Filters and page number of a search query; lists come as repeated or comma-separated parameters."""
    filters = {
        key: sorted(
            {
                v.strip()
                for raw in query.getlist(key)
                for v in raw.split(",")
                if v.strip()
            }
        )
        for key in FACET_KEYS
    }
    filters["q"] = query.get("q", "").strip()
    filters["grain"] = "documents" if query.get("grain") == "documents" else "analyses"
    filters["onlyWithAnalyses"] = query.get("onlyWithAnalyses", "true").lower() not in (
        "0",
        "false",
        "no",
    )
    try:
        page = max(1, int(query.get("page", "1")))
    except ValueError:
        page = 1
    return filters, page


def _facet_values(row, key):
    if key == "technique":
        return [row["technique"]["uri"]] if row["technique"] else []
    if key == "part":
        return [row["component"]] if row["component"] else []
    if key == "year":
        return [str(row["year"])] if row["year"] else []
    if key in ("project", "operator"):
        return row[f"{key}s"]
    plural = {
        "material": "materials",
        "colour": "colours",
        "element": "elements",
        "layer": "layers",
    }[key]
    return [ref["uri"] for ref in row[plural]]


def _facet_labels(rows, language, user):
    labels = defaultdict(dict)
    for row in rows:
        if row["technique"]:
            labels["technique"][row["technique"]["uri"]] = row["technique"]["label"]
        for key, plural in (
            ("material", "materials"),
            ("colour", "colours"),
            ("element", "elements"),
            ("layer", "layers"),
        ):
            for ref in row[plural]:
                labels[key][ref["uri"]] = ref["label"]
        if row["year"]:
            labels["year"][str(row["year"])] = {
                "value": str(row["year"]),
                "lang": language,
            }
    ids = {
        v
        for row in rows
        for key in ("part", "project", "operator")
        for v in _facet_values(row, key)
    }
    named = names(ids, language, user)
    for row in rows:
        for key in ("part", "project", "operator"):
            for v in _facet_values(row, key):
                labels[key][v] = named.get(v, {"value": v[:8], "lang": language})
    return labels


def _ref(resource_id, model, label_of):
    return {"id": resource_id, "model": model, "name": label_of[resource_id]}


def analysis_hit(row, label_of):
    return {
        "type": "analysis",
        "id": row["id"],
        "name": row["name"],
        "technique": row["technique"],
        "document": _ref(row["document"], "document", label_of),
        "component": (
            _ref(row["component"], "component", label_of) if row["component"] else None
        ),
        "canvas": row["canvas"],
        "date": row["date"],
        "dataKinds": row["dataKinds"],
        "materials": row["materials"],
        "unpublished": row["unpublished"],
    }


def row_filter(rows, query):
    """The Corpus filter rule over *rows*: ``(keep, active, filters, page, needle, universe)``.

    ``keep(row, skip=None)`` is OR inside a facet and AND across facets, and
    the folded free text ``needle``; ``skip`` leaves one facet out (open facet
    counts). ``universe`` holds, per facet, the values the rows carry; a
    selected value outside it is ignored (§3.3).
    """
    filters, page = parse_filters(query)
    universe = {
        key: {v for row in rows for v in _facet_values(row, key)} for key in FACET_KEYS
    }
    active = {
        key: [v for v in filters[key] if v in universe[key]] for key in FACET_KEYS
    }
    needle = fold(filters["q"])

    def keep(row, skip=None):
        for key in FACET_KEYS:
            if (
                key != skip
                and active[key]
                and not set(_facet_values(row, key)) & set(active[key])
            ):
                return False
        return not needle or needle in row["text"]

    return keep, active, filters, page, needle, universe


def search_payload(query, user, language):
    """``SearchResponse`` (spec §5): results of one page, open facet counts, unpublished count.

    Facet counts are "open to the other selections": OR inside a facet, AND
    across facets. A facet is absent when no value has a count on the whole
    visible set; a selected value that is not in the visible set is ignored
    without a word.
    """
    rows = corpus_rows(user, language)
    keep, active, filters, page, needle, universe = row_filter(rows, query)

    matching = [row for row in rows if keep(row)]
    labels = _facet_labels(rows, language, user)
    facets = []
    for key in FACET_KEYS:
        if not universe[key]:
            continue
        counts = Counter(
            v for row in rows if keep(row, key) for v in set(_facet_values(row, key))
        )
        values = [
            {
                "id": v,
                "label": labels[key][v],
                "count": counts[v],
                "selected": v in active[key],
            }
            for v in universe[key]
            if counts[v] > 0 or v in active[key]
        ]
        values.sort(
            key=(
                (lambda item: item["id"])
                if key == "year"
                else (lambda item: (fold(item["label"]["value"]), item["id"]))
            )
        )
        facets.append({"key": key, "values": values})

    visible = visible_set(user)
    label_of = names(
        {r["document"] for r in rows}
        | {r["component"] for r in rows if r["component"]}
        | visible.documents,
        language,
        user,
    )
    if filters["grain"] == "documents":
        per_document = Counter(row["document"] for row in matching)
        candidates = sorted(
            visible.documents, key=lambda d: (fold(label_of[d]["value"]), d)
        )
        results = [
            {
                "type": "document",
                "id": d,
                "name": label_of[d],
                "holding": None,
                "analysisCount": per_document[d],
                "thumbnail": reverse("thumbnail", kwargs={"resource_id": d}),
                "unpublished": d in visible.unpublished,
            }
            for d in candidates
            if per_document[d] > 0
            or (
                not filters["onlyWithAnalyses"]
                and (not needle or needle in fold(label_of[d]["value"]))
            )
        ]
    else:
        matching.sort(
            key=lambda r: (
                fold(label_of[r["document"]]["value"]),
                r["component"] or "",
                fold(r["name"]["value"]),
                r["id"],
            )
        )
        results = [analysis_hit(row, label_of) for row in matching]
    size = settings.EXPLORER_SEARCH_PAGE_SIZE
    chunk = results[(page - 1) * size : page * size]
    return {
        "total": len(results),
        "page": {"number": page, "size": size, "count": len(chunk)},
        "results": chunk,
        "facets": facets,
        "unpublishedCount": sum(1 for r in results if r["unpublished"]),
    }


_LOCAL_MANIFEST = re.compile(r"/manifest/(?P<uuid>[0-9a-fA-F-]{36})/?$")


def manifest_json(url):
    """Manifest JSON of *url*: a local ``/manifest/<uuid>`` is read from ``IIIFManifest`` in the database, never over HTTP."""
    url = rewrite_legacy_url(url or "")
    if not url:
        return None
    match = _LOCAL_MANIFEST.search(url)
    if match and (
        url.startswith("/") or url.startswith(settings.PUBLIC_SERVER_ADDRESS)
    ):
        stored = (
            IIIFManifest.objects.filter(globalid=match["uuid"])
            .values_list("manifest", flat=True)
            .first()
        )
        return stored if isinstance(stored, dict) else None
    return CanvasIIIF.fetch_manifest(url)


def _canvas_label(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for texts in value.values():
            if isinstance(texts, list) and texts:
                return str(texts[0])
    return ""


def canvases_of(manifest):
    """``{"id", "label", "image"}`` of every canvas of a v2 or v3 manifest; legacy hosts rewritten."""
    if not isinstance(manifest, dict):
        return []
    version = CanvasIIIF.detect_version(manifest)
    if version == 3:
        raw = manifest.get("items") or []
    else:
        raw = ((manifest.get("sequences") or [{}])[0] or {}).get("canvases") or []
    found = []
    for canvas in raw:
        canvas_id = canvas.get("id") or canvas.get("@id")
        if not canvas_id:
            continue
        service = (
            CanvasIIIF._get_image_service_url_v3(canvas)
            if version == 3
            else CanvasIIIF._get_image_service_url_v2(canvas)
        )
        width, height = CanvasIIIF.get_canvas_dimensions(canvas)
        found.append(
            {
                "id": rewrite_legacy_url(canvas_id),
                "label": _canvas_label(canvas.get("label")),
                "image": {
                    "service": rewrite_legacy_url(service) if service else None,
                    "url": None,
                    "width": int(width),
                    "height": int(height),
                },
            }
        )
    return found


def _ranks(item_ids):
    return {
        str(i): int(order or 0)
        for i, order in ListItem.objects.filter(
            pk__in=[i for i in item_ids if i]
        ).values_list("id", "sortorder")
    }


def certainty_scale(language):
    """The levels of the certainty list of identified materials, by ``sortorder`` (rank 0 = most certain)."""
    index = GraphIndex.for_slug("characterization")
    list_id = index.lists.get("material_confidence") if index else None
    if not list_id:
        return {"levels": []}
    items = list(
        ListItem.objects.filter(list_id=list_id)
        .order_by("sortorder")
        .values_list("id", "uri", "sortorder")
    )
    texts = defaultdict(dict)
    for item, lang, value in ListItemValue.objects.filter(
        list_item_id__in=[i for i, _, _ in items], valuetype_id="prefLabel"
    ).values_list("list_item_id", "language_id", "value"):
        texts[str(item)][lang] = value
    return {
        "levels": [
            {
                "id": str(i),
                "uri": uri or "",
                "label": label(texts[str(i)], language)
                or {"value": uri or "", "lang": language},
                "rank": int(order or 0),
            }
            for i, uri, order in items
        ]
    }


def canvas_index(canvases):
    """``{name: (canvas id, width, height)}`` of each canvas, by its id and by its image service.

    Arches' IIIF viewer stores an annotation under the image service it drew
    (the tile layer's URL), not under the manifest's canvas id; both names
    lead to the canvas.
    """
    index = {}
    for canvas in canvases:
        entry = (canvas["id"], canvas["image"]["width"], canvas["image"]["height"])
        index[canvas["id"].rstrip("/")] = entry
        if canvas["image"]["service"]:
            index[canvas["image"]["service"].rstrip("/")] = entry
    return index


def _canvas_and_shape(vw, dims):
    """Canvas id and pixel ``Shape`` of one ``VwAnnotation`` row; canvas empty and shape None when unresolved.

    *dims* is a ``canvas_index``: the stored name (canvas id or image service)
    becomes the manifest's canvas id. A canvas missing from it keeps its
    stored name and is not clamped to any size, so a zone has the same
    coordinates whether its canvas dimensions are known or not.
    """
    feature = vw.feature or {}
    stored = rewrite_legacy_url(
        vw.canvas or (feature.get("properties") or {}).get("canvas") or ""
    )
    canvas, width, height = dims.get(stored.rstrip("/")) or (
        stored,
        sys.maxsize,
        sys.maxsize,
    )
    shape = shape_of(feature.get("geometry"), width, height)
    return canvas, shape


def _annotations(node, resource_ids, dims, readable):
    """``(resource id, feature id, canvas, shape)`` of every resolved annotation feature of *node*, by feature id.

    Nothing when the node is unresolved or its nodegroup is not in *readable*.
    """
    if node is None or node.nodegroup_id not in readable:
        return
    for vw in VwAnnotation.objects.filter(
        resourceinstance_id__in=list(resource_ids), node_id=node.nodeid
    ).order_by("feature_id"):
        canvas, shape = _canvas_and_shape(vw, dims)
        if canvas and shape:
            yield str(vw.resourceinstance_id), vw.feature_id, canvas, shape


def _zone(node, resource_ids, dims, readable):
    """``{resource id: {"canvas", "shape"}}`` from the first annotation feature of *node*; ``{}`` when its nodegroup is not in *readable*."""
    zones = {}
    for rid, _, canvas, shape in _annotations(node, resource_ids, dims, readable):
        zones.setdefault(rid, {"canvas": canvas, "shape": shape})
    return zones


def characterization_summaries(ids, visible, user, language, dims):
    """``CharacterizationSummary`` of the visible identified materials among *ids*."""
    ids = sorted(i for i in ids if i in visible.characterizations)
    if not ids:
        return []
    keys = [
        "material",
        "confidence",
        "colour",
        "layer",
        "elements",
        "element_level",
        "ch_note",
        "ch_authors",
        "ch_start",
        "ch_end",
        "ch_source",
    ]
    values = Values(ids, keys, user)
    readable = readable_nodegroup_ids(user)
    objects_of = _links("characterization", "object_observed", readable)
    objects = {
        c: sorted(
            o for o in objects_of[c] if o in visible.documents | visible.components
        )
        for c in ids
    }
    authors_of = {c: _resource_refs(values.get(c, "ch_authors")) for c in ids}
    shown_authors = set(linkable({a for v in authors_of.values() for a in v}, user))
    authors = {c: sorted(authors_of[c] & shown_authors) for c in ids}
    label_of = names(
        set(ids)
        | {o for v in objects.values() for o in v}
        | {a for v in authors.values() for a in v},
        language,
        user,
    )
    slug_of = model_of(
        {o for v in objects.values() for o in v}
        | {a for v in authors.values() for a in v}
    )
    own_zone = _zone(role_node(*ROLES["ch_zone"]), ids, dims, readable)
    component_zone = _zone(
        role_node(*ROLES["comp_zone"]),
        {o for v in objects.values() for o in v},
        dims,
        readable,
    )
    material_node, confidence_node = values.node("material"), values.node("confidence")
    element_node, level_node = values.node("elements"), values.node("element_level")
    rank_ids = set()
    for c in ids:
        for data in values.tiles(c, "material") + values.tiles(c, "elements"):
            for node in (confidence_node, level_node):
                if node:
                    rank_ids |= {
                        r["id"] for r in value_refs(data.get(node.nodeid), language)
                    }
    ranks = _ranks(rank_ids)
    ranked = lambda refs: (
        {**refs[0], "rank": ranks.get(refs[0]["id"], 0)} if refs else None
    )
    summaries = []
    for c in ids:
        materials = []
        for data in values.tiles(c, "material"):
            for ref in value_refs(
                data.get(material_node.nodeid) if material_node else None, language
            ):
                confidence = (
                    value_refs(data.get(confidence_node.nodeid), language)
                    if confidence_node
                    else []
                )
                materials.append(
                    {"value": ref, "confidence": ranked(confidence), "proportion": None}
                )
        elements = []
        for data in values.tiles(c, "elements"):
            found = (
                value_refs(data.get(element_node.nodeid), language)
                if element_node
                else []
            )
            if found:
                level = (
                    value_refs(data.get(level_node.nodeid), language)
                    if level_node
                    else []
                )
                elements.append({"level": ranked(level), "values": found})
        if c in own_zone:
            zone = {**own_zone[c], "source": "own"}
        else:
            first = next((o for o in objects[c] if o in component_zone), None)
            zone = {**component_zone[first], "source": "component"} if first else None
        note_value = values.first(c, "ch_note")
        note_text = label(string_texts(note_value), language) if note_value else None
        start, end = values.first(c, "ch_start"), values.first(c, "ch_end")
        summaries.append(
            {
                "id": c,
                "name": label_of[c],
                "objects": [
                    {"id": o, "model": slug_of.get(o, ""), "name": label_of[o]}
                    for o in objects[c]
                ],
                "materials": materials,
                "colours": _unique(
                    [
                        r
                        for v in values.get(c, "colour")
                        for r in value_refs(v, language)
                    ]
                ),
                "layers": _unique(
                    [r for v in values.get(c, "layer") for r in value_refs(v, language)]
                ),
                "elements": elements,
                "zone": zone,
                "evidence": list(visible.evidence.get(c, ())),
                "note": (
                    {"html": clean_html(note_text["value"]), "lang": note_text["lang"]}
                    if note_text
                    else None
                ),
                "sources": [
                    {
                        "title": (
                            {"value": d["label"], "lang": language}
                            if d["label"]
                            else None
                        ),
                        "url": d["url"],
                        "ref": None,
                    }
                    for d in (dataset_of(v) for v in values.get(c, "ch_source"))
                    if d
                ],
                "authors": [
                    {"id": a, "model": slug_of.get(a, ""), "name": label_of[a]}
                    for a in authors[c]
                ],
                "date": {
                    "start": _date(start) if isinstance(start, str) else None,
                    "end": _date(end) if isinstance(end, str) else None,
                },
                "unpublished": c in visible.unpublished,
            }
        )
    return summaries


def document_payload(document_id, user, language, query=None):
    """``DocumentPayload`` of a visible document; None when it is unknown or not visible.

    *query* carries the Corpus filters; each analysis says whether they keep
    it (``match``), by the rule of the search.
    """
    visible = visible_set(user)
    document_id = str(document_id)
    if document_id not in visible.documents:
        return None
    chains = structure(visible, user)
    analyses = sorted(a for a, (d, _) in chains.items() if d == document_id)
    readable = readable_nodegroup_ids(user)
    part_of = _links("component", "item_visual_is_part_of_document", readable)
    components = {c for c in visible.components if document_id in part_of[c]}
    values = Values([document_id], ["doc_name", "doc_manifest", "doc_owner"], user)
    manifest_url = (
        rewrite_legacy_url(values.first(document_id, "doc_manifest") or "") or None
    )
    canvases = canvases_of(manifest_json(manifest_url)) if manifest_url else []
    dims = canvas_index(canvases)
    all_rows = corpus_rows(user, language, chains=chains)
    keep, *_ = row_filter(all_rows, query or QueryDict(""))
    rows = {r["id"]: r for r in all_rows if r["document"] == document_id}
    annotations = []
    for analysis, feature_id, canvas, shape in _annotations(
        role_node(*ROLES["zone"]), analyses, dims, readable
    ):
        row = rows.get(analysis)
        if row is None:
            continue
        annotations.append(
            {
                "key": f"an:{analysis}:{feature_id}",
                "analysis": analysis,
                "name": row["name"],
                "canvas": canvas,
                "shape": shape,
                "technique": row["technique"],
                "dataKind": (row["dataKinds"] or ["file"])[0],
                "unpublished": row["unpublished"],
                "match": keep(row),
            }
        )
    located = {a["analysis"] for a in annotations}
    unlocated = [
        {
            "analysis": a,
            "name": rows[a]["name"],
            "technique": rows[a]["technique"],
            "dataKind": (rows[a]["dataKinds"] or ["file"])[0],
            "unpublished": rows[a]["unpublished"],
            "match": keep(rows[a]),
        }
        for a in analyses
        if a in rows and a not in located
    ]
    objects_of = _links("characterization", "object_observed", readable)
    related = [
        c
        for c in visible.characterizations
        if set(objects_of[c]) & ({document_id} | components)
    ]
    summaries = characterization_summaries(related, visible, user, language, dims)
    shown = set(linkable(_resource_refs(values.get(document_id, "doc_owner")), user))
    owners = [
        str(v.get("resourceId"))
        for v in values.get(document_id, "doc_owner")
        if isinstance(v, dict) and str(v.get("resourceId")) in shown
    ]
    label_of = names({document_id} | set(owners[:1]), language, user)
    per_canvas = Counter(
        a["canvas"] for a in {a["analysis"]: a for a in annotations}.values()
    )
    per_canvas_char = Counter(s["zone"]["canvas"] for s in summaries if s["zone"])
    return {
        "id": document_id,
        "name": label_of[document_id],
        "holding": label_of[owners[0]] if owners else None,
        "manifest": manifest_url,
        "canvases": [
            {
                **c,
                "analysisCount": per_canvas[c["id"]],
                "characterizationCount": per_canvas_char[c["id"]],
            }
            for c in canvases
        ],
        "annotations": annotations,
        "characterizations": summaries,
        "history": [],
        "unpublishedCount": sum(1 for a in analyses if a in visible.unpublished)
        + sum(1 for s in summaries if s["unpublished"]),
        "unpublished": document_id in visible.unpublished,
        "certaintyScale": certainty_scale(language),
        "unlocated": unlocated,
    }


_ELEMENT_SYMBOL = re.compile(r"^[A-Z][a-z]?$")
_BAND = re.compile(
    r"^(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>nm|µm|um|cm-1|cm⁻¹|keV|eV)$"
)


def layer_of(index, text, image):
    """One image layer of an imaging manifest (D46): an element map (maXRF), a spectral band (hyperspectral) or another image."""
    text = (text or "").strip()
    band = _BAND.match(text)
    if _ELEMENT_SYMBOL.match(text):
        return {
            "index": index,
            "label": text,
            "kind": "element",
            "element": text,
            "band": None,
            "image": image,
        }
    if band:
        value = float(band["value"].replace(",", "."))
        unit = band["unit"].replace("um", "µm").replace("cm-1", "cm⁻¹")
        return {
            "index": index,
            "label": text,
            "kind": "band",
            "element": None,
            "band": {"value": value, "unit": unit},
            "image": image,
        }
    return {
        "index": index,
        "label": text,
        "kind": "other",
        "element": None,
        "band": None,
        "image": image,
    }


def imaging_entries(analysis_id, manifest_values, language):
    """``FileEntry`` of each imaging manifest of an analysis (maXRF, hyperspectral, other); its canvases are the layers, numbered across manifests."""
    entries, index = [], 0
    for position, value in enumerate(manifest_values):
        url = rewrite_legacy_url(
            value if isinstance(value, str) else (value or {}).get("url", "")
        )
        if not url:
            continue
        manifest = manifest_json(url) or {}
        layers = []
        for canvas in canvases_of(manifest):
            layers.append(layer_of(index, canvas["label"], canvas["image"]))
            index += 1
        layers.sort(
            key=lambda layer: (
                layer["kind"] != "band",
                layer["band"]["value"] if layer["band"] else 0,
            )
        )
        entries.append(
            {
                "id": f"{analysis_id}:imaging:{position}",
                "name": _canvas_label(manifest.get("label")) or url.rsplit("/", 1)[-1],
                "size": None,
                "format": "application/ld+json",
                "role": "other",
                "pairedWith": None,
                "dataKind": "chemical-imaging",
                "viewer": {
                    "rendererConfigId": None,
                    "xLabel": None,
                    "yLabel": None,
                    "axisKey": None,
                    "axisTitle": None,
                    "points": None,
                    "decimated": False,
                },
                "layers": layers,
                "license": effective_license({}, language),
                "downloadUrl": url,
                "previewUrl": None,
                "zone": None,
            }
        )
    return entries


def analysis_files(analysis_id, user, language, values=None):
    """Every file of an analysis as ``FileEntry``: measurements, micro-imaging, chemical imaging.

    *values* lets a caller with several analyses share one batched ``Values``
    lookup instead of one tile query per analysis.
    """
    if values is None:
        values = Values([analysis_id], ["files", "micro", "imaging"], user)
    config_ids = {
        e.get("rendererConfig")
        for e in values.get(analysis_id, "files")
        if isinstance(e, dict) and e.get("rendererConfig")
    }
    configs = {
        str(config_id): config
        for config_id, config in RendererConfig.objects.filter(
            configid__in=list(config_ids)
        ).values_list("configid", "config")
    }
    return (
        file_entries(
            values.get(analysis_id, "files"),
            language=language,
            configs=configs,
            kind="measurement",
        )
        + file_entries(
            values.get(analysis_id, "micro"),
            language=language,
            configs={},
            kind="micro-imaging",
        )
        + imaging_entries(analysis_id, values.get(analysis_id, "imaging"), language)
    )


def analysis_payload(analysis_id, user, language):
    """``AnalysisPayload`` of a visible analysis; None when it is unknown or not visible."""
    visible = visible_set(user)
    analysis_id = str(analysis_id)
    chains = structure(visible, user)
    if analysis_id not in visible.analyses or analysis_id not in chains:
        return None
    row = next(
        r for r in corpus_rows(user, language, chains=chains) if r["id"] == analysis_id
    )
    document, component = chains[analysis_id]
    values = Values(
        [analysis_id],
        [
            "dataset",
            "bibliography",
            "statement_type",
            "statement_content",
            "instrument",
            "end",
        ],
        user,
    )
    readable = readable_nodegroup_ids(user)
    projects = sorted(
        p
        for p in _links("analysis", "analysis_by_project", readable)[analysis_id]
        if p in visible.projects
    )
    samples = sorted(
        s
        for s in _links("analysis", "sample_used", readable)[analysis_id]
        if s in visible.samples
    )
    instruments = linkable(
        _links("analysis", "instrument", readable)[analysis_id], user
    )
    ids = (
        {document}
        | ({component} if component else set())
        | set(projects)
        | set(samples)
        | set(row["operators"])
        | set(instruments[:1])
    )
    label_of = names(ids, language, user)
    slug_of = model_of(ids)
    ref = lambda rid: {"id": rid, "model": slug_of.get(rid, ""), "name": label_of[rid]}
    type_node, content_node = values.node("statement_type"), values.node(
        "statement_content"
    )
    conditions = (
        conditions_of(
            values.tiles(analysis_id, "statement_content"),
            type_node.nodeid if type_node else "",
            content_node.nodeid,
            language,
        )
        if content_node
        else []
    )
    evidence_of = characterization_summaries(
        [c for c, cited in visible.evidence.items() if analysis_id in cited],
        visible,
        user,
        language,
        {},
    )
    end = values.first(analysis_id, "end")
    return {
        "id": analysis_id,
        "name": row["name"],
        "technique": row["technique"],
        "instrument": ref(instruments[0]) if instruments else None,
        "operators": [ref(o) for o in row["operators"]],
        "projects": [ref(p) for p in projects],
        "date": {
            "start": row["date"],
            "end": _date(end) if isinstance(end, str) else None,
        },
        "document": ref(document),
        "component": ref(component) if component else None,
        "sample": ref(samples[0]) if samples else None,
        "files": analysis_files(analysis_id, user, language),
        "conditions": conditions,
        "evidenceOf": evidence_of,
        "dataset": dataset_of(values.first(analysis_id, "dataset")),
        "bibliography": [
            t
            for t in (
                label(string_texts(v), language)
                for v in values.get(analysis_id, "bibliography")
            )
            if t
        ],
        "citation": None,
        "permalink": f"{settings.PUBLIC_SERVER_ADDRESS}report/{analysis_id}",
        "certaintyScale": certainty_scale(language),
        "unpublished": row["unpublished"],
    }


ITEM_KEY = re.compile(r"^(af|im|ch):([0-9a-f-]{36}):([^:]+)$")


def parse_keys(query):
    """Selection keys of an ``ids`` parameter, repeated or comma-separated, unique and sorted."""
    return sorted(
        {k.strip() for raw in query.getlist("ids") for k in raw.split(",") if k.strip()}
    )


def items_payload(keys, user, language):
    """``ItemsResponse``: the items still visible and the keys that are not, without saying why."""
    visible = visible_set(user)
    rows = {r["id"]: r for r in corpus_rows(user, language)}
    label_of = names(
        {r["document"] for r in rows.values()}
        | {r["component"] for r in rows.values() if r["component"]},
        language,
        user,
    )
    parsed = [(key, ITEM_KEY.match(key)) for key in keys]
    ch_ids = sorted(
        {
            m.group(2)
            for _, m in parsed
            if m and m.group(1) == "ch" and m.group(3) == "-"
        }
    )
    summary_of = {
        s["id"]: s
        for s in characterization_summaries(ch_ids, visible, user, language, {})
    }
    file_ids = sorted(
        {m.group(2) for _, m in parsed if m and m.group(1) in ("af", "im")} & set(rows)
    )
    shared_values = (
        Values(file_ids, ["files", "micro", "imaging"], user) if file_ids else None
    )
    files_of, items, missing = {}, [], []
    for key, match in parsed:
        if not match:
            missing.append(key)
            continue
        kind, rid, sub = match.groups()
        if kind == "ch":
            summary = summary_of.get(rid) if sub == "-" else None
            if summary:
                items.append(
                    {
                        "key": key,
                        "kind": "characterization",
                        "characterization": summary,
                    }
                )
            else:
                missing.append(key)
            continue
        if rid not in rows:
            missing.append(key)
            continue
        if rid not in files_of:
            files_of[rid] = analysis_files(rid, user, language, values=shared_values)
        if kind == "af":
            found = next(
                (
                    f
                    for f in files_of[rid]
                    if f["id"] == sub and f["dataKind"] != "chemical-imaging"
                ),
                None,
            )
        else:
            found = next(
                (
                    f
                    for f in files_of[rid]
                    if f["dataKind"] == "chemical-imaging"
                    and any(str(layer["index"]) == sub for layer in f["layers"])
                ),
                None,
            )
        if found is None:
            missing.append(key)
            continue
        items.append(
            {
                "key": key,
                "kind": "analysis-file" if kind == "af" else "imaging",
                "analysis": analysis_hit(rows[rid], label_of),
                "file": found,
            }
        )
    return {"items": items, "missing": sorted(missing)}
