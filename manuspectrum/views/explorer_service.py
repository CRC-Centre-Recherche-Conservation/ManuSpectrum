"""Payloads of the Explorer's Corpus APIs (spec §5), built from ``visible_set``.

Every function takes the reader and the request language; nothing is memoised
in v1. Values are read off the tiles of the nodegroups the reader may read,
links off the tiles by role (D6), and a resource outside ``visible_set`` never
reaches a payload, a facet or a name.
"""

import logging
import unicodedata
from collections import Counter, defaultdict

from django.conf import settings
from django.urls import reverse

from arches.app.models.models import ResourceInstance, TileModel
from arches_controlled_lists.models import ListItem, ListItemValue

from manuspectrum.utils.public_visibility import (
    hidden_resource_ids,
    readable_nodegroup_ids,
    visible_set,
)
from manuspectrum.utils.role_links import readable_links, role_node
from manuspectrum.views.explorer_values import (
    name_of,
    reference_terms,
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
            .order_by("sortorder")
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


def names(resource_ids, language):
    """``{id: Label}`` of resources of any model, from their ``label_of_name`` (fallback in ``name_of``)."""
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
        if node:
            for rid, value in (
                TileModel.objects.filter(
                    resourceinstance_id__in=rids, nodegroup_id=node.nodegroup_id
                )
                .order_by("sortorder")
                .values_list("resourceinstance_id", f"data__{node.nodeid}")
            ):
                if value not in _EMPTY:
                    values[str(rid)].append(value)
        for rid in rids:
            found[rid] = name_of(
                values[rid], index.name if index else {}, rid, language
            )
    return found


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


def corpus_rows(user, language):
    """One row per visible analysis: what search filters, counts and lists."""
    visible = visible_set(user)
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
    hidden = hidden_resource_ids(user)
    analysis_index = GraphIndex.for_slug("analysis")
    analysis_model = analysis_index.name if analysis_index else {}
    technique_ids = {
        ref["id"]
        for a in analyses
        for ref in value_refs(values.first(a, "technique"), language)
    }
    ancestors = ancestor_terms(technique_ids)
    related = {d for d, _ in chains.values()} | {c for _, c in chains.values() if c}
    label_of = names(related, language)
    rows = []
    for a in analyses:
        document, component = chains[a]
        technique_value = values.first(a, "technique")
        techniques = value_refs(technique_value, language)
        technique = techniques[0] if techniques else None
        cited = cited_by[a]

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
                "canvas": _canvas_of(values.first(a, "zone")),
                "date": date,
                "year": int(date[:4]) if date and date[:4].isdigit() else None,
                "projects": sorted(p for p in projects_of[a] if p in visible.projects),
                "operators": sorted(
                    {
                        str(v.get("resourceId"))
                        for v in values.get(a, "operators")
                        if isinstance(v, dict)
                        and v.get("resourceId")
                        and str(v.get("resourceId")) not in hidden
                    }
                ),
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
            {v for raw in query.getlist(key) for v in raw.split(",") if v.strip()}
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


def _facet_labels(rows, language):
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
    named = names(ids, language)
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


def search_payload(query, user, language):
    """``SearchResponse`` (spec §5): results of one page, open facet counts, unpublished count.

    Facet counts are "open to the other selections": OR inside a facet, AND
    across facets. A facet is absent when no value has a count on the whole
    visible set; a selected value that is not in the visible set is ignored
    without a word.
    """
    rows = corpus_rows(user, language)
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

    matching = [row for row in rows if keep(row)]
    labels = _facet_labels(rows, language)
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
                else (lambda item: fold(item["label"]["value"]))
            )
        )
        facets.append({"key": key, "values": values})

    visible = visible_set(user)
    label_of = names(
        {r["document"] for r in rows}
        | {r["component"] for r in rows if r["component"]}
        | visible.documents,
        language,
    )
    if filters["grain"] == "documents":
        per_document = Counter(row["document"] for row in matching)
        candidates = sorted(visible.documents, key=lambda d: fold(label_of[d]["value"]))
        results = [
            {
                "type": "document",
                "id": d,
                "name": label_of[d],
                "holding": None,
                "analysisCount": per_document[d],
                "thumbnail": settings.PUBLIC_SERVER_ADDRESS
                + reverse("thumbnail", kwargs={"resource_id": d}).lstrip("/"),
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
