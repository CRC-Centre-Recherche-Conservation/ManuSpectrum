"""Introspection of Arches resource graphs into a graph-explorer JSON payload.

Pure helpers (DB-free) are unit-tested; build_model_graph() reads the ORM and is
verified against the dev database. Keep it lean — this feeds a cached endpoint.
"""

import re

from django.conf import settings
from django.db.models import Count
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

# The four atelier "carte des ressources" groupings, keyed by graph slug.
GROUPS = [
    {
        "id": "studied-object",
        "label_en": "Studied object",
        "label_fr": "Objet étudié",
        "color": "#3b82f6",
    },
    {
        "id": "observation",
        "label_en": "Observation · CRMsci",
        "label_fr": "Observation · CRMsci",
        "color": "#10b981",
    },
    {
        "id": "context",
        "label_en": "Shared context",
        "label_fr": "Contexte commun",
        "color": "#8b5cf6",
    },
    {
        "id": "transformations",
        "label_en": "Transformations",
        "label_fr": "Transformations subies",
        "color": "#e67e22",
    },
    {"id": "other", "label_en": "Other", "label_fr": "Autre", "color": "#94a3b8"},
]

_SLUG_TO_GROUP = {
    "document": "studied-object",
    "component": "studied-object",
    "sample": "studied-object",
    "analysis": "observation",
    "characterization": "observation",
    "person": "context",
    "place": "context",
    "project": "context",
    "instrument": "context",
    "group": "context",
    "alteration": "transformations",
    "modification": "transformations",
}

# Stable per-datatype colors for the "Datatypes" view / field chips.
DATATYPE_COLORS = {
    "string": "#3b82f6",
    "concept": "#8b5cf6",
    "concept-list": "#7c3aed",
    "resource-instance": "#e67e22",
    "resource-instance-list": "#d97706",
    "number": "#10b981",
    "date": "#0ea5e9",
    "boolean": "#64748b",
    "domain-value": "#f0b429",
    "domain-value-list": "#eab308",
    "geojson-feature-collection": "#14b8a6",
    "file-list": "#ef4444",
    "url": "#06b6d4",
    "node-value": "#a855f7",
    "annotation": "#f97316",
    "edtf": "#0ea5e9",
    "semantic": "#cbd5e1",
    "non-localized-string": "#60a5fa",
    "reference": "#9333ea",
    "language": "#84cc16",
    # Custom project datatypes (DATATYPE_LOCATIONS -> manuspectrum/datatypes/).
    "manifest": "#ec4899",
}
_DATATYPE_FALLBACK = "#94a3b8"

# Scratch/system graphs that must never appear in the public explorer.
# Matched EXACTLY (not by substring) so a real future model whose name merely
# contains "test" is never silently hidden.
EXCLUDED_GRAPH_SLUGS = {
    "test_ressource",
    "test-ressource",
    "test_resource",
    "test-resource",
}
EXCLUDED_GRAPH_NAMES = {"test ressource", "test resource"}

# Human, translatable labels for the datatypes shown in the "Datatypes" chart.
# gettext_lazy at module level (import time has no active language); resolved to
# a real str per request inside `with translation.override(language)` — see the
# str() at the build site. Complete on purpose: the old `.title()` fallback only
# ever produced English, so FR pages showed "Concept List", "Resource Instance"…
# next to French axes.
DATATYPE_LABELS = {
    "string": _("String"),
    "concept": _("Concept"),
    "concept-list": _("Concept List"),
    "resource-instance": _("Resource Instance"),
    "resource-instance-list": _("Resource Instance List"),
    "number": _("Number"),
    "date": _("Date"),
    "boolean": _("Boolean"),
    "domain-value": _("Domain Value"),
    "domain-value-list": _("Domain Value List"),
    "geojson-feature-collection": _("GeoJSON Feature Collection"),
    "file-list": _("File List"),
    "url": _("URL"),
    "node-value": _("Node Value"),
    "annotation": _("Annotation"),
    "edtf": _("EDTF"),
    "non-localized-string": _("Non-localized String"),
    "reference": _("Reference"),
    "language": _("Language"),
    "manifest": _("IIIF Manifest"),
}


def datatype_color(datatype):
    return DATATYPE_COLORS.get(datatype, _DATATYPE_FALLBACK)


def prettify_cidoc(uri):
    """'…/E22_Human-Made_Object' -> 'E22 Human-Made Object'."""
    if not uri:
        return ""
    tail = str(uri).rstrip("/").split("/")[-1]
    if "_" in tail:
        code, _, rest = tail.partition("_")
        return f"{code} {rest.replace('_', ' ')}"
    return tail


_P_CODE = re.compile(r"\bP\d+[a-z]?", re.IGNORECASE)


def property_code(prettified):
    """'P98i was born' -> 'P98i'. Precomputed so the client runs no regex per edge."""
    m = _P_CODE.search(str(prettified or ""))
    return m.group(0) if m else ""


def skip_from_counts(datatype, istopnode):
    """The ONE rule that keeps `stats.nodes` at 452 and `stats.nodegroups` at 169.

    A graph's top node is a synthetic `semantic` root that models the resource
    itself, not a field anyone fills in. It is excluded from `ng_map`, from
    `datatype_hist` and from every published count — but it IS emitted as the
    root of the `structure` tree, because a tree needs a root. Those two facts
    must stay independently true; see `tests/test_model_graph.py`.
    """
    return datatype == "semantic" and bool(istopnode)


def structure_depths(parent_of):
    """{nodeid: parent|None} -> {nodeid: hops from root}. Memoised, cycle-safe.

    Every ManuSpectrum graph is a verified strict tree (edges == nodes - 1, one
    root), so the cycle guard should never fire — but a corrupt Edge table must
    degrade to a flat drawing, never to a hung request.
    """
    depths = {}

    def walk(nid, seen):
        if nid in depths:
            return depths[nid]
        parent = parent_of.get(nid)
        if parent is None or parent not in parent_of or parent in seen:
            depths[nid] = 0
        else:
            depths[nid] = walk(parent, seen | {nid}) + 1
        return depths[nid]

    for nid in parent_of:
        walk(nid, frozenset())
    return depths


def finalize_structure(nodes, parent_of, ng_meta):
    """Attach parent/depth/cardinality to a graph's structure nodes.

    `nodes` are partially-built dicts (id/name/datatype/... already set);
    `parent_of` maps nodeid -> parent nodeid or None; `ng_meta` maps nodegroupid
    -> {"cardinality", "parent_nodegroup"}. Pure — unit-tested without the ORM.
    """
    depths = structure_depths(parent_of)
    root = None
    for nd in nodes:
        nid = nd["id"]
        nd["parent"] = parent_of.get(nid)
        nd["depth"] = depths.get(nid, 0)
        meta = ng_meta.get(nd.get("nodegroup") or "") or {}
        nd["cardinality"] = meta.get("cardinality")
        nd["parent_nodegroup"] = meta.get("parent_nodegroup")
        if nd["parent"] is None and root is None:
            root = nid
    # Deterministic order: a public payload people diff and cite must not depend
    # on the database's row order.
    nodes.sort(key=lambda n: (n["depth"], n["name"], n["id"]))
    return {"root": root, "nodes": nodes}


def group_for_slug(slug):
    return _SLUG_TO_GROUP.get((slug or "").lower(), "other")


def trim_node_config(datatype, config):
    """Return only display-relevant config keys (never dump raw config)."""
    cfg = dict(config) if isinstance(config, dict) else {}
    out = {}
    if datatype in ("resource-instance", "resource-instance-list"):
        graphs = cfg.get("graphs") or []
        out["target_graphs"] = [
            str(g.get("graphid"))
            for g in graphs
            if isinstance(g, dict) and g.get("graphid")
        ]
    elif datatype in ("concept", "concept-list"):
        coll = cfg.get("rdmCollection")
        if coll:
            out["collection"] = str(coll)
    return out


def draft_state_ids(lifecycle_states):
    """IDs of the lifecycle states that mean "not published yet".

    A state is a draft gate when it is the *initial* state of a lifecycle that
    has more than one state; single-state lifecycles publish immediately, so
    their initial state is NOT a draft. Flag-based on purpose: state names are
    I18n_String and matching "Draft" would break under localisation.

    ``lifecycle_states`` is an iterable of dicts with keys ``id``,
    ``is_initial_state`` and ``resource_instance_lifecycle_id`` (the shape of
    a ``.values()`` query), so the rule stays unit-testable without the ORM.
    """
    states = list(lifecycle_states)
    per_lifecycle = {}
    for s in states:
        lc = s["resource_instance_lifecycle_id"]
        per_lifecycle[lc] = per_lifecycle.get(lc, 0) + 1
    return {
        s["id"]
        for s in states
        if s["is_initial_state"]
        and per_lifecycle[s["resource_instance_lifecycle_id"]] > 1
    }


def _excluded_graph_ids():
    """Graph ids to always drop from the explorer payload.

    `SYSTEM_SETTINGS_RESOURCE_MODEL_ID` is NOT a Django `settings.py` value —
    it lives as a class attribute on `arches.app.models.system_settings.
    SystemSettings`. `getattr(settings, ...)` looks in the wrong place and
    silently no-ops, so import it directly (no instantiation, no DB hit).
    """
    from arches.app.models.system_settings import SystemSettings

    ids = set()
    sysid = getattr(settings, "SYSTEM_SETTINGS_RESOURCE_MODEL_ID", None) or getattr(
        SystemSettings, "SYSTEM_SETTINGS_RESOURCE_MODEL_ID", None
    )
    if sysid:
        ids.add(str(sysid))
    return ids


def build_model_graph(language="en"):
    """Introspect resource graphs into the explorer payload (see spec)."""
    from arches.app.models.models import (
        CardXNodeXWidget,
        Concept,
        GraphModel,
        Node,
        NodeGroup,
        Edge,
        ResourceInstance,
        ResourceInstanceLifecycleState,
    )

    excluded = _excluded_graph_ids()

    with translation.override(language):
        graphs = list(
            GraphModel.objects.filter(isresource=True, publication__isnull=False)
        )
        graphs = [
            g
            for g in graphs
            if str(g.graphid) not in excluded
            and (g.slug or "").strip().lower() not in EXCLUDED_GRAPH_SLUGS
            and str(g.name).strip().lower() not in EXCLUDED_GRAPH_NAMES
        ]
        graph_ids = [g.graphid for g in graphs]
        id_str = {str(g.graphid) for g in graphs}

        # Live instance counts per graph (cheap COUNT … GROUP BY). Grouping by
        # lifecycle state too lets us split published vs draft in Python with
        # the SAME single query — the public "records" figures must not count
        # resources still behind the draft gate (WAVE 5: 147 shown, 19 drafts).
        drafts = draft_state_ids(
            ResourceInstanceLifecycleState.objects.values(
                "id", "is_initial_state", "resource_instance_lifecycle_id"
            )
        )
        counts, draft_counts = {}, {}
        for row in (
            ResourceInstance.objects.filter(graph_id__in=graph_ids)
            .values("graph_id", "resource_instance_lifecycle_state_id")
            .order_by()
            .annotate(n=Count("resourceinstanceid"))
        ):
            gid = str(row["graph_id"])
            bucket = (
                draft_counts
                if row["resource_instance_lifecycle_state_id"] in drafts
                else counts
            )
            bucket[gid] = bucket.get(gid, 0) + row["n"]

        # Edge lookups, both keyed by the RANGE node (an Arches graph is a tree,
        # so every non-root node is the range of exactly one edge):
        #   edge_prop   -> the ontology property that links it to its parent
        #   edge_parent -> the parent nodeid itself
        # `domainnode_id` costs nothing here — it is already in the row being
        # fetched, it was simply being discarded. The whole `structure` tree
        # therefore adds ZERO queries beyond the NodeGroup metadata below.
        edge_prop, edge_parent = {}, {}
        for e in Edge.objects.filter(graph_id__in=graph_ids).values(
            "rangenode_id", "domainnode_id", "ontologyproperty"
        ):
            rid = str(e["rangenode_id"])
            edge_prop[rid] = e["ontologyproperty"]
            edge_parent[rid] = str(e["domainnode_id"])

        all_nodes = list(Node.objects.filter(graph_id__in=graph_ids))

        # Localised field labels. Node.name is NOT localizable in Arches core;
        # the curated, per-language labels live on the card/widget rows (and
        # were translated via `i18n loadmessages`). Prefer them when present —
        # this is also what the Arches data-entry forms display.
        widget_labels = {}
        for row in CardXNodeXWidget.objects.filter(
            node_id__in=[n.nodeid for n in all_nodes]
        ).values("node_id", "label"):
            raw = row["label"]
            if raw is None:
                continue
            if isinstance(raw, dict):
                lbl = (
                    raw.get(language)
                    or raw.get(language.split("-")[0])
                    or raw.get("en")
                )
            else:
                # .values() still applies from_db_value, so this is an
                # I18n_String — str() resolves it in the ACTIVE language
                # (we are inside translation.override(language)).
                lbl = str(raw)
            lbl = (lbl or "").strip()
            if lbl and lbl.lower() not in ("null", "none"):
                widget_labels[str(row["node_id"])] = lbl

        def node_label(n):
            return widget_labels.get(str(n.nodeid)) or str(n.name)

        # The single new query: cardinality + nesting for every nodegroup in play.
        # `nodegroups[]` already ships a flat list of groups; what it cannot say is
        # that Person's 23 groups are really 10 roots in a depth-4 forest.
        ng_meta = {}
        ng_ids = {n.nodegroup_id for n in all_nodes if n.nodegroup_id}
        if ng_ids:
            for ng in NodeGroup.objects.filter(nodegroupid__in=ng_ids).values(
                "nodegroupid", "cardinality", "parentnodegroup_id"
            ):
                ng_meta[str(ng["nodegroupid"])] = {
                    "cardinality": ng["cardinality"] or None,
                    "parent_nodegroup": (
                        str(ng["parentnodegroup_id"])
                        if ng["parentnodegroup_id"]
                        else None
                    ),
                }

        models, datatype_hist = [], {}
        cidoc_classes = set()
        thesaurus_nodes = 0
        relations_by_key = (
            {}
        )  # (gid, tgt, prop) -> relation dict, preserves first-seen order

        for g in graphs:
            gid = str(g.graphid)
            g_nodes = [n for n in all_nodes if str(n.graph_id) == gid]
            g_node_ids = {str(n.nodeid) for n in g_nodes}
            ng_map = {}  # nodegroupid -> {id,name,cidoc,nodes[]}
            data_nodes = 0
            struct_nodes, parent_of = [], {}

            for n in g_nodes:
                nid = str(n.nodeid)
                dt = n.datatype
                cfg = n.config if isinstance(n.config, dict) else dict(n.config or {})
                node_cfg = trim_node_config(dt, cfg)
                if n.ontologyclass:
                    cidoc_classes.add(prettify_cidoc(n.ontologyclass))

                # --- structure tree: EVERY node, top node included -------------
                # An edge whose domain sits in another graph cannot be a parent
                # here; treat it as a root so the tree stays well-formed.
                parent = edge_parent.get(nid)
                parent_of[nid] = parent if parent in g_node_ids else None
                prop_uri = edge_prop.get(nid)
                prop = prettify_cidoc(prop_uri)
                struct_nodes.append(
                    {
                        "id": nid,
                        "name": node_label(n),
                        "datatype": dt,
                        "cidoc": prettify_cidoc(n.ontologyclass),
                        "cidoc_uri": str(n.ontologyclass or ""),
                        "required": bool(n.isrequired),
                        "property": prop,
                        "property_code": property_code(prop),
                        "property_uri": str(prop_uri or ""),
                        "nodegroup": str(n.nodegroup_id) if n.nodegroup_id else None,
                        "is_collector": bool(n.nodegroup_id)
                        and nid == str(n.nodegroup_id),
                        "config": node_cfg,
                    }
                )

                # --- published counts: top node deliberately excluded ----------
                if skip_from_counts(dt, n.istopnode):
                    continue
                datatype_hist[dt] = datatype_hist.get(dt, 0) + 1
                if dt != "semantic":
                    data_nodes += 1
                if dt in ("concept", "concept-list"):
                    thesaurus_nodes += 1
                ngid = str(n.nodegroup_id) if n.nodegroup_id else "ungrouped"
                bucket = ng_map.setdefault(ngid, {"id": ngid, "name": "", "nodes": []})
                bucket["nodes"].append(
                    {
                        "name": node_label(n),
                        "datatype": dt,
                        "cidoc": prettify_cidoc(n.ontologyclass),
                        "required": bool(n.isrequired),
                        "is_collector": bool(n.nodegroup_id)
                        and nid == str(n.nodegroup_id),
                        "config": node_cfg,
                    }
                )
                # Relations from resource-instance nodes.
                if dt in ("resource-instance", "resource-instance-list"):
                    for tgt in node_cfg.get("target_graphs", []):
                        if tgt in id_str and tgt != gid:
                            prop = prettify_cidoc(edge_prop.get(str(n.nodeid)))
                            name = str(n.name)
                            key = (gid, tgt, prop)
                            existing = relations_by_key.get(key)
                            if existing is None:
                                relations_by_key[key] = {
                                    "source": gid,
                                    "target": tgt,
                                    "property": prop or name,
                                    "label": name,
                                    "count": 1,
                                    "fields": [name],
                                }
                            else:
                                existing["count"] += 1
                                if name not in existing["fields"]:
                                    existing["fields"].append(name)

            # Name nodegroups by their collector node's name where possible.
            for n in g_nodes:
                if (
                    n.nodegroup_id
                    and str(n.nodeid) == str(n.nodegroup_id)
                    and str(n.nodegroup_id) in ng_map
                ):
                    ng_map[str(n.nodegroup_id)]["name"] = str(n.name)

            models.append(
                {
                    "id": gid,
                    "name": str(g.name),
                    "slug": (g.slug or "").strip().lower(),
                    "description": str(g.description or ""),
                    "group": group_for_slug(g.slug),
                    "cidoc": prettify_cidoc(_top_ontologyclass(g_nodes)),
                    "instances": counts.get(gid, 0),
                    "counts": {"nodegroups": len(ng_map), "nodes": data_nodes},
                    "nodegroups": list(ng_map.values()),
                    "structure": finalize_structure(struct_nodes, parent_of, ng_meta),
                }
            )

        # dict preserves insertion order, so this keeps first-appearance ordering.
        relations = list(relations_by_key.values())

        datatypes = [
            {
                "id": dt,
                # str() forces the lazy proxy to resolve NOW, in the active
                # language, into a plain string safe to JSON-encode and cache.
                "label": str(DATATYPE_LABELS.get(dt) or dt.replace("-", " ").title()),
                "color": datatype_color(dt),
                "count": c,
            }
            for dt, c in sorted(datatype_hist.items(), key=lambda kv: -kv[1])
            if dt != "semantic"
        ]

        # Two cheap COUNTs. The pages quote "12 thesauri · ~20,000 concepts";
        # both drift as the RDM grows, so neither may live in a template.
        try:
            concepts = Concept.objects.filter(nodetype_id="Concept").count()
            thesauri = Concept.objects.filter(nodetype_id="ConceptScheme").count()
        except Exception:  # noqa: BLE001 — a missing RDM must not 500 the explorer
            concepts, thesauri = 0, 0

        data_nodes_total = sum(m["counts"]["nodes"] for m in models)
        stats = {
            # --- PINNED. The matrix/table/datatypes views and the published
            # figures on /about/model both read these; `nodes` is 452 and must
            # stay 452 unless the graphs themselves change. See skip_from_counts.
            "models": len(models),
            "nodegroups": sum(m["counts"]["nodegroups"] for m in models),
            "nodes": data_nodes_total,
            "relations": len(relations),
            "datatypes": len(datatypes),
            # --- derived figures, added so the About pages stop hardcoding them.
            "total_nodes": sum(len(m["structure"]["nodes"]) for m in models),
            "records": sum(int(m["instances"] or 0) for m in models),
            # Resources still behind the draft gate — kept out of "records" so
            # the public figures only claim published data.
            "records_draft": sum(draft_counts.values()),
            "empty_models": sum(1 for m in models if not m["instances"]),
            "thesaurus_nodes": thesaurus_nodes,
            "thesaurus_pct": (
                round(thesaurus_nodes * 100 / data_nodes_total)
                if data_nodes_total
                else 0
            ),
            "cidoc_classes": len(cidoc_classes),
            "properties": len(
                {p for p in edge_prop.values() if p}
            ),  # distinct CIDOC properties in use
            "concepts": concepts,
            "thesauri": thesauri,
        }

        # RDM collection labels + sizes: concept fields expose
        # "collection_label"/"collection_size" ("Pigments", 312) instead of a
        # bare UUID — the FAIR argument, readable. Two cheap queries; any RDM
        # quirk degrades to the UUID, never to a 500.
        coll_ids = set()
        for m in models:
            for nd in m["structure"]["nodes"]:
                c = (nd.get("config") or {}).get("collection")
                if c:
                    coll_ids.add(c)
        if coll_ids:
            try:
                from arches.app.models.models import Relation, Value

                labels = {}
                for v in Value.objects.filter(
                    concept_id__in=coll_ids, valuetype_id="prefLabel"
                ).values("concept_id", "value", "language_id"):
                    lang2 = (v["language_id"] or "").lower()[:2]
                    labels.setdefault(str(v["concept_id"]), {})[lang2] = v["value"]
                sizes = {
                    str(r["conceptfrom_id"]): r["n"]
                    for r in Relation.objects.filter(
                        conceptfrom_id__in=coll_ids, relationtype_id="member"
                    )
                    .values("conceptfrom_id")
                    .order_by()
                    .annotate(n=Count("relationid"))
                }
                page_lang = language.split("-")[0]
                for m in models:
                    for nd in m["structure"]["nodes"]:
                        cfg = nd.get("config") or {}
                        c = cfg.get("collection")
                        if not c:
                            continue
                        lbls = labels.get(c) or {}
                        lbl = (
                            lbls.get(page_lang)
                            or lbls.get("en")
                            or next(iter(lbls.values()), None)
                        )
                        if lbl:
                            cfg["collection_label"] = str(lbl)
                        if c in sizes:
                            cfg["collection_size"] = sizes[c]
            except Exception:  # noqa: BLE001
                pass

        return {
            "language": language,
            "generated_at": timezone.now().isoformat(),
            "stats": stats,
            "groups": GROUPS,
            "datatypes": datatypes,
            "models": models,
            "relations": relations,
        }


def _top_ontologyclass(nodes):
    for n in nodes:
        if n.istopnode:
            return n.ontologyclass
    return None
