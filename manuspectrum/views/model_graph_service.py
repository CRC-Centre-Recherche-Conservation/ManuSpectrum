"""Introspection of Arches resource graphs into a graph-explorer JSON payload.

Pure helpers (DB-free) are unit-tested; build_model_graph() reads the ORM and is
verified against the dev database. Keep it lean — this feeds a cached endpoint.
"""

from django.conf import settings
from django.db.models import Count
from django.utils import translation

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
    "intrument": "context",
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

# Human labels where `.title()` of the id is wrong (custom datatypes, acronyms).
DATATYPE_LABELS = {
    "manifest": "IIIF Manifest",
    "edtf": "EDTF",
    "non-localized-string": "Non-localized String",
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
        GraphModel,
        Node,
        Edge,
        ResourceInstance,
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

        # Live instance counts per graph (cheap COUNT … GROUP BY).
        counts = {}
        for row in (
            ResourceInstance.objects.filter(graph_id__in=graph_ids)
            .values("graph_id")
            .order_by()
            .annotate(n=Count("resourceinstanceid"))
        ):
            counts[str(row["graph_id"])] = row["n"]

        # Edge property lookup: rangenode_id -> ontologyproperty (for relation labels).
        edge_prop = {}
        for e in Edge.objects.filter(graph_id__in=graph_ids).values(
            "rangenode_id", "ontologyproperty"
        ):
            edge_prop[str(e["rangenode_id"])] = e["ontologyproperty"]

        all_nodes = list(Node.objects.filter(graph_id__in=graph_ids))

        models, datatype_hist = [], {}
        relations_by_key = (
            {}
        )  # (gid, tgt, prop) -> relation dict, preserves first-seen order

        for g in graphs:
            gid = str(g.graphid)
            g_nodes = [n for n in all_nodes if str(n.graph_id) == gid]
            ng_map = {}  # nodegroupid -> {id,name,cidoc,nodes[]}
            data_nodes = 0

            for n in g_nodes:
                if n.datatype == "semantic" and n.istopnode:
                    continue
                dt = n.datatype
                datatype_hist[dt] = datatype_hist.get(dt, 0) + 1
                if dt != "semantic":
                    data_nodes += 1
                ngid = str(n.nodegroup_id) if n.nodegroup_id else "ungrouped"
                bucket = ng_map.setdefault(ngid, {"id": ngid, "name": "", "nodes": []})
                node_cfg = trim_node_config(
                    dt, n.config if isinstance(n.config, dict) else dict(n.config or {})
                )
                bucket["nodes"].append(
                    {
                        "name": str(n.name),
                        "datatype": dt,
                        "cidoc": prettify_cidoc(n.ontologyclass),
                        "required": bool(n.isrequired),
                        "is_collector": bool(n.nodegroup_id)
                        and str(n.nodeid) == str(n.nodegroup_id),
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
                    "description": str(g.description or ""),
                    "group": group_for_slug(g.slug),
                    "cidoc": prettify_cidoc(_top_ontologyclass(g_nodes)),
                    "instances": counts.get(gid, 0),
                    "counts": {"nodegroups": len(ng_map), "nodes": data_nodes},
                    "nodegroups": list(ng_map.values()),
                }
            )

        # dict preserves insertion order, so this keeps first-appearance ordering.
        relations = list(relations_by_key.values())

        datatypes = [
            {
                "id": dt,
                "label": DATATYPE_LABELS.get(dt) or dt.replace("-", " ").title(),
                "color": datatype_color(dt),
                "count": c,
            }
            for dt, c in sorted(datatype_hist.items(), key=lambda kv: -kv[1])
            if dt != "semantic"
        ]

        stats = {
            "models": len(models),
            "nodegroups": sum(m["counts"]["nodegroups"] for m in models),
            "nodes": sum(m["counts"]["nodes"] for m in models),
            "relations": len(relations),
            "datatypes": len(datatypes),
        }

        return {
            "language": language,
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
