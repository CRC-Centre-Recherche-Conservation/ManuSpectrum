"""Relatable nodes of a resource model, for the summary configuration form.

The form in the designer needs, for one model: the aliases it can show as
fields, the relations it can follow in one hop, and the aliases it can
aggregate on the models those hops reach. Four queries answer all of it,
none of them per node.

Relations are read from the node configuration: a resource-instance(-list)
node carries ``config["graphs"] = [{"graphid", "name"}, …]``, the models its
values may point at. A hop is outgoing when the node belongs to this model,
incoming when it belongs to another model that names this one.

Labels are the widget label of the active language, so the form shows the
same words as the data-entry form; a node with no card falls back to its
name. Draft models are out of scope — the function manager runs on published
models — and so is the system-settings model.
"""

import uuid

from django.db.models import Q
from django.http import Http404, JsonResponse
from django.utils import translation
from django.utils.decorators import method_decorator
from django.views import View

from arches.app.models import models
from arches.app.models.system_settings import settings as system_settings
from arches.app.utils.decorators import group_required

# Who may read a model's structure here: the group that edits graphs, and the
# two administrator groups. Never "Guest" or "Resource Exporter" — Arches'
# SetAnonymousUser maps every unauthenticated visitor to the `anonymous` user,
# which belongs to both (see views/permissions.py). Django superusers pass the
# check in Arches itself.
CONFIG_GROUPS = ("Graph Editor", "Application Administrator", "System Administrator")

RELATION_DATATYPES = ("resource-instance", "resource-instance-list")
AGGREGATABLE_DATATYPES = ("reference",)


def localized(value, language):
    """First non-empty of the active language, English, any other language.

    Accepts the ``I18n_String`` the ORM returns, a plain dict, or a bare
    string from a value written before the field was localized.
    """
    raw = getattr(value, "raw_value", value)
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return ""
    for key in (language, "en"):
        if raw.get(key):
            return raw[key]
    for text in raw.values():
        if text:
            return text
    return ""


def target_graphids(node):
    """Canonical graph ids a resource-instance(-list) node may point at.

    Deduplicated, in configuration order; an id the configuration carries in
    another casing is the same model.
    """
    seen = []
    for target in (node.config or {}).get("graphs") or []:
        raw = target.get("graphid") if isinstance(target, dict) else None
        try:
            graphid = str(uuid.UUID(str(raw)))
        except (AttributeError, TypeError, ValueError):
            continue
        if graphid not in seen:
            seen.append(graphid)
    return seen


@method_decorator(group_required(*CONFIG_GROUPS, raise_exception=True), name="dispatch")
class RelatableNodesView(View):
    """``GET /<lang>/function-config/relatable-nodes/<graphid>``.

    Answers 404 for anything that is not a published resource model: an
    unknown id, a branch, a draft, or the system settings model.
    """

    def get(self, request, graphid):
        language = translation.get_language() or "en"
        graphid = str(uuid.UUID(str(graphid)))

        graphs = {
            str(graph.graphid): graph
            for graph in models.GraphModel.objects.filter(
                isresource=True, source_identifier__isnull=True
            ).exclude(graphid=system_settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID)
        }
        graph = graphs.get(graphid)
        if graph is None:
            raise Http404("Unknown resource model")

        outgoing = []
        incoming = []
        involved = {graphid}
        for node in models.Node.objects.filter(
            datatype__in=RELATION_DATATYPES, graph_id__in=list(graphs)
        ).order_by("sortorder", "name"):
            if not node.alias:
                continue
            targets = target_graphids(node)
            if str(node.graph_id) == graphid:
                known = [graphs[target] for target in targets if target in graphs]
                outgoing.append((node, known))
                involved.update(str(target.graphid) for target in known)
            elif graphid in targets:
                incoming.append((node, graphs[str(node.graph_id)]))
                involved.add(str(node.graph_id))

        own_nodes = []
        reference_nodes = []
        for node in models.Node.objects.filter(
            Q(graph_id=graphid)
            | Q(
                graph_id__in=sorted(involved - {graphid}),
                datatype__in=AGGREGATABLE_DATATYPES,
            )
        ).order_by("sortorder", "name"):
            if not node.alias:
                continue
            if str(node.graph_id) == graphid:
                if node.datatype != "semantic":
                    own_nodes.append(node)
            if node.datatype in AGGREGATABLE_DATATYPES:
                reference_nodes.append(node)

        labels = self.widget_labels(
            [node for node, _ in outgoing]
            + [node for node, _ in incoming]
            + own_nodes
            + reference_nodes,
            language,
        )

        def named(target):
            return {
                "graphid": str(target.graphid),
                "slug": target.slug,
                "name": localized(target.name, language) or target.slug,
            }

        aggregatable = {graphs[gid].slug: [] for gid in involved}
        for node in reference_nodes:
            aggregatable[graphs[str(node.graph_id)].slug].append(
                {"alias": node.alias, "label": labels[node.nodeid]}
            )

        return JsonResponse(
            {
                "graph": named(graph),
                "fields": [
                    {
                        "alias": node.alias,
                        "datatype": node.datatype,
                        "label": labels[node.nodeid],
                    }
                    for node in own_nodes
                ],
                "outgoing": [
                    {
                        "alias": node.alias,
                        "label": labels[node.nodeid],
                        "targets": [named(target) for target in targets],
                    }
                    for node, targets in outgoing
                ],
                "incoming": [
                    {
                        "graph_slug": source.slug,
                        "graph_name": localized(source.name, language) or source.slug,
                        "alias": node.alias,
                        "label": labels[node.nodeid],
                    }
                    for node, source in incoming
                ],
                "aggregatable": aggregatable,
            }
        )

    def widget_labels(self, nodes, language):
        """Label per node id, from its widget label, falling back to the node name."""
        localized_labels = {
            nodeid: localized(label, language)
            for nodeid, label in models.CardXNodeXWidget.objects.filter(
                node_id__in={node.nodeid for node in nodes}
            ).values_list("node_id", "label")
        }
        return {
            node.nodeid: localized_labels.get(node.nodeid) or node.name
            for node in nodes
        }
