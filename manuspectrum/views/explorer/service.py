"""Payloads of the Explorer's Corpus APIs (spec §5), built from ``visible_set``.

Every function takes the reader and the request language. What a request
derives from the whole visible corpus is a ``CorpusBundle``, memoised by
``explorer.memo`` per reader scope, language and data version; the rest is
built per request. Values are read off the tiles of the nodegroups the reader
may read, links off the tiles by role (D6), and a resource outside
``visible_set`` never reaches a payload, a facet or a name.
"""

import datetime
import hashlib
import html
import logging
import re
import textwrap
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
    ResourceInstance,
    TileModel,
)
from arches_controlled_lists.models import ListItem, ListItemValue

from manuspectrum.constants.licenses import effective_license
from manuspectrum.iiif.facts import CharacterizationZones, listed_source
from manuspectrum.iiif.ids import content_state as content_state_url
from manuspectrum.iiif.sources import (
    canvas_index,
    canvas_label,
    canvases_of,
    manifest_json,
)
from manuspectrum.iiif.zones import annotation_features, first_zone
from manuspectrum.models import RendererConfig
from manuspectrum.utils.public_visibility import (
    VisibleSet,
    hidden_resource_ids,
    readable_graph_ids,
    readable_nodegroup_ids,
    unpublished_resource_ids,
    visible_set,
)
from manuspectrum.utils.role_links import readable_links, role_node
from manuspectrum.utils.roles import ROLES
from manuspectrum.views.explorer import memo as explorer_memo
from manuspectrum.views.explorer.citations import (
    CitedAnalysis,
    citation_entry,
    shown_citation,
    person_name,
)
from manuspectrum.views.explorer.conditions import clean_html, conditions_of
from manuspectrum.views.explorer.values import (
    FALLBACK_LANGUAGE,
    StoredConfig,
    acronym,
    dataset_of,
    element_symbols,
    file_entries,
    fold,
    label,
    name_of,
    plots,
    reference_terms,
    rewrite_legacy_url,
    string_texts,
    value_refs,
)
from manuspectrum.views.explorer.swatches import (
    SWATCH_ORDER,
    colour_rank,
    colour_refs,
    colour_swatch,
)
from manuspectrum.views.summary_service import GraphIndex, _date

FACET_GROUPS = (
    ("part", ("partType", "part")),
    ("analysis", ("project", "technique", "operator", "year")),
    ("characterization", ("material", "colour", "layer", "element")),
)
FACET_KEYS = tuple(key for _, keys in FACET_GROUPS for key in keys)
GROUP_OF = {key: group for group, keys in FACET_GROUPS for key in keys}
CHARACTERIZATION_KEYS = dict(FACET_GROUPS)["characterization"]
REF_FACETS = {
    "partType": ("partTypes",),
    "material": ("materials",),
    "colour": ("colours", "partColours"),
    "element": ("elements",),
    "layer": ("layers",),
}
COLOUR_KEY = {"all": "colour", "part": "colourPart", "material": "colourOwn"}
CHARACTERIZATION_ROLES = {
    "material": "material",
    "colour": "colour",
    "layer": "layer",
    "element": "elements",
}
TECHNIQUE_PALETTE = 10
SWATCH_FACETS = ("colour",)
LAZY_FACETS = ("part",)
PREVIEW_SIZE = 6
PLACE_DEPTH = 16
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


LAYER_KEYS = (
    "layer_canvas",
    "layer_label",
    "layer_content",
    "layer_elements",
    "layer_line",
    "layer_band_value",
    "layer_band_lower",
    "layer_band_upper",
    "layer_band_unit",
    "layer_method",
    "layer_component_index",
    "layer_inputs",
    "layer_note",
)
_unresolved_optional_warned = False


class Values:
    """Tile values of *resource_ids* for the roles *keys*, from readable nodegroups only.

    ``get`` flattens list values except references, whose list is one value;
    ``tiles`` keeps each tile's data for the roles read tile by tile
    (statements, material with its certainty), reduced to the nodes of the
    roles asked for. A role whose node is not resolved reads as empty and logs
    a warning; the layer roles are optional (a graph published before the
    imaging layers lacks them), so all of them together warn once per process.
    """

    def __init__(self, resource_ids, keys, user):
        nodes = {key: role_node(*ROLES[key]) for key in keys}
        optional = []
        for key, node in nodes.items():
            if node is not None:
                continue
            if key in LAYER_KEYS:
                optional.append(key)
            else:
                logger.warning("explorer: role %s.%s is not resolved", *ROLES[key])
        global _unresolved_optional_warned
        if optional and not _unresolved_optional_warned:
            _unresolved_optional_warned = True
            logger.warning(
                "explorer: imaging layer roles are not resolved: %s",
                ", ".join(".".join(ROLES[key]) for key in optional),
            )
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


def _ordered_refs(values):
    """The resource ids of *values* in the order stored, each once."""
    return list(
        dict.fromkeys(
            str(v.get("resourceId"))
            for v in values
            if isinstance(v, dict) and v.get("resourceId")
        )
    )


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


def place_closure(own_ids, user):
    """``(reach, parents)`` of the places *own_ids* and their ancestors.

    ``reach`` maps each own place the reader may see to the frozenset of
    itself and its visible ancestors along ``part_of_places``, at most
    ``PLACE_DEPTH`` levels up; a cycle is walked once. A place outside
    ``linkable`` (hidden, or of an unreadable model) is dropped and cuts the
    chain: what lies above it is not reached through it. ``parents`` maps
    every place of ``reach`` to its visible parent, the smallest id when
    there are several, or None. An unreadable ``part_of_places`` nodegroup
    reads as no parent. A Draft place stays visible (D50).
    """
    own = {str(i) for i in own_ids if i}
    if not own:
        return {}, {}
    parent_of = _links(*ROLES["place_parent"], readable_nodegroup_ids(user))
    seen, frontier = set(own), set(own)
    for _ in range(PLACE_DEPTH):
        frontier = {p for i in frontier for p in parent_of.get(i, ())} - seen
        if not frontier:
            break
        seen |= frontier
    shown = set(linkable(seen, user))
    reach = {}
    for place in sorted(own & shown):
        found, frontier = {place}, {place}
        for _ in range(PLACE_DEPTH):
            frontier = {
                p for i in frontier for p in parent_of.get(i, ()) if p in shown
            } - found
            if not frontier:
                break
            found |= frontier
        reach[place] = frozenset(found)
    reached = set().union(*reach.values())
    parents = {}
    for place in reached:
        above = sorted(p for p in parent_of.get(place, ()) if p in reached)
        parents[place] = above[0] if above else None
    return reach, parents


def _bound_year(value):
    return int(value[:4]) if isinstance(value, str) and value[:4].isdigit() else None


def production_tile(values, rid, prefix):
    """``(start, end, approximate)`` of the first Production tile of *rid* holding a bound, as stored, or None.

    *prefix* is ``doc`` or ``comp``; *values* read its ``_start``, ``_end``
    and ``_approx`` roles. ``type_of_production_time`` true means
    approximate, and is read from the tile that holds the bounds.
    """
    start_node, end_node = values.node(f"{prefix}_start"), values.node(f"{prefix}_end")
    approx_node = values.node(f"{prefix}_approx")
    for data in values.tiles(rid, f"{prefix}_start") or values.tiles(
        rid, f"{prefix}_end"
    ):
        start = data.get(start_node.nodeid) if start_node else None
        end = data.get(end_node.nodeid) if end_node else None
        if start or end:
            approximate = data.get(approx_node.nodeid) if approx_node else None
            return start, end, approximate is True
    return None


def _production_of(values, rid, prefix):
    """``(start year, end year, approximate)`` of the Production of *rid*, or None.

    A bound that does not start with a year is ignored; a single known
    bound stands for both.
    """
    found = production_tile(values, rid, prefix)
    if found is None:
        return None
    start, end = _bound_year(found[0]), _bound_year(found[1])
    if start is None and end is None:
        return None
    return (
        start if start is not None else end,
        end if end is not None else start,
        found[2],
    )


def production_dates(values, rid):
    """``ProductionDates`` of the document *rid* (``doc_*`` roles), or None without a bound."""
    found = production_tile(values, rid, "doc")
    if found is None:
        return None
    start, end, approximate = found
    return {
        "start": _date(start) if isinstance(start, str) else None,
        "end": _date(end) if isinstance(end, str) else None,
        "approximate": approximate,
    }


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


def row_entries(cited, part):
    """The ``characterizations`` of a row: *cited* (``value_sets`` of the identified materials it cites) with the *part* colours of its component, plus an entry without material when *part* is set and nothing is cited."""
    entries = [
        {
            **values,
            "colourPart": part,
            "colour": values["colourOwn"] | part,
        }
        for values in cited
    ]
    if part and not entries:
        entries.append(
            {
                "material": set(),
                "layer": set(),
                "element": set(),
                "colourOwn": set(),
                "colourPart": part,
                "colour": part,
            }
        )
    return entries


def _corpus_rows(user, language, visible, chains, projects_of, objects_of=None):
    """``(rows, values, parents)``: the ``corpus_rows``, per visible identified
    material ``{key: set of uris}`` of the characterization facets, and the
    ``place_closure`` parents of the places the rows carry.

    A row's ``places`` are the production places of its component and of its
    document with their visible ancestors (sorted ids); its ``periods`` hold
    the production bounds in years, the component's when it has one, else the
    document's.

    A row's ``characterizations`` hold one entry per identified material it
    cites, plus one without material when its component has a colour and
    nothing cites it; each carries ``colourOwn`` (``color_aspect`` of the
    material), ``colourPart`` (``color_features`` of the row's component) and
    their union ``colour``. A material's own values (*values*) take the
    colours of the visible components it observes (*objects_of*, read when
    omitted) as ``colourPart``.
    """
    memo = _BuildMemo(language)
    if objects_of is None:
        objects_of = _links(
            "characterization", "object_observed", readable_nodegroup_ids(user)
        )
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
    observed = {
        c: frozenset(objects_of.get(c, ())) & visible.components
        for c in visible.characterizations
    }
    parts = Values(
        {c for _, c in chains.values() if c}
        | {k for components in observed.values() for k in components},
        ["comp_type", "comp_colour"],
        user,
    )

    documents = {d for d, _ in chains.values()}
    components = {c for _, c in chains.values() if c}
    produced = {
        "doc": Values(
            documents,
            ["doc_start", "doc_end", "doc_approx", "doc_place"],
            user,
        ),
        "comp": Values(
            components,
            ["comp_start", "comp_end", "comp_approx", "comp_place"],
            user,
        ),
    }
    own_places = {
        rid: _ordered_refs(produced[prefix].get(rid, f"{prefix}_place"))
        for prefix, ids in (("doc", documents), ("comp", components))
        for rid in ids
    }
    reach, place_parents = place_closure(
        {p for found in own_places.values() for p in found}, user
    )

    produced_by_chain = {}

    def production_of(document, component):
        """``(places, periods)`` of a chain, one object shared by its rows."""
        key = (document, component)
        if key not in produced_by_chain:
            places = set()
            for own in (own_places[document], own_places.get(component, ())):
                for place in own:
                    places |= reach.get(place, set())
            period = (
                _production_of(produced["comp"], component, "comp")
                if component
                else None
            ) or _production_of(produced["doc"], document, "doc")
            produced_by_chain[key] = (
                sorted(places),
                {"production": period, "modification": None},
            )
        return produced_by_chain[key]

    def colours_of(component):
        return {
            ref["uri"]
            for v in (parts.get(component, "comp_colour") if component else [])
            for ref in memo.refs(v)
        }

    value_sets = {}
    for c in visible.characterizations:
        value_sets[c] = {
            key: {
                ref["uri"]
                for v in characterizations.get(c, role)
                for ref in memo.refs(v)
            }
            for key, role in CHARACTERIZATION_ROLES.items()
        }
        own = value_sets[c].pop("colour")
        part = set().union(*(colours_of(k) for k in observed[c]))
        value_sets[c].update(colourOwn=own, colourPart=part, colour=own | part)
    cited_by = defaultdict(list)
    for characterization, evidence in visible.evidence.items():
        for analysis in evidence:
            cited_by[analysis].append(characterization)
    operators_of = {a: _ordered_refs(values.get(a, "operators")) for a in analyses}
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
        if document not in label_of or (component and component not in label_of):
            continue
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
        if any(plots(e) for e in values.get(a, "files") if isinstance(e, dict)):
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
                "operators": [o for o in operators_of[a] if o in shown_operators],
                "materials": _unique(materials),
                "colours": _unique(colours),
                "layers": _unique(refs_of("layer")),
                "elements": _unique(refs_of("elements")),
                "characterizations": row_entries(
                    [value_sets[c] for c in cited], colours_of(component)
                ),
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
                "places": production_of(document, component)[0],
                "periods": production_of(document, component)[1],
            }
        )
    return rows, value_sets, place_parents


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
    ``colour_items`` is ``[(uri, rank)]`` of the items of the colour list, in
    the order the colour facet shows them. ``places`` maps every place the rows
    carry, ancestors included, to ``{"parent": id or None, "unpublished":
    bool}``; ``period_bounds`` holds per event the ``(min start, max end)``
    years of the dated rows, or None.
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
    colour_items: list
    places: dict
    period_bounds: dict

    @property
    def colour_ranks(self):
        """``{uri: rank}`` of ``colour_items``."""
        return dict(self.colour_items)


LINK_ROLES = {
    "part_of": ("component", "item_visual_is_part_of_document"),
    "projects": ("analysis", "analysis_by_project"),
    "samples": ("analysis", "sample_used"),
    "instruments": ("analysis", "instrument"),
    "objects": ("characterization", "object_observed"),
}


def build_bundle(user, language, visible):
    """The ``CorpusBundle`` of *user* in *language* over *visible*.

    A resource deleted while the bundle builds (``names`` no longer finds
    it) is left out with the rows that run through it; the next data
    version leaves it out of *visible* as well.
    """
    readable = readable_nodegroup_ids(user)
    links = {
        name: {
            source: frozenset(targets)
            for source, targets in _links(slug, alias, readable).items()
        }
        for name, (slug, alias) in LINK_ROLES.items()
    }
    chains = structure(visible, user, part_of=links["part_of"])
    rows, characterization_values, place_parents = _corpus_rows(
        user, language, visible, chains, links["projects"], links["objects"]
    )
    colour_items, colour_labels, colour_swatches = colour_list(language)
    label_of = names(
        {r["document"] for r in rows}
        | {r["component"] for r in rows if r["component"]}
        | visible.documents,
        language,
        user,
    )
    rows = [
        r
        for r in rows
        if r["document"] in label_of
        and (not r["component"] or r["component"] in label_of)
    ]
    documents = [d for d in visible.documents if d in label_of]
    by_document = defaultdict(list)
    for row in rows:
        by_document[row["document"]].append(row)
    folds = {}

    def folded(text):
        if text not in folds:
            folds[text] = fold(text)
        return folds[text]

    names_folded = {d: folded(label_of[d]["value"]) for d in documents}
    placed = {place for row in rows for place in row["places"]}
    drafts = unpublished_resource_ids(placed)
    produced = [r["periods"]["production"] for r in rows if r["periods"]["production"]]
    return CorpusBundle(
        visible=visible,
        chains=chains,
        links=links,
        rows=rows,
        by_id={row["id"]: row for row in rows},
        by_document=dict(by_document),
        universe=facet_universe(rows),
        labels=_with_colour_labels(_facet_labels(rows, language, user), colour_labels),
        marks={
            row["technique"]["uri"]: {
                k: row["technique"][k] for k in ("code", "colour", "family")
            }
            for row in rows
            if row["technique"]
        },
        swatches={
            **colour_swatches,
            **{uri: swatch for row in rows for uri, swatch in row["swatches"].items()},
        },
        label_of=label_of,
        folded=names_folded,
        documents=sorted(documents, key=lambda d: (names_folded[d], d)),
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
        colour_items=colour_items,
        places={
            place: {"parent": place_parents.get(place), "unpublished": place in drafts}
            for place in sorted(placed)
        },
        period_bounds={
            "production": (
                (min(p[0] for p in produced), max(p[1] for p in produced))
                if produced
                else None
            ),
            "modification": None,
        },
    )


def _with_colour_labels(labels, colour_labels):
    """*labels* as plain dicts, the ``colour`` one completed with the labels of the list items no row carries."""
    labels = {key: dict(values) for key, values in labels.items()}
    for uri, text in colour_labels.items():
        labels.setdefault("colour", {}).setdefault(uri, text)
    return labels


def colour_list(language):
    """``(items, labels, swatches)`` of the colour list of the ``color_aspect`` node.

    *items* is ``[(uri, rank)]`` in display order: the concepts of
    ``SWATCH_ORDER`` first, then the others by the list's ``sortorder``;
    *labels* and *swatches* are by uri. All empty when the node has no list.
    """
    index = GraphIndex.for_slug("characterization")
    list_id = index.lists.get("color_aspect") if index else None
    if not list_id:
        return [], {}, {}
    items = list(
        ListItem.objects.filter(list_id=list_id).values_list("id", "uri", "sortorder")
    )
    entries = defaultdict(list)
    for item, valuetype, lang, value in ListItemValue.objects.filter(
        list_item_id__in=[i for i, _, _ in items]
    ).values_list("list_item_id", "valuetype_id", "language_id", "value"):
        entries[item].append(
            {"value": value, "valuetype_id": valuetype, "language_id": lang}
        )
    known = sorted(
        (colour_rank(uri), uri) for _, uri, _ in items if colour_rank(uri) is not None
    )
    other = sorted(
        (order or 0, uri) for _, uri, order in items if colour_rank(uri) is None and uri
    )
    ranked = [(uri, rank) for rank, uri in known] + [
        (uri, len(SWATCH_ORDER) + position) for position, (_, uri) in enumerate(other)
    ]
    labels, swatches = {}, {}
    for item, uri, _ in items:
        if not uri:
            continue
        prefs = {
            e["language_id"]: e["value"]
            for e in entries[item]
            if e["valuetype_id"] == "prefLabel" and e["value"]
        }
        labels[uri] = label(prefs, language) or {"value": uri, "lang": language}
        swatch = colour_swatch({"uri": uri, "labels": entries[item]})
        if swatch:
            swatches[uri] = swatch
    return ranked, labels, swatches


def corpus_bundle(user, language, ticket=None):
    """The memoised ``CorpusBundle`` of *user* in *language* (``explorer.memo``).

    *ticket* is the ``explorer.memo.ticket`` the caller already read.
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
    documents without analyses. ``colour`` is the union of the ``colour`` and
    ``partColour`` values: ``partColour`` is the alias of the two colour facets
    merged in 2026-10, still read for one release. ``colourScope`` is ``part``
    or ``material``, else ``all``.
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
    filters["colour"] = sorted(
        set(filters["colour"])
        | {
            v.strip()
            for raw in query.getlist("partColour")
            for v in raw.split(",")
            if v.strip()
        }
    )
    filters["colourScope"] = (
        query.get("colourScope") if query.get("colourScope") in COLOUR_KEY else "all"
    )
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
    return list(
        dict.fromkeys(ref["uri"] for field in REF_FACETS[key] for ref in row[field])
    )


def _facet_labels(rows, language, user):
    labels = defaultdict(dict)
    for row in rows:
        if row["technique"]:
            labels["technique"][row["technique"]["uri"]] = row["technique"]["label"]
        for key, fields in REF_FACETS.items():
            for field in fields:
                for ref in row[field]:
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


def characterization_wanted(active, skip=None, scope="all"):
    """``[(key read, selected uris)]`` of the active facets of the characterization group, *skip* left out.

    The key read is the facet key, except for ``colour``: ``COLOUR_KEY[scope]``.
    """
    return [
        (COLOUR_KEY[scope] if key == "colour" else key, set(active[key]))
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

    scope = filters["colourScope"]

    def meeting(row, skip):
        wanted = characterization_wanted(active, skip, scope)
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
        if key not in CHARACTERIZATION_KEYS:
            return set(_facet_values(row, key))
        read = COLOUR_KEY[scope] if key == "colour" else key
        found = meeting(row, key)
        if found is None and key != "colour":
            return set(_facet_values(row, key))
        if found is None:
            found = row["characterizations"]
        return set().union(*(c[read] for c in found))

    return keep, active, filters, page, needle, universe, carried


def facet_entry(
    key,
    rows,
    active,
    counted,
    labels,
    marks,
    swatches,
    offered,
    ranks=None,
    complete=False,
):
    """One ``Facet`` over *rows*: the values of *offered* with a count and the selected ones.

    Counts are "open to the other selections" (``counted``, the ``carried`` of
    ``row_filter``). A selected value is listed at count 0 when no row counts
    for it. Values are in label order, years in numeric order; ``total`` is
    the number of values. ``colour`` is in the fixed order of ``colour_order``
    (*ranks*); with *complete*, every offered value is listed, at count 0 when
    no row counts for it.
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
        if complete or counts[v] > 0 or v in active[key]
    ]
    if key == "colour":
        order = colour_order(ranks or {})
        values.sort(key=lambda item: order(item["id"], item["label"]["value"]))
    else:
        values.sort(
            key=(
                (lambda item: item["id"])
                if key == "year"
                else (lambda item: (fold(item["label"]["value"]), item["id"]))
            )
        )
    return {"key": key, "group": GROUP_OF[key], "values": values, "total": len(values)}


def colour_order(ranks):
    """Sort key ``(uri, label) -> tuple`` of the colour facet: the colours of the list by *ranks*, else by ``SWATCH_ORDER``, the rest by label."""

    def order(uri, text):
        rank = ranks.get(uri)
        if rank is None:
            rank = colour_rank(uri)
        return (0, rank, "", uri) if rank is not None else (1, 0, fold(text), uri)

    return order


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


def offered_values(bundle, key):
    """The values a corpus facet offers: the universe, and for ``colour`` every item of its list as well."""
    if key == "colour":
        return bundle.universe[key] | set(bundle.colour_ranks)
    return bundle.universe[key]


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
            offered_values(bundle, key),
            bundle.colour_ranks,
            complete=key == "colour",
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
        bundle.colour_ranks,
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
            offered_values(bundle, key),
            bundle.colour_ranks,
            complete=key == "colour",
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
    keep, active, filters, _, needle, _, counted = row_filter(
        rows, query, universe=bundle.universe
    )
    facets = [
        facet
        for key in FACET_KEYS
        if (facet := document_facet(key, bundle, rows, active, counted))
    ]
    kept = sorted(row["id"] for row in rows if keep(row))
    filtered = bool(needle) or any(active.values())
    wanted = characterization_wanted(active, scope=filters["colourScope"])
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
            "doc_approx",
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
    hits = []
    for d in document_ids:
        dates = production_dates(values, d)
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


QUALIFIERS = {"material": "confidence", "elements": "element_level"}


def qualified_values(values, ids, language):
    """The ``material`` and ``elements`` tiles of the identified materials *ids*, each with its qualifier.

    ``{id: {key: [(refs, stored, qualifier), …]}}`` in tile order, for each
    key of ``QUALIFIERS``: *refs* are the ``value_refs`` of the tile's node
    (a tile without any is left out), *stored* the stored value, and
    *qualifier* the first value of the tile's ``confidence`` or
    ``element_level`` node as a ``RankedValue`` (rank = ``sortorder`` of its
    list item, 0 when the item is unknown), else None. *values* holds the
    roles of both.
    """
    found = {}
    for c in ids:
        found[c] = {}
        for key, qualifier_key in QUALIFIERS.items():
            node, qualifier = values.node(key), values.node(qualifier_key)
            tiles = []
            for data in values.tiles(c, key):
                stored = data.get(node.nodeid) if node else None
                refs = value_refs(stored, language)
                if not refs:
                    continue
                first = (
                    value_refs(data.get(qualifier.nodeid), language)[:1]
                    if qualifier
                    else []
                )
                tiles.append((refs, stored, first[0] if first else None))
            found[c][key] = tiles
    ranks = _ranks(
        {
            q["id"]
            for per_key in found.values()
            for tiles in per_key.values()
            for _, _, q in tiles
            if q
        }
    )
    return {
        c: {
            key: [
                (refs, stored, {**q, "rank": ranks.get(q["id"], 0)} if q else None)
                for refs, stored, q in tiles
            ]
            for key, tiles in per_key.items()
        }
        for c, per_key in found.items()
    }


def characterization_summaries(
    ids, visible, user, language, source=None, objects_of=None, analysis_rows=None
):
    """``CharacterizationSummary`` of the visible identified materials among *ids*.

    ``zone`` is the first zone placing the material on the canvases of
    *source* (``iiif.facts.listed_source`` of its document's manifest) by
    ``iiif.facts.CharacterizationZones``; without *source* it is None.
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
    authors_of = {c: _ordered_refs(values.get(c, "ch_authors")) for c in ids}
    shown_authors = set(linkable({a for v in authors_of.values() for a in v}, user))
    authors = {c: [a for a in authors_of[c] if a in shown_authors] for c in ids}
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
    placed = (
        CharacterizationZones(ids, visible, readable).sourced(ids, source)
        if source is not None
        else {}
    )
    qualified = qualified_values(values, ids, language)
    summaries = []
    for c in ids:
        materials = [
            {"value": ref, "confidence": confidence, "proportion": None}
            for refs, _, confidence in qualified[c]["material"]
            for ref in refs
        ]
        elements = [
            {"level": level, "values": refs}
            for refs, _, level in qualified[c]["elements"]
        ]
        origin, zones = placed.get(c, (None, None))
        zone = (
            {"canvas": zones[0].canvas, "shape": zones[0].shape, "source": origin}
            if zones
            else None
        )
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
                        for r in colour_refs(v, language)
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
    zones = first_zone(role_node(*ROLES["sample_zone"]), ids, dims, readable)
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


def component_zones(document_id, bundle, dims, position, readable):
    """``{component id: [AnalysisZone, …]}`` of the visible Components of *document_id* placed on a canvas of its manifest.

    A Component belongs to the document through a readable
    ``item_visual_is_part_of_document`` link; its zones are read off
    ``location_in_document`` as analysis zones are, by page then feature id.
    A Component without a zone on a listed canvas is left out.
    """
    ids = sorted(
        c
        for c, documents in bundle.links["part_of"].items()
        if document_id in documents and c in bundle.visible.components
    )
    zones = defaultdict(list)
    for component, feature, canvas, shape in annotation_features(
        role_node(*ROLES["comp_zone"]), ids, dims, readable
    ):
        if canvas in position:
            zones[component].append(
                {"canvas": position[canvas], "shape": shape, "feature": feature}
            )
    return {c: sorted(z, key=lambda zone: zone["canvas"]) for c, z in zones.items()}


def history_of(values, document_id, places, label_of):
    """The ``HistoryLine`` list of a document: its Production, or none without a bound or a place.

    *places* are the production places a reference may show, in stored
    order; *label_of* names them.
    """
    dates = production_dates(values, document_id)
    if dates is None and not places:
        return []
    return [
        {
            "type": "production",
            "places": [{"id": p, "name": label_of[p]} for p in places if p in label_of],
            "date": dates or {"start": None, "end": None, "approximate": False},
        }
    ]


def document_payload(document_id, user, language, ticket=None):
    """``DocumentPayload`` of a visible document, the same whatever the filters; None when it is unknown or not visible.

    ``techniques`` holds each technique of its analyses by uri; each analysis
    names its technique by that uri and lists its zones, each on a canvas
    given by its position in ``canvases`` and named by its ``feature`` id.
    A zone on a canvas the manifest does not list is left out; an analysis
    without zones is not located on a page. ``components`` lists the visible
    Components placed on its pages (``component_zones``), by first page then
    name. ``document_match`` says what the filters keep. ``history`` holds
    the document's Production line when it has a bound or a place a linked
    reference may show (a Draft place included, a hidden one left out).
    """
    bundle = corpus_bundle(user, language, ticket)
    visible = bundle.visible
    document_id = str(document_id)
    if document_id not in visible.documents:
        return None
    rows = bundle.by_document.get(document_id, [])
    readable = readable_nodegroup_ids(user)
    values = Values(
        [document_id],
        [
            "doc_name",
            "doc_manifest",
            "doc_owner",
            "doc_start",
            "doc_end",
            "doc_approx",
            "doc_place",
        ],
        user,
    )
    manifest_url = (
        rewrite_legacy_url(values.first(document_id, "doc_manifest") or "") or None
    )
    canvases = canvases_of(manifest_json(manifest_url)) if manifest_url else []
    dims = canvas_index(canvases)
    position = {canvas["id"]: index for index, canvas in enumerate(canvases)}
    zones = defaultdict(list)
    for analysis, feature, canvas, shape in annotation_features(
        role_node(*ROLES["zone"]), [row["id"] for row in rows], dims, readable
    ):
        if canvas in position:
            zones[analysis].append(
                {"canvas": position[canvas], "shape": shape, "feature": feature}
            )
    placed = component_zones(document_id, bundle, dims, position, readable)
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
        listed_source(manifest_url or "", canvases),
        objects_of=bundle.links["objects"],
        analysis_rows=bundle.by_id,
    )
    shown = set(linkable(_resource_refs(values.get(document_id, "doc_owner")), user))
    owners = [
        str(v.get("resourceId"))
        for v in values.get(document_id, "doc_owner")
        if isinstance(v, dict) and str(v.get("resourceId")) in shown
    ]
    produced = _ordered_refs(values.get(document_id, "doc_place"))
    shown_places = set(linkable(produced, user))
    produced_at = [p for p in produced if p in shown_places]
    label_of = names(
        {document_id} | set(owners[:1]) | set(placed) | set(produced_at), language, user
    )
    components = sorted(
        (c for c in placed if c in label_of),
        key=lambda c: (placed[c][0]["canvas"], fold(label_of[c]["value"]), c),
    )
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
        "components": [
            {"id": c, "name": label_of[c], "zones": placed[c]} for c in components
        ],
        "characterizations": summaries,
        "history": history_of(values, document_id, produced_at, label_of),
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


FILE_KEYS = ("files", "micro", "imaging", *LAYER_KEYS)


def _text(value):
    """The stripped text of a string value (plain or localized), None when empty."""
    texts = string_texts(value)
    text = next((t.strip() for t in texts.values() if t and t.strip()), "")
    return text or None


def _number(value):
    return value if isinstance(value, (int, float)) else None


def _only(refs):
    return refs[0] if refs else None


def _layer_tiles(values, analysis_id):
    """``{canvas id: {role: value}}`` of the imaging layer tiles of an analysis.

    The canvas id is passed through ``rewrite_legacy_url``, as ``canvases_of``
    does for the manifest's; the first tile wins a canvas. Empty when the
    layer nodegroup is unreadable or unresolved.
    """
    nodes = {key: values.node(key) for key in LAYER_KEYS}
    if nodes["layer_canvas"] is None:
        return {}
    found = {}
    for data in values.tiles(analysis_id, "layer_canvas"):
        canvas = data.get(nodes["layer_canvas"].nodeid)
        if isinstance(canvas, str) and canvas.strip():
            found.setdefault(
                rewrite_legacy_url(canvas.strip()),
                {
                    key: data.get(node.nodeid)
                    for key, node in nodes.items()
                    if node is not None
                },
            )
    return found


def layer_of(index, text, image, canvas_id="", fields=None, language="en"):
    """One image layer of an imaging manifest, as ``FileLayer`` states it.

    Its position, its canvas id, its label as stored and its image; the rest
    comes from *fields*, the ``{role: value}`` of the layer tile of that
    canvas. Without a tile the layer is unclassified.
    """
    fields = fields or {}
    elements = fields.get("layer_elements")
    unit = _only(value_refs(fields.get("layer_band_unit"), language))
    method = _only(value_refs(fields.get("layer_method"), language))
    band = {
        "value": _number(fields.get("layer_band_value")),
        "lower": _number(fields.get("layer_band_lower")),
        "upper": _number(fields.get("layer_band_upper")),
        "unit": (
            {**unit, "symbol": acronym(fields.get("layer_band_unit"))} if unit else None
        ),
    }
    processing = {
        "method": (
            {**method, "symbol": acronym(fields.get("layer_method"))}
            if method
            else None
        ),
        "index": _number(fields.get("layer_component_index")),
        "inputs": _text(fields.get("layer_inputs")),
    }
    return {
        "index": index,
        "id": canvas_id,
        "label": (text or "").strip(),
        "image": image,
        "content": _only(value_refs(fields.get("layer_content"), language)),
        "elements": [
            {"value": ref, "symbol": symbol}
            for ref, symbol in zip(
                value_refs(elements, language), element_symbols(elements)
            )
        ],
        "emissionLine": _only(value_refs(fields.get("layer_line"), language)),
        "band": band if any(v is not None for v in band.values()) else None,
        "processing": (
            processing if any(v is not None for v in processing.values()) else None
        ),
        "note": _text(fields.get("layer_note")),
    }


def imaging_entries(
    analysis_id, manifest_values, language, read=None, layer_tiles=None
):
    """``FileEntry`` of each imaging manifest of an analysis (maXRF, hyperspectral, other); its canvases are the layers, numbered across manifests.

    *read* reads a manifest by URL: a caller's memoised reader, else
    ``manifest_json``. *layer_tiles* is ``_layer_tiles`` of the analysis; a
    canvas without a tile is an unclassified layer.
    """
    read = read or manifest_json
    layer_tiles = layer_tiles or {}
    entries, index = [], 0
    for position, value in enumerate(manifest_values):
        url = rewrite_legacy_url(
            value if isinstance(value, str) else (value or {}).get("url", "")
        )
        if not url:
            continue
        manifest = read(url) or {}
        layers = []
        for canvas in canvases_of(manifest):
            layers.append(
                layer_of(
                    index,
                    canvas["label"],
                    canvas["image"],
                    canvas["id"],
                    layer_tiles.get(canvas["id"]),
                    language,
                )
            )
            index += 1
        entries.append(
            {
                "id": f"{analysis_id}:imaging:{position}",
                "name": canvas_label(manifest.get("label")) or url.rsplit("/", 1)[-1],
                "size": None,
                "format": "application/ld+json",
                "role": "other",
                "pairedWith": None,
                "dataKind": "chemical-imaging",
                "viewer": {
                    "rendererConfigId": None,
                    "presetKey": None,
                    "configName": None,
                    "xLabel": None,
                    "yLabel": None,
                    "axisKey": None,
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
    """``{config id: StoredConfig}`` of the renderer configurations the measurement files of *analysis_ids* name, in one query."""
    config_ids = {
        e.get("rendererConfig")
        for analysis_id in analysis_ids
        for e in values.get(analysis_id, "files")
        if isinstance(e, dict) and e.get("rendererConfig")
    }
    if not config_ids:
        return {}
    return {
        str(config_id): StoredConfig(config, name)
        for config_id, config, name in RendererConfig.objects.filter(
            configid__in=list(config_ids)
        ).values_list("configid", "config", "name")
    }


def analysis_files(analysis_id, user, language, values=None, configs=None, read=None):
    """Every file of an analysis as ``FileEntry``: measurements, micro-imaging, chemical imaging.

    *values* and *configs* (``renderer_configs``) let a caller with several
    analyses share one batched tile lookup and one configuration lookup
    instead of one of each per analysis; *read* reads the imaging manifests
    (``imaging_entries``).
    """
    if values is None:
        values = Values([analysis_id], FILE_KEYS, user)
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
        + imaging_entries(
            analysis_id,
            values.get(analysis_id, "imaging"),
            language,
            read,
            _layer_tiles(values, analysis_id),
        )
    )


def report_url(resource_id, language):
    """Path of the Arches report of *resource_id* on this site, in *language*."""
    with translation.override(language):
        return reverse("resource_report", kwargs={"resourceid": resource_id})


def permalink(resource_id):
    """Absolute URL of the Arches report of *resource_id*, as citations and exports name it."""
    return f"{settings.PUBLIC_SERVER_ADDRESS}report/{resource_id}"


MULTILINGUAL_PRODUCTS = frozenset({"iiif-v3-explorer-manifest"})


def product_path(route, query, language):
    """Path on this site of the language-neutral product *route* for the scope *query* in *language*.

    *query* is an URL-encoded ``ExportScope.query`` (``ids=…``,
    ``document=…``, ``project=…`` and their flags); ``lang`` is appended,
    except to a product carrying every language (``MULTILINGUAL_PRODUCTS``).
    """
    if route in MULTILINGUAL_PRODUCTS:
        return f"{reverse(route)}?{query}"
    return f"{reverse(route)}?{query}&{urlencode({'lang': language})}"


def product_url(route, query, language):
    """Absolute URL of ``product_path``, as a copied link, an external viewer or an IIIF id names it."""
    return f"{settings.PUBLIC_SERVER_ADDRESS}{product_path(route, query, language).lstrip('/')}"


def product_link(route, query, language):
    """``ProductLink`` of ``product_path``: its ``path`` for a link followed on this site, its ``url`` for what leaves it."""
    path = product_path(route, query, language)
    return {"url": f"{settings.PUBLIC_SERVER_ADDRESS}{path.lstrip('/')}", "path": path}


def cited_analysis(row, end, label_of, operators, projects, slug_of):
    """``CitedAnalysis`` of a corpus *row*; *operators* and *projects* are the ids the citation may name.

    Operators are cited in the order given. Only a Person (*slug_of* model
    ``person``) is split into family and given name at its comma; a Group or a
    Project name is cited literally.
    """
    return CitedAnalysis(
        id=row["id"],
        name=row["name"]["value"],
        permalink=permalink(row["id"]),
        start=row["date"],
        end=end,
        authors=tuple(
            (
                person_name(label_of[o]["value"])
                if slug_of.get(o) == "person"
                else {"literal": label_of[o]["value"].strip()}
            )
            for o in operators
            if o in label_of
        ),
        projects=tuple(label_of[p]["value"] for p in projects if p in label_of),
    )


def licence_labels(files):
    """Labels of the licences of *files* (``FileEntry``), in file order."""
    return [f["license"]["label"]["value"] for f in files if f.get("license")]


def _analysis_manifest(analysis_id, language):
    """The URL of the Explorer manifest of one analysis, or None when that manifest holds no canvas or is over the canvas bound (``manifest_offer``)."""
    from manuspectrum.views.explorer.manifest import manifest_offer
    from manuspectrum.views.explorer.scopes import resolve_scope

    query = f"ids=an:{analysis_id}:-"
    scope = resolve_scope(QueryDict(query), language)
    if scope is None or manifest_offer(scope) != "manifest":
        return None
    return product_url("iiif-v3-explorer-manifest", query, language)


def content_states(analysis_id, document_id, user):
    """``ContentStateLink`` of each zone of *analysis_id* on a canvas of its document's manifest, in feature order.

    ``url`` is the absolute IIIF id. Zones are read from the nodegroups *user*
    may read; a zone on a canvas the manifest does not list has none.
    """
    values = Values([document_id], ["doc_manifest"], user)
    url = rewrite_legacy_url(values.first(document_id, "doc_manifest") or "")
    canvases = canvases_of(manifest_json(url)) if url else []
    listed = {canvas["id"] for canvas in canvases}
    features = sorted(
        {
            feature
            for _, feature, canvas, _ in annotation_features(
                role_node(*ROLES["zone"]),
                [analysis_id],
                canvas_index(canvases),
                readable_nodegroup_ids(user),
            )
            if canvas in listed and feature
        }
    )
    return [
        {"feature": feature, "url": content_state_url(analysis_id, feature)}
        for feature in features
    ]


def analysis_payload(analysis_id, user, language):
    """``AnalysisPayload`` of a visible analysis; None when it is unknown or not visible.

    A linked resource that no longer exists is left out of the references.
    ``manifest`` is None when the analysis places no canvas;
    ``contentStates`` lists the published Content State of each of its
    located zones (``content_states``), none without a manifest.
    """
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

    def ref(rid):
        if rid not in label_of:
            return None
        return {"id": rid, "model": slug_of.get(rid, ""), "name": label_of[rid]}

    def refs(rids):
        return [r for r in map(ref, rids) if r]

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
    manifest = _analysis_manifest(analysis_id, language)
    dataset = dataset_of(values.first(analysis_id, "dataset"))
    citation = citation_entry(
        dataset,
        [cited_analysis(row, end, label_of, row["operators"], projects, slug_of)],
        licences=licence_labels(files),
        language=language,
        accessed=datetime.date.today(),
    )
    return {
        "id": analysis_id,
        "name": row["name"],
        "technique": row["technique"],
        "instrument": ref(instruments[0]) if instruments else None,
        "operators": refs(row["operators"]),
        "projects": refs(projects),
        "date": {
            "start": row["date"],
            "end": end,
        },
        "document": ref(document),
        "component": ref(component) if component else None,
        "sample": ref(samples[0]) if samples else None,
        "files": files,
        "conditions": conditions,
        "evidenceOf": [
            {"id": c, "name": label_of[c]} for c in cited_by if c in label_of
        ],
        "dataset": dataset,
        "bibliography": [
            t
            for t in (
                label(string_texts(v), language)
                for v in values.get(analysis_id, "bibliography")
            )
            if t
        ],
        "citation": shown_citation(citation),
        "availability": citation["availability"],
        "manifest": manifest,
        "contentStates": (
            content_states(analysis_id, document, user) if manifest else []
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
    ``ch:<characterization>:-`` an identified material, its ``zone`` None:
    a Selection names no document to place it on.
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
            objects_of=bundle.links["objects"],
            analysis_rows=rows,
        )
    }
    file_ids = sorted(
        {m.group(2) for _, m in parsed if m and m.group(1) in ("an", "af", "im")}
        & set(rows)
    )
    shared_values = Values(file_ids, FILE_KEYS, user) if file_ids else None
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
                rid,
                user,
                language,
                values=shared_values,
                configs=shared_configs,
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
