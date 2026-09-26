"""Payloads of the Explorer's Corpus APIs (spec §5), built from ``visible_set``.

Every function takes the reader and the request language. What a request
derives from the whole visible corpus is a ``CorpusBundle``, memoised by
``explorer_memo`` per reader scope, language and data version; the rest is
built per request. Values are read off the tiles of the nodegroups the reader
may read, links off the tiles by role (D6), and a resource outside
``visible_set`` never reaches a payload, a facet or a name.
"""

import datetime
import functools
import hashlib
import html
import logging
import re
import sys
import textwrap
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass

import nh3
import orjson
from django.conf import settings
from django.db.models import BooleanField, TextField
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast
from django.http import QueryDict
from django.urls import reverse
from django.utils import translation
from django.utils.http import urlencode

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
    VisibleSet,
    hidden_resource_ids,
    readable_graph_ids,
    readable_nodegroup_ids,
    visible_set,
)
from manuspectrum.utils.role_links import readable_links, role_node
from manuspectrum.views import explorer_memo
from manuspectrum.views.explorer_citations import (
    CitedAnalysis,
    citation_entry,
    person_name,
)
from manuspectrum.views.explorer_conditions import clean_html, conditions_of
from manuspectrum.views.explorer_values import (
    FALLBACK_LANGUAGE,
    acronym,
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
    "doc_identifier": ("document", "value_of_identifier"),
    "doc_identifier_type": ("document", "type_of_identifier"),
    "doc_start": ("document", "date_start_of_production_time"),
    "doc_end": ("document", "date_end_of_production_time"),
    "doc_description": ("document", "content_of_statement"),
    "doc_type": ("document", "type"),
    "comp_zone": ("component", "location_in_document"),
    "comp_type": ("component", "type"),
    "comp_colour": ("component", "color_features"),
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
    "sample_zone": ("sample", "location_in_object_of_sampling_taking"),
}
FACET_GROUPS = (
    ("part", ("partType", "partColour", "part")),
    ("analysis", ("project", "technique", "operator", "year")),
    ("characterization", ("material", "colour", "layer", "element")),
)
FACET_KEYS = tuple(key for _, keys in FACET_GROUPS for key in keys)
GROUP_OF = {key: group for group, keys in FACET_GROUPS for key in keys}
CHARACTERIZATION_KEYS = dict(FACET_GROUPS)["characterization"]
REF_FACETS = {
    "partType": "partTypes",
    "partColour": "partColours",
    "material": "materials",
    "colour": "colours",
    "element": "elements",
    "layer": "layers",
}
CHARACTERIZATION_ROLES = {
    "material": "material",
    "colour": "colour",
    "layer": "layer",
    "element": "elements",
}
TECHNIQUE_PALETTE = 10
SWATCHES = {
    "blue": "royalblue",
    "bleu": "royalblue",
    "azur": "royalblue",
    "red": "firebrick",
    "rouge": "firebrick",
    "vermillon": "orangered",
    "vermilion": "orangered",
    "green": "forestgreen",
    "vert": "forestgreen",
    "gold": "goldenrod",
    "golden": "goldenrod",
    "or": "goldenrod",
    "dore": "goldenrod",
    "silver": "silver",
    "argent": "silver",
    "argente": "silver",
    "white": "white",
    "blanc": "white",
    "black": "black",
    "noir": "black",
    "yellow": "gold",
    "jaune": "gold",
    "brown": "saddlebrown",
    "brun": "saddlebrown",
    "marron": "saddlebrown",
    "beige": "beige",
    "ochre": "peru",
    "ocre": "peru",
    "grey": "grey",
    "gray": "grey",
    "gris": "grey",
    "purple": "purple",
    "violet": "purple",
    "pourpre": "purple",
    "pink": "hotpink",
    "rose": "hotpink",
    "orange": "darkorange",
}
SWATCH_FACETS = ("colour", "partColour")
LAZY_FACETS = ("part",)
PREVIEW_SIZE = 6
_EMPTY = (None, "", [], {})
PAGE_SIZES = (10, 25, 50)
DESCRIPTION_LENGTH = 220
SHELFMARK_LABELS = frozenset({"shelfmark", "shelf mark", "call number", "cote"})
LINK_IDENTIFIER = re.compile(r"(?i)\s*(https?://|ark:)")

logger = logging.getLogger(__name__)


def _tile_order(row):
    """``ORDER BY sortorder, tileid`` of PostgreSQL: nulls last, uuids in text order."""
    sortorder, tileid = row[0], row[1]
    return (sortorder is None, sortorder or 0, tileid)


class Values:
    """Tile values of *resource_ids* for the roles *keys*, from readable nodegroups only.

    ``get`` flattens list values except references, whose list is one value;
    ``tiles`` keeps each tile's data for the roles read tile by tile
    (statements, material with its certainty), reduced to the nodes of the
    roles asked for. A role whose node is not resolved logs a warning and
    reads as empty.
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
        cases, params = [], []
        for nodegroup_id, pairs in by_group.items():
            nodeids = sorted({node.nodeid for _, node in pairs})
            cases.append(
                "WHEN %s::uuid THEN jsonb_build_object("
                + ", ".join("%s, tiledata -> %s" for _ in nodeids)
                + ")"
            )
            params += [nodegroup_id] + [
                p for nodeid in nodeids for p in (nodeid, nodeid)
            ]
        projection = RawSQL(
            "(CASE nodegroupid %s END)::text" % " ".join(cases),
            params,
            output_field=TextField(),
        )
        rows = TileModel.objects.filter(
            RawSQL(
                "resourceinstanceid = ANY(%s::uuid[])",
                [ids],
                output_field=BooleanField(),
            ),
            nodegroup_id__in=list(by_group),
        ).values_list(
            "sortorder",
            Cast("tileid", TextField()),
            Cast("resourceinstance_id", TextField()),
            Cast("nodegroup_id", TextField()),
            projection,
        )
        rows = sorted(rows, key=_tile_order)
        for _, _, rid, nodegroup_id, projected in rows:
            pairs, data = by_group.get(nodegroup_id, []), orjson.loads(projected)
            for key, node in pairs:
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


@functools.cache
def _combining_marks():
    return dict.fromkeys(
        code for code in range(sys.maxunicode + 1) if unicodedata.combining(chr(code))
    )


def fold(text):
    """*text* without accents, casefolded, for free-text matching.

    The accents are the characters of non-zero canonical combining class
    left by the NFKD decomposition.
    """
    text = text or ""
    if text.isascii():
        return text.casefold()
    decomposed = unicodedata.normalize("NFKD", text)
    return decomposed.translate(_combining_marks()).casefold()


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


def parent_chains(item_ids):
    """``{item id: its ancestor ids, nearest first}`` in the thesaurus; an unknown item has none."""
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
    return ancestors


def ancestor_terms(item_ids, chains=None):
    """``{item id: labels of its ancestors}``: a parent term found by free text brings its children (« XRF » → pXRF).

    *chains* is a ``parent_chains`` result the caller already holds.
    """
    ancestors = parent_chains(item_ids) if chains is None else chains
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


def structure(visible, user, part_of=None):
    """``{analysis id: (document id, component id or None)}`` along the first visible chain, sorted.

    *part_of* is the component → documents map the caller already holds.
    """
    readable = readable_nodegroup_ids(user)
    if part_of is None:
        part_of = _links("component", "item_visual_is_part_of_document", readable)
    observed = _links("analysis", "component_observed", readable)
    found = {}
    for analysis in visible.analyses:
        for target in sorted(observed.get(analysis, ())):
            if target in visible.documents:
                found[analysis] = (target, None)
                break
            if target in visible.components:
                documents = sorted(
                    d for d in part_of.get(target, ()) if d in visible.documents
                )
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


def colour_swatch(value):
    """Display colour of a colour concept (``SWATCHES``), the same in every language; None when no label names one.

    Labels are tried in a fixed order whatever the request language: English
    preferred label, other preferred labels by language, then alternative
    labels by language; the first colour word found wins.
    """
    entries = [
        entry
        for item in (value if isinstance(value, list) else [value])
        if isinstance(item, dict)
        for entry in item.get("labels") or []
        if isinstance(entry, dict) and isinstance(entry.get("value"), str)
    ]
    entries.sort(
        key=lambda e: (
            e.get("valuetype_id") != "prefLabel",
            e.get("language_id") != FALLBACK_LANGUAGE,
            e.get("language_id") or "",
            e["value"],
        )
    )
    for entry in entries:
        for word in re.split(r"[^a-z]+", fold(entry["value"])):
            if word in SWATCHES:
                return SWATCHES[word]
    return None


def _letters_code(text, taken):
    letters = re.sub(r"[\W_]", "", text or "").upper() or "?"
    for candidate in (letters[:1], letters[:2], letters[:3]):
        if candidate not in taken:
            return candidate
    suffix = 2
    while f"{letters[:1]}{suffix}" in taken:
        suffix += 1
    return f"{letters[:1]}{suffix}"


def family_colours(families):
    """``{family uri: colour}``: each family's ``--tech-n`` keyed by its uri, independent of counts and language.

    A family's home hue is the sha1 of its uri modulo ``TECHNIQUE_PALETTE``.
    Families are placed in uri order; one whose hue is taken takes the next
    free hue (linear probing), so two families never share a hue while one
    is free, and families beyond the palette have none (``None``). Adding a
    family only moves the families placed after it whose probe run crosses
    the hue it takes; every other family keeps its colour.
    """
    taken, colours = set(), {}
    for uri in sorted(set(families)):
        home = int(hashlib.sha1(uri.encode("utf-8")).hexdigest(), 16)
        colours[uri] = None
        for step in range(TECHNIQUE_PALETTE):
            slot = (home + step) % TECHNIQUE_PALETTE
            if slot not in taken:
                taken.add(slot)
                colours[uri] = slot + 1
                break
    return colours


def technique_marks(techniques, chains):
    """``{item id: {"code", "colour", "family"}}`` of the techniques used in the corpus, the same in every language.

    *techniques* maps an item id to ``(uri, reference value)``, *chains* is
    ``parent_chains`` of the ids. A technique whose ancestor is also used
    belongs to the family of its farthest used ancestor; ``family`` is that
    ancestor's uri, else its own, and its colour is ``family_colours`` of that
    uri. The code is the ``acronym`` of the value, else the first letters of
    its English label not already taken, in uri order.
    """
    root = {}
    for item in techniques:
        used = [a for a in chains.get(item, []) if a in techniques]
        root[item] = used[-1] if used else item
    colour_of = family_colours(techniques[f][0] for f in set(root.values()))
    by_uri = sorted(techniques, key=lambda item: (techniques[item][0], item))
    codes = {item: acronym(techniques[item][1]) for item in by_uri}
    taken = {code for code in codes.values() if code}
    for item in by_uri:
        if not codes[item]:
            refs = value_refs(techniques[item][1], FALLBACK_LANGUAGE)
            codes[item] = _letters_code(
                refs[0]["label"]["value"] if refs else "", taken
            )
            taken.add(codes[item])
    return {
        item: {
            "code": codes[item],
            "colour": colour_of[techniques[root[item]][0]],
            "family": techniques[root[item]][0],
        }
        for item in techniques
    }


class _BuildMemo:
    """Per-build memo of the pure conversions a corpus build repeats per row.

    A concept or a label recurs on thousands of rows; each distinct value is
    converted once and every row holds the same result object.
    """

    def __init__(self, language):
        self.language = language
        self._refs, self._swatches, self._terms, self._folds = {}, {}, {}, {}

    def refs(self, value):
        key = orjson.dumps(value)
        found = self._refs.get(key)
        if found is None:
            found = self._refs[key] = value_refs(value, self.language)
        return found

    def swatch(self, value):
        key = orjson.dumps(value)
        if key not in self._swatches:
            self._swatches[key] = colour_swatch(value)
        return self._swatches[key]

    def terms(self, value):
        key = orjson.dumps(value)
        found = self._terms.get(key)
        if found is None:
            found = self._terms[key] = reference_terms(value)
        return found

    def fold(self, text):
        found = self._folds.get(text)
        if found is None:
            found = self._folds[text] = fold(text)
        return found


def corpus_rows(user, language, chains=None):
    """One row per visible analysis: what search filters, counts and lists.

    *chains* skips a repeat of ``structure()`` when the caller already has it.
    """
    visible = visible_set(user)
    if chains is None:
        chains = structure(visible, user)
    projects_of = _links(
        "analysis", "analysis_by_project", readable_nodegroup_ids(user)
    )
    return _corpus_rows(user, language, visible, chains, projects_of)[0]


def _corpus_rows(user, language, visible, chains, projects_of):
    """``(rows, values)``: the ``corpus_rows`` and, per visible identified
    material, ``{facet key: set of uris}`` of the characterization facets."""
    memo = _BuildMemo(language)
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
    characterizations = Values(
        visible.characterizations, ["material", "colour", "layer", "elements"], user
    )
    value_sets = {
        c: {
            key: {
                ref["uri"]
                for v in characterizations.get(c, role)
                for ref in memo.refs(v)
            }
            for key, role in CHARACTERIZATION_ROLES.items()
        }
        for c in visible.characterizations
    }
    parts = Values(
        {c for _, c in chains.values() if c}, ["comp_type", "comp_colour"], user
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
    used = {}
    for a in analyses:
        value = values.first(a, "technique")
        for ref in memo.refs(value)[:1]:
            used.setdefault(ref["id"], (ref["uri"], value))
    parents = parent_chains(used)
    marks = technique_marks(used, parents)
    ancestors = ancestor_terms(used, parents)
    related = {d for d, _ in chains.values()} | {c for _, c in chains.values() if c}
    label_of = names(related, language, user)
    techniques_of = {}
    rows = []
    for a in analyses:
        document, component = chains[a]
        technique_value = values.first(a, "technique")
        techniques = memo.refs(technique_value)
        technique = None
        if techniques:
            technique = techniques_of.get(techniques[0]["id"])
            if technique is None or technique[0] is not techniques[0]:
                technique = (
                    techniques[0],
                    {**techniques[0], **marks[techniques[0]["id"]]},
                )
                techniques_of[techniques[0]["id"]] = technique
            technique = technique[1]
        cited = sorted(cited_by[a])

        def refs_of(key):
            return [
                ref
                for c in cited
                for v in characterizations.get(c, key)
                for ref in memo.refs(v)
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
            texts += list(memo.terms(technique_value)) + list(
                ancestors.get(technique["id"], ())
            )
        texts += [
            t
            for c in cited
            for key in ("material", "colour")
            for v in characterizations.get(c, key)
            for t in memo.terms(v)
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
                "projects": sorted(
                    p for p in projects_of.get(a, ()) if p in visible.projects
                ),
                "operators": sorted(operators_of[a] & shown_operators),
                "materials": _unique(materials),
                "colours": _unique(colours),
                "layers": _unique(refs_of("layer")),
                "elements": _unique(refs_of("elements")),
                "characterizations": [value_sets[c] for c in cited],
                "partTypes": _unique(
                    [
                        r
                        for v in (
                            parts.get(component, "comp_type") if component else []
                        )
                        for r in memo.refs(v)
                    ]
                ),
                "partColours": _unique(
                    [
                        r
                        for v in (
                            parts.get(component, "comp_colour") if component else []
                        )
                        for r in memo.refs(v)
                    ]
                ),
                "swatches": {
                    ref["uri"]: memo.swatch(item)
                    for v in [
                        *(parts.get(component, "comp_colour") if component else []),
                        *(v for c in cited for v in characterizations.get(c, "colour")),
                    ]
                    for item in (v if isinstance(v, list) else [v])
                    for ref in memo.refs(item)
                },
                "dataKinds": kinds,
                "unpublished": a in visible.unpublished,
                "text": " ".join(memo.fold(t) for t in texts),
            }
        )
    return rows, value_sets


@dataclass(frozen=True, eq=False, repr=False)
class CorpusBundle:
    """What a request derives from the whole visible corpus of one reader scope, in one language.

    ``rows`` are the ``corpus_rows`` in analysis id order, indexed ``by_id``
    and ``by_document`` (each list in ``rows`` order). ``universe`` holds,
    per facet, the values the rows carry; ``labels``, ``marks`` and
    ``swatches`` name and colour them. ``label_of`` names every document
    and component of the rows and every visible document, ``folded`` holds
    the folded name of each visible document and ``documents`` lists them
    in name order. ``order`` is the analyses-grain sort key of each row.
    ``links`` holds the role maps the payloads follow, keyed by source id.
    ``characterization_values`` holds, per visible identified material, the
    uris it carries for each facet of the characterization group.
    """

    visible: VisibleSet
    chains: dict
    links: dict
    rows: list
    by_id: dict
    by_document: dict
    universe: dict
    labels: dict
    marks: dict
    swatches: dict
    label_of: dict
    folded: dict
    documents: list
    order: dict
    characterization_values: dict


LINK_ROLES = {
    "part_of": ("component", "item_visual_is_part_of_document"),
    "projects": ("analysis", "analysis_by_project"),
    "samples": ("analysis", "sample_used"),
    "instruments": ("analysis", "instrument"),
    "objects": ("characterization", "object_observed"),
}


def build_bundle(user, language, visible):
    """The ``CorpusBundle`` of *user* in *language* over *visible*."""
    readable = readable_nodegroup_ids(user)
    links = {
        name: {
            source: frozenset(targets)
            for source, targets in _links(slug, alias, readable).items()
        }
        for name, (slug, alias) in LINK_ROLES.items()
    }
    chains = structure(visible, user, part_of=links["part_of"])
    rows, characterization_values = _corpus_rows(
        user, language, visible, chains, links["projects"]
    )
    by_document = defaultdict(list)
    for row in rows:
        by_document[row["document"]].append(row)
    label_of = names(
        {r["document"] for r in rows}
        | {r["component"] for r in rows if r["component"]}
        | visible.documents,
        language,
        user,
    )
    folds = {}

    def folded(text):
        if text not in folds:
            folds[text] = fold(text)
        return folds[text]

    names_folded = {d: folded(label_of[d]["value"]) for d in visible.documents}
    return CorpusBundle(
        visible=visible,
        chains=chains,
        links=links,
        rows=rows,
        by_id={row["id"]: row for row in rows},
        by_document=dict(by_document),
        universe=facet_universe(rows),
        labels={
            key: dict(values)
            for key, values in _facet_labels(rows, language, user).items()
        },
        marks={
            row["technique"]["uri"]: {
                k: row["technique"][k] for k in ("code", "colour", "family")
            }
            for row in rows
            if row["technique"]
        },
        swatches={
            uri: swatch for row in rows for uri, swatch in row["swatches"].items()
        },
        label_of=label_of,
        folded=names_folded,
        documents=sorted(visible.documents, key=lambda d: (names_folded[d], d)),
        order={
            row["id"]: (
                folded(label_of[row["document"]]["value"]),
                row["component"] or "",
                folded(row["name"]["value"]),
                row["id"],
            )
            for row in rows
        },
        characterization_values=characterization_values,
    )


def corpus_bundle(user, language, ticket=None):
    """The memoised ``CorpusBundle`` of *user* in *language* (``explorer_memo``).

    *ticket* is the ``explorer_memo.ticket`` the caller already read.
    """
    return explorer_memo.corpus_bundle(user, language, build_bundle, held=ticket)


def _unique(refs):
    seen, kept = set(), []
    for ref in refs:
        if ref["uri"] not in seen:
            seen.add(ref["uri"])
            kept.append(ref)
    return kept


def parse_filters(query):
    """Filters and page number of a search query; lists come as repeated or comma-separated parameters.

    ``size`` is one of ``PAGE_SIZES``, else the first; ``empty`` asks for the
    documents without analyses.
    """
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
    filters["empty"] = query.get("empty", "").lower() in ("1", "true", "yes")
    try:
        size = int(query.get("size", ""))
    except ValueError:
        size = None
    filters["size"] = size if size in PAGE_SIZES else PAGE_SIZES[0]
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
    return [ref["uri"] for ref in row[REF_FACETS[key]]]


def _facet_labels(rows, language, user):
    labels = defaultdict(dict)
    for row in rows:
        if row["technique"]:
            labels["technique"][row["technique"]["uri"]] = row["technique"]["label"]
        for key, plural in REF_FACETS.items():
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


def facet_universe(rows):
    """``{facet key: set of the values the rows carry}``."""
    return {
        key: {v for row in rows for v in _facet_values(row, key)} for key in FACET_KEYS
    }


def characterization_wanted(active, skip=None):
    """``[(facet key, selected uris)]`` of the active facets of the characterization group, *skip* left out."""
    return [
        (key, set(active[key]))
        for key in CHARACTERIZATION_KEYS
        if key != skip and active[key]
    ]


def meets(values, wanted):
    """Whether one identified material's ``{facet key: uris}`` carries a selected value of each *wanted* facet."""
    return all(values[key] & selected for key, selected in wanted)


def row_filter(rows, query, universe=None):
    """The Corpus filter rule over *rows*: ``(keep, active, filters, page, needle, universe, carried)``.

    ``keep(row, skip=None)`` is OR inside a facet, AND across facets, and the
    folded free text ``needle``; ``skip`` leaves one facet out (open facet
    counts). The facets of the characterization group hold on one identified
    material: a row is kept when one characterization citing it carries a
    selected value of each of them. ``carried(row, key)`` is the set of
    values of *key* a row counts for under the other selections: in that
    group, the values of the characterizations that meet the other facets of
    the group. ``universe`` holds, per facet, the values the rows carry; a
    selected value outside it is ignored (§3.3). A caller filtering a part of
    the corpus passes the ``facet_universe`` of the whole corpus.
    """
    filters, page = parse_filters(query)
    if universe is None:
        universe = facet_universe(rows)
    active = {
        key: [v for v in filters[key] if v in universe[key]] for key in FACET_KEYS
    }
    needle = fold(filters["q"])

    def meeting(row, skip):
        wanted = characterization_wanted(active, skip)
        if not wanted:
            return None
        return [c for c in row["characterizations"] if meets(c, wanted)]

    def keep(row, skip=None):
        for key in FACET_KEYS:
            if (
                key != skip
                and key not in CHARACTERIZATION_KEYS
                and active[key]
                and not set(_facet_values(row, key)) & set(active[key])
            ):
                return False
        if meeting(row, skip) == []:
            return False
        return not needle or needle in row["text"]

    def carried(row, key):
        if not keep(row, key):
            return set()
        found = meeting(row, key) if key in CHARACTERIZATION_KEYS else None
        if found is None:
            return set(_facet_values(row, key))
        return set().union(*(c[key] for c in found))

    return keep, active, filters, page, needle, universe, carried


def facet_entry(key, rows, active, counted, labels, marks, swatches, offered):
    """One ``Facet`` over *rows*: the values of *offered* with a count and the selected ones.

    Counts are "open to the other selections" (``counted``, the ``carried`` of
    ``row_filter``). A selected value is listed at count 0 when no row counts
    for it. Values are in label order, years in numeric order; ``total`` is
    the number of values.
    """
    counts = Counter(v for row in rows for v in counted(row, key))
    values = [
        {
            "id": v,
            "label": labels[key][v],
            "count": counts[v],
            "mark": marks.get(v) if key == "technique" else None,
            "swatch": swatches.get(v) if key in SWATCH_FACETS else None,
        }
        for v in offered | set(active[key])
        if counts[v] > 0 or v in active[key]
    ]
    values.sort(
        key=(
            (lambda item: item["id"])
            if key == "year"
            else (lambda item: (fold(item["label"]["value"]), item["id"]))
        )
    )
    return {"key": key, "group": GROUP_OF[key], "values": values, "total": len(values)}


def preview(facet, active):
    """*facet* cut to its first ``PREVIEW_SIZE`` values plus the selected ones; ``total`` keeps the full count."""
    selected = set(active[facet["key"]])
    return {
        **facet,
        "values": [
            value
            for index, value in enumerate(facet["values"])
            if index < PREVIEW_SIZE or value["id"] in selected
        ],
    }


def corpus_facets(bundle, rows, active, counted):
    """The ``Facet`` of every key the visible corpus carries; ``LAZY_FACETS`` come as a ``preview``."""
    facets = []
    for key in FACET_KEYS:
        if not bundle.universe[key]:
            continue
        facet = facet_entry(
            key,
            rows,
            active,
            counted,
            bundle.labels,
            bundle.marks,
            bundle.swatches,
            bundle.universe[key],
        )
        facets.append(preview(facet, active) if key in LAZY_FACETS else facet)
    return facets


def wants_facets(query):
    """False when the query says ``facets=0``: the client holds the facets of these filters."""
    return query.get("facets", "") not in ("0", "false", "no")


def search_payload(query, user, language, ticket=None):
    """``SearchResponse`` (spec §5): results of one page, open facet counts, unpublished count.

    Facet counts are "open to the other selections": OR inside a facet, AND
    across facets. A facet is absent when no value has a count on the whole
    visible set; a selected value that is not in the visible set is ignored
    without a word. ``facets`` is None with ``facets=0``; a facet of
    ``LAZY_FACETS`` lists its first ``PREVIEW_SIZE`` values and the selected
    ones, ``facet_payload`` gives all of them.

    In the documents grain, a visible document without any visible analysis
    is listed only with ``empty``, when no facet filter is active and the
    free text is in its name; ``withoutAnalyses`` counts those documents
    whether listed or not (0 in the other cases).
    """
    bundle = corpus_bundle(user, language, ticket)
    rows = bundle.rows
    keep, active, filters, page, needle, _, counted = row_filter(
        rows, query, universe=bundle.universe
    )
    matching = [row for row in rows if keep(row)]
    facets = (
        corpus_facets(bundle, rows, active, counted) if wants_facets(query) else None
    )

    visible, label_of = bundle.visible, bundle.label_of
    size = filters["size"]
    without_analyses = 0
    if filters["grain"] == "documents":
        per_document = Counter(row["document"] for row in matching)
        with_rows = bundle.by_document
        candidates = bundle.documents
        bare = (
            set()
            if any(active.values())
            else {
                d
                for d in candidates
                if d not in with_rows and (not needle or needle in bundle.folded[d])
            }
        )
        without_analyses = len(bare)
        listed = [
            d
            for d in candidates
            if per_document[d] > 0 or (filters["empty"] and d in bare)
        ]
        chunk_ids = listed[(page - 1) * size : page * size]
        chunk = document_hits(
            chunk_ids, per_document, visible, user, language, label_of
        )
        total = len(listed)
        unpublished = sum(1 for d in listed if d in visible.unpublished)
    else:
        matching.sort(key=lambda r: bundle.order[r["id"]])
        chunk = [
            analysis_hit(row, label_of)
            for row in matching[(page - 1) * size : page * size]
        ]
        total = len(matching)
        unpublished = sum(1 for r in matching if r["unpublished"])
    return {
        "total": total,
        "page": {"number": page, "size": size, "count": len(chunk)},
        "results": chunk,
        "facets": facets,
        "unpublishedCount": unpublished,
        "withoutAnalyses": without_analyses,
    }


def document_scope(query):
    """The document ``document`` names in *query*: "" without one, None when it is not a UUID."""
    if "document" not in query:
        return ""
    try:
        return str(uuid.UUID(query.get("document", "")))
    except ValueError:
        return None


def document_rows(bundle, document_id):
    """The rows of the analyses of a visible document, in ``rows`` order; None when it is not visible."""
    if document_id not in bundle.visible.documents:
        return None
    return bundle.by_document.get(document_id, [])


def document_facet(key, bundle, rows, active, counted):
    """``Facet`` *key* of one document's *rows*: the values they carry plus the selected ones; None without values."""
    facet = facet_entry(
        key,
        rows,
        active,
        counted,
        bundle.labels,
        bundle.marks,
        bundle.swatches,
        {v for row in rows for v in _facet_values(row, key)},
    )
    return facet if facet["values"] else None


def facet_payload(key, query, user, language, ticket=None):
    """``Facet`` *key* under the filters of *query*, every value; None when absent.

    Over the whole visible corpus, or over one visible document when
    ``document`` names it: then the facet is the one ``match_payload`` lists
    for that document. ``find`` narrows the values to those whose folded
    label holds its folded text, the selected ones kept; ``total`` stays the
    number of values without it. A key outside ``FACET_KEYS``, a facet the
    search or the match would not show (no value), or a ``document`` that is
    not a UUID or not visible, is None.
    """
    document_id = document_scope(query)
    if key not in FACET_KEYS or document_id is None:
        return None
    bundle = corpus_bundle(user, language, ticket)
    if document_id:
        rows = document_rows(bundle, document_id)
        if rows is None:
            return None
        _, active, *_, counted = row_filter(rows, query, universe=bundle.universe)
        facet = document_facet(key, bundle, rows, active, counted)
        if facet is None:
            return None
    else:
        if not bundle.universe[key]:
            return None
        _, active, *_, counted = row_filter(
            bundle.rows, query, universe=bundle.universe
        )
        facet = facet_entry(
            key,
            bundle.rows,
            active,
            counted,
            bundle.labels,
            bundle.marks,
            bundle.swatches,
            bundle.universe[key],
        )
    needle = fold(query.get("find", "").strip())
    if needle:
        selected = set(active[key])
        facet["values"] = [
            value
            for value in facet["values"]
            if needle in fold(value["label"]["value"]) or value["id"] in selected
        ]
    return facet


def document_characterizations(bundle, document_id):
    """Ids of the visible identified materials observed on *document_id* or on one of its visible parts, sorted."""
    part_of, objects_of = bundle.links["part_of"], bundle.links["objects"]
    observed = {document_id} | {
        c for c in bundle.visible.components if document_id in part_of.get(c, ())
    }
    return sorted(
        c
        for c in bundle.visible.characterizations
        if objects_of.get(c, frozenset()) & observed
    )


def match_payload(document_id, query, user, language, ticket=None):
    """``DocumentMatch``: what the Corpus filters of *query* keep in a visible document; None when not visible.

    ``facets`` list the values the document's analyses carry plus the
    selected ones (count 0 when it lacks them); a facet without values is
    absent. ``kept.analyses`` are the document's analyses ``row_filter``
    keeps, with the facet universe of the whole corpus, or None when no
    filter is active (every analysis kept); ``total`` counts them. ``kept.characterizations`` are its identified materials carrying a
    selected value of each active facet of the characterization group; the
    other facets and the free text leave them kept. Grain, page and size are
    not read.
    """
    bundle = corpus_bundle(user, language, ticket)
    document_id = str(document_id)
    rows = document_rows(bundle, document_id)
    if rows is None:
        return None
    keep, active, _, _, needle, _, counted = row_filter(
        rows, query, universe=bundle.universe
    )
    facets = [
        facet
        for key in FACET_KEYS
        if (facet := document_facet(key, bundle, rows, active, counted))
    ]
    kept = sorted(row["id"] for row in rows if keep(row))
    filtered = bool(needle) or any(active.values())
    wanted = characterization_wanted(active)
    return {
        "facets": facets,
        "kept": {
            "analyses": kept if filtered else None,
            "characterizations": [
                c
                for c in document_characterizations(bundle, document_id)
                if meets(bundle.characterization_values[c], wanted)
            ],
        },
        "total": len(kept),
    }


_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193


def day_index(day, count):
    """Position (from 0) of the document of *day* (``YYYY-MM-DD``) among *count*; None when *count* is 0.

    FNV-1a (32 bits) of the day's characters modulo *count*.
    """
    if count <= 0:
        return None
    digest = _FNV_OFFSET
    for character in day:
        digest = ((digest ^ ord(character)) * _FNV_PRIME) & 0xFFFFFFFF
    return digest % count


def home_payload(day, user, language, ticket=None):
    """``HomeResponse``: the explorer home of *day* (a ``YYYY-MM-DD`` string) for the reader.

    ``documentCount`` counts the documents with a visible analysis,
    ``unpublishedCount`` the unpublished ones among them; ``techniques`` and
    ``projects`` are the facets of the unfiltered search; ``featured`` is the
    ``DocumentHit`` at ``day_index`` of those documents in name order, None
    without any.
    """
    bundle = corpus_bundle(user, language, ticket)
    listed = [d for d in bundle.documents if d in bundle.by_document]
    _, active, *_, counted = row_filter(
        bundle.rows, QueryDict(""), universe=bundle.universe
    )
    facets = {
        facet["key"]: facet["values"]
        for facet in corpus_facets(bundle, bundle.rows, active, counted)
        if facet["key"] in ("technique", "project")
    }
    position = day_index(day, len(listed))
    featured = None
    if position is not None:
        chosen = listed[position]
        featured = document_hits(
            [chosen],
            {chosen: len(bundle.by_document[chosen])},
            bundle.visible,
            user,
            language,
            bundle.label_of,
        )[0]
    return {
        "documentCount": len(listed),
        "techniques": facets.get("technique", []),
        "projects": facets.get("project", []),
        "featured": featured,
        "unpublishedCount": sum(1 for d in listed if d in bundle.visible.unpublished),
    }


def plain_text(markup, length=DESCRIPTION_LENGTH):
    """*markup* as plain text: tags removed, entities decoded, whitespace collapsed, cut on a word to *length* characters with « … »."""
    spaced = re.sub(r"(?i)<br\s*/?>|</(p|li|div|h[1-6])\s*>", " ", markup or "")
    text = html.unescape(nh3.clean(spaced, tags=set(), attributes={}))
    return textwrap.shorten(text, width=length, placeholder="…")


def _shelfmark(tiles, value_node, type_node, language):
    """The identifier typed as a shelfmark (``SHELFMARK_LABELS``), else the first identifier; None without one.

    An identifier that is a link (``LINK_IDENTIFIER``: http, https, ark) is
    never a shelfmark.
    """
    found = []
    for data in tiles:
        text = label(string_texts(data.get(value_node.nodeid)), language)
        if not text or LINK_IDENTIFIER.match(text["value"]):
            continue
        terms = (
            {fold(t) for t in reference_terms(data.get(type_node.nodeid))}
            if type_node
            else set()
        )
        found.append((not terms & SHELFMARK_LABELS, text))
    return min(found, key=lambda f: f[0])[1] if found else None


def document_hits(document_ids, per_document, visible, user, language, label_of):
    """``DocumentHit`` of each of *document_ids*, in order, read in one batch.

    A field whose nodegroup the reader may not read is None; the holding is
    the first owner a linked reference may show.
    """
    values = Values(
        document_ids,
        [
            "doc_owner",
            "doc_identifier",
            "doc_identifier_type",
            "doc_start",
            "doc_end",
            "doc_description",
            "doc_type",
        ],
        user,
    )
    owners_of = {d: _resource_refs(values.get(d, "doc_owner")) for d in document_ids}
    shown = set(linkable({o for v in owners_of.values() for o in v}, user))
    owner_of = {
        d: [
            str(v.get("resourceId"))
            for v in values.get(d, "doc_owner")
            if isinstance(v, dict) and str(v.get("resourceId")) in shown
        ][:1]
        for d in document_ids
    }
    owner_names = names({o for v in owner_of.values() for o in v}, language, user)
    identifier_node = values.node("doc_identifier")
    type_node = values.node("doc_identifier_type")
    start_node, end_node = values.node("doc_start"), values.node("doc_end")
    hits = []
    for d in document_ids:
        dates = None
        for data in values.tiles(d, "doc_start") or values.tiles(d, "doc_end"):
            start = data.get(start_node.nodeid) if start_node else None
            end = data.get(end_node.nodeid) if end_node else None
            if start or end:
                dates = {
                    "start": _date(start) if isinstance(start, str) else None,
                    "end": _date(end) if isinstance(end, str) else None,
                }
                break
        description = next(
            (
                found
                for found in (
                    label(
                        {
                            lang: plain_text(text)
                            for lang, text in string_texts(v).items()
                        },
                        language,
                    )
                    for v in values.get(d, "doc_description")
                )
                if found
            ),
            None,
        )
        types = value_refs(values.first(d, "doc_type"), language)
        hits.append(
            {
                "type": "document",
                "id": d,
                "name": label_of[d],
                "holding": owner_names[owner_of[d][0]] if owner_of[d] else None,
                "analysisCount": per_document[d],
                "thumbnail": reverse("thumbnail", kwargs={"resource_id": d}),
                "unpublished": d in visible.unpublished,
                "shelfmark": (
                    _shelfmark(
                        values.tiles(d, "doc_identifier"),
                        identifier_node,
                        type_node,
                        language,
                    )
                    if identifier_node
                    else None
                ),
                "dates": dates,
                "description": description,
                "documentType": types[0]["label"] if types else None,
            }
        )
    return hits


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


def characterization_summaries(
    ids, visible, user, language, dims, objects_of=None, analysis_rows=None
):
    """``CharacterizationSummary`` of the visible identified materials among *ids*.

    ``evidence`` names each visible analysis cited, in id order. *objects_of*
    is the characterization → objects observed map the caller already holds,
    *analysis_rows* the corpus rows by analysis id, whose names it reuses.
    """
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
    if objects_of is None:
        objects_of = _links("characterization", "object_observed", readable)
    objects = {
        c: sorted(
            o
            for o in objects_of.get(c, ())
            if o in visible.documents | visible.components
        )
        for c in ids
    }
    authors_of = {c: _resource_refs(values.get(c, "ch_authors")) for c in ids}
    shown_authors = set(linkable({a for v in authors_of.values() for a in v}, user))
    authors = {c: sorted(authors_of[c] & shown_authors) for c in ids}
    rows = analysis_rows or {}
    cited = {a for c in ids for a in visible.evidence.get(c, ())}
    label_of = names(
        set(ids)
        | {o for v in objects.values() for o in v}
        | {a for v in authors.values() for a in v}
        | {a for a in cited if a not in rows},
        language,
        user,
    )
    label_of.update({a: rows[a]["name"] for a in cited if a in rows})
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
                "evidence": [
                    {"id": a, "name": label_of[a]} for a in visible.evidence.get(c, ())
                ],
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


def sample_summaries(analyses, visible, user, language, dims, sample_of=None):
    """``SampleSummary`` of the visible samples used by *analyses*, sorted by id.

    *analyses* are the visible analyses of one document; each sample lists
    those that used it. The zone is the first annotation feature of the
    sample zone, resolved through the ``canvas_index`` *dims*. *sample_of*
    is the analysis → samples map the caller already holds.
    """
    readable = readable_nodegroup_ids(user)
    if sample_of is None:
        sample_of = _links("analysis", "sample_used", readable)
    used_by = defaultdict(set)
    for analysis in analyses:
        for sample in sample_of.get(analysis, ()):
            if sample in visible.samples:
                used_by[sample].add(analysis)
    ids = sorted(used_by)
    label_of = names(ids, language, user)
    zones = _zone(role_node(*ROLES["sample_zone"]), ids, dims, readable)
    return [
        {
            "id": s,
            "name": label_of[s],
            "zone": zones.get(s),
            "analyses": sorted(used_by[s]),
            "unpublished": s in visible.unpublished,
        }
        for s in ids
    ]


def document_payload(document_id, user, language, ticket=None):
    """``DocumentPayload`` of a visible document, the same whatever the filters; None when it is unknown or not visible.

    ``techniques`` holds each technique of its analyses by uri; each analysis
    names its technique by that uri and lists its zones, each on a canvas
    given by its position in ``canvases``. A zone on a canvas the manifest
    does not list is left out; an analysis without zones is not located on
    a page. ``document_match`` says what the filters keep. ``history`` (the
    document's dated and placed events, spec §5) is empty until the map and
    timeline API fills it.
    """
    bundle = corpus_bundle(user, language, ticket)
    visible = bundle.visible
    document_id = str(document_id)
    if document_id not in visible.documents:
        return None
    rows = bundle.by_document.get(document_id, [])
    readable = readable_nodegroup_ids(user)
    values = Values([document_id], ["doc_name", "doc_manifest", "doc_owner"], user)
    manifest_url = (
        rewrite_legacy_url(values.first(document_id, "doc_manifest") or "") or None
    )
    canvases = canvases_of(manifest_json(manifest_url)) if manifest_url else []
    dims = canvas_index(canvases)
    position = {canvas["id"]: index for index, canvas in enumerate(canvases)}
    zones = defaultdict(list)
    for analysis, _, canvas, shape in _annotations(
        role_node(*ROLES["zone"]), [row["id"] for row in rows], dims, readable
    ):
        if canvas in position:
            zones[analysis].append({"canvas": position[canvas], "shape": shape})
    techniques = {}
    analyses = []
    for row in rows:
        technique = row["technique"]
        if technique:
            techniques.setdefault(technique["uri"], technique)
        analyses.append(
            {
                "id": row["id"],
                "name": row["name"],
                "technique": technique["uri"] if technique else None,
                "dataKind": (row["dataKinds"] or ["file"])[0],
                "unpublished": row["unpublished"],
                "zones": zones.get(row["id"], []),
            }
        )
    summaries = characterization_summaries(
        document_characterizations(bundle, document_id),
        visible,
        user,
        language,
        dims,
        objects_of=bundle.links["objects"],
        analysis_rows=bundle.by_id,
    )
    shown = set(linkable(_resource_refs(values.get(document_id, "doc_owner")), user))
    owners = [
        str(v.get("resourceId"))
        for v in values.get(document_id, "doc_owner")
        if isinstance(v, dict) and str(v.get("resourceId")) in shown
    ]
    label_of = names({document_id} | set(owners[:1]), language, user)
    per_canvas = Counter(
        zone["canvas"]
        for entry in analyses
        for zone in {z["canvas"]: z for z in entry["zones"]}.values()
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
                "analysisCount": per_canvas[index],
                "characterizationCount": per_canvas_char[c["id"]],
            }
            for index, c in enumerate(canvases)
        ],
        "techniques": techniques,
        "analyses": analyses,
        "characterizations": summaries,
        "history": [],
        "unpublishedCount": sum(1 for row in rows if row["unpublished"])
        + sum(1 for s in summaries if s["unpublished"]),
        "unpublished": document_id in visible.unpublished,
        "certaintyScale": certainty_scale(language),
        "samples": sample_summaries(
            [row["id"] for row in rows],
            visible,
            user,
            language,
            dims,
            sample_of=bundle.links["samples"],
        ),
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


def renderer_configs(values, analysis_ids):
    """``{config id: config}`` of the renderer configurations the measurement files of *analysis_ids* name, in one query."""
    config_ids = {
        e.get("rendererConfig")
        for analysis_id in analysis_ids
        for e in values.get(analysis_id, "files")
        if isinstance(e, dict) and e.get("rendererConfig")
    }
    if not config_ids:
        return {}
    return {
        str(config_id): config
        for config_id, config in RendererConfig.objects.filter(
            configid__in=list(config_ids)
        ).values_list("configid", "config")
    }


def analysis_files(analysis_id, user, language, values=None, configs=None):
    """Every file of an analysis as ``FileEntry``: measurements, micro-imaging, chemical imaging.

    *values* and *configs* (``renderer_configs``) let a caller with several
    analyses share one batched tile lookup and one configuration lookup
    instead of one of each per analysis.
    """
    if values is None:
        values = Values([analysis_id], ["files", "micro", "imaging"], user)
    if configs is None:
        configs = renderer_configs(values, [analysis_id])
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


def report_url(resource_id, language):
    """Path of the Arches report of *resource_id* on this site, in *language*."""
    with translation.override(language):
        return reverse("resource_report", kwargs={"resourceid": resource_id})


def permalink(resource_id):
    """Absolute URL of the Arches report of *resource_id*, as citations and exports name it."""
    return f"{settings.PUBLIC_SERVER_ADDRESS}report/{resource_id}"


def product_url(route, query, language):
    """Absolute URL of the language-neutral product *route* for the scope *query* in *language*.

    *query* is an URL-encoded ``ExportScope.query`` (``ids=…``,
    ``document=…``, ``project=…`` and their flags); ``lang`` is appended.
    """
    path = reverse(route).lstrip("/")
    return f"{settings.PUBLIC_SERVER_ADDRESS}{path}?{query}&{urlencode({'lang': language})}"


def cited_analysis(row, end, label_of, operators, projects):
    """``CitedAnalysis`` of a corpus *row*; *operators* and *projects* are the ids the citation may name."""
    return CitedAnalysis(
        id=row["id"],
        name=row["name"]["value"],
        permalink=permalink(row["id"]),
        start=row["date"],
        end=end,
        authors=tuple(
            person_name(label_of[o]["value"]) for o in operators if o in label_of
        ),
        projects=tuple(label_of[p]["value"] for p in projects if p in label_of),
    )


def licence_labels(files):
    """Labels of the licences of *files* (``FileEntry``), in file order."""
    return [f["license"]["label"]["value"] for f in files if f.get("license")]


def analysis_payload(analysis_id, user, language):
    """``AnalysisPayload`` of a visible analysis; None when it is unknown or not visible."""
    bundle = corpus_bundle(user, language)
    visible = bundle.visible
    analysis_id = str(analysis_id)
    if analysis_id not in visible.analyses or analysis_id not in bundle.chains:
        return None
    row = bundle.by_id[analysis_id]
    document, component = bundle.chains[analysis_id]
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
    links = bundle.links
    projects = sorted(
        p for p in links["projects"].get(analysis_id, ()) if p in visible.projects
    )
    samples = sorted(
        s for s in links["samples"].get(analysis_id, ()) if s in visible.samples
    )
    instruments = linkable(links["instruments"].get(analysis_id, ()), user)
    ids = (
        {document}
        | ({component} if component else set())
        | set(projects)
        | set(samples)
        | set(row["operators"])
        | set(instruments[:1])
    )
    cited_by = sorted(
        c
        for c, cited in visible.evidence.items()
        if analysis_id in cited and c in visible.characterizations
    )
    label_of = names(ids | set(cited_by), language, user)
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
    end = values.first(analysis_id, "end")
    end = _date(end) if isinstance(end, str) else None
    files = analysis_files(analysis_id, user, language)
    dataset = dataset_of(values.first(analysis_id, "dataset"))
    return {
        "id": analysis_id,
        "name": row["name"],
        "technique": row["technique"],
        "instrument": ref(instruments[0]) if instruments else None,
        "operators": [ref(o) for o in row["operators"]],
        "projects": [ref(p) for p in projects],
        "date": {
            "start": row["date"],
            "end": end,
        },
        "document": ref(document),
        "component": ref(component) if component else None,
        "sample": ref(samples[0]) if samples else None,
        "files": files,
        "conditions": conditions,
        "evidenceOf": [{"id": c, "name": label_of[c]} for c in cited_by],
        "dataset": dataset,
        "bibliography": [
            t
            for t in (
                label(string_texts(v), language)
                for v in values.get(analysis_id, "bibliography")
            )
            if t
        ],
        "citation": citation_entry(
            dataset,
            [cited_analysis(row, end, label_of, row["operators"], projects)],
            licences=licence_labels(files),
            language=language,
            accessed=datetime.date.today(),
        ),
        "manifest": product_url(
            "iiif-v3-explorer-manifest", f"ids=an:{analysis_id}:-", language
        ),
        "permalink": permalink(analysis_id),
        "reportUrl": report_url(analysis_id, language),
        "certaintyScale": certainty_scale(language),
        "unpublished": row["unpublished"],
    }


ITEM_KEY = re.compile(r"^(an|af|im|ch):([0-9a-f-]{36}):([^:]+)$")


def shown_files(files):
    """The files of *files* a viewer shows: readable spectra, imaging manifests with layers, micro-images."""
    return [
        f
        for f in files
        if (f["dataKind"] == "xy" and f["role"] == "readable")
        or (f["dataKind"] == "chemical-imaging" and f["layers"])
        or f["dataKind"] == "micro-imaging"
    ]


def parse_keys(query):
    """Selection keys of an ``ids`` parameter, repeated or comma-separated, unique and sorted."""
    return sorted(
        {k.strip() for raw in query.getlist("ids") for k in raw.split(",") if k.strip()}
    )


def items_payload(keys, user, language):
    """``ItemsResponse``: the items still visible and the keys that are not, without saying why.

    ``an:<analysis>:-`` is a whole analysis with the files a viewer shows
    (possibly none); ``af:<analysis>:<file>`` one of its files and
    ``im:<analysis>:<layer>`` the imaging manifest holding that layer;
    ``ch:<characterization>:-`` an identified material.
    """
    bundle = corpus_bundle(user, language)
    visible, rows, label_of = bundle.visible, bundle.by_id, bundle.label_of
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
        for s in characterization_summaries(
            ch_ids,
            visible,
            user,
            language,
            {},
            objects_of=bundle.links["objects"],
            analysis_rows=rows,
        )
    }
    file_ids = sorted(
        {m.group(2) for _, m in parsed if m and m.group(1) in ("an", "af", "im")}
        & set(rows)
    )
    shared_values = (
        Values(file_ids, ["files", "micro", "imaging"], user) if file_ids else None
    )
    shared_configs = (
        renderer_configs(shared_values, file_ids) if shared_values else None
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
        if rid not in rows or (kind == "an" and sub != "-"):
            missing.append(key)
            continue
        if rid not in files_of:
            files_of[rid] = analysis_files(
                rid, user, language, values=shared_values, configs=shared_configs
            )
        if kind == "an":
            items.append(
                {
                    "key": key,
                    "kind": "analysis",
                    "analysis": analysis_hit(rows[rid], label_of),
                    "files": shown_files(files_of[rid]),
                }
            )
            continue
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
