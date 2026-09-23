"""Unit coverage for the ORM-driven half of `model_graph_service`.

The pure helpers are already pinned by `tests/test_model_graph.py`; this module
covers what that file cannot reach — `build_model_graph()`'s assembly loop, the
`stats` block, the RDM enrichment and its two degradation paths, plus
`_excluded_graph_ids()` and `_top_ontologyclass()`.

`build_model_graph` imports its Arches managers inside the function body, so
there is nothing to patch on `manuspectrum.views.model_graph_service`: the
stand-ins are installed on `arches.app.models.models`, the import site.
"""

import contextlib
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from manuspectrum.views.model_graph_service import (
    GROUPS,
    _excluded_graph_ids,
    _top_ontologyclass,
    build_model_graph,
)

CIDOC = "http://www.cidoc-crm.org/cidoc-crm/"


class _Rows:
    """Chainable queryset stand-in: filter/values/order_by/annotate all return self."""

    def __init__(self, rows=(), count=0):
        self._rows = list(rows)
        self._count = count

    def filter(self, *args, **kwargs):
        return self

    def values(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def annotate(self, *args, **kwargs):
        return self

    def count(self):
        return self._count

    def __iter__(self):
        return iter(self._rows)


class _ConceptManager:
    """Concept.objects, whose two COUNTs differ only by `nodetype_id`."""

    def __init__(self, concepts, schemes):
        self._by_type = {"Concept": concepts, "ConceptScheme": schemes}

    def filter(self, nodetype_id=None, **kwargs):
        return _Rows(count=self._by_type.get(nodetype_id, 0))


def _manager(rows=(), count=0):
    return SimpleNamespace(objects=_Rows(rows, count))


def _raising_manager(exc):
    objects = mock.Mock()
    objects.filter.side_effect = exc
    return SimpleNamespace(objects=objects)


def _graph(gid, slug, name, description=""):
    return SimpleNamespace(graphid=gid, slug=slug, name=name, description=description)


def _node(
    nid,
    graph,
    datatype="string",
    name=None,
    ontologyclass=None,
    nodegroup=None,
    istopnode=False,
    isrequired=False,
    config=None,
):
    return SimpleNamespace(
        nodeid=nid,
        graph_id=graph,
        datatype=datatype,
        name=name if name is not None else nid,
        ontologyclass=ontologyclass,
        nodegroup_id=nodegroup,
        istopnode=istopnode,
        isrequired=isrequired,
        config=config,
    )


def _edge(rangenode, domainnode, prop):
    return {
        "rangenode_id": rangenode,
        "domainnode_id": domainnode,
        "ontologyproperty": prop,
    }


@contextlib.contextmanager
def patched_orm(
    graphs=(),
    nodes=(),
    edges=(),
    instances=(),
    lifecycle_states=(),
    nodegroups=(),
    labels=(),
    concepts=0,
    thesauri=0,
    values=(),
    relations=(),
    **overrides,
):
    targets = {
        "GraphModel": _manager(graphs),
        "Node": _manager(nodes),
        "Edge": _manager(edges),
        "NodeGroup": _manager(nodegroups),
        "CardXNodeXWidget": _manager(labels),
        "ResourceInstance": _manager(instances),
        "ResourceInstanceLifecycleState": _manager(lifecycle_states),
        "Concept": SimpleNamespace(objects=_ConceptManager(concepts, thesauri)),
        "Value": _manager(values),
        "Relation": _manager(relations),
    }
    targets.update(overrides)
    with mock.patch.multiple("arches.app.models.models", **targets):
        yield


# --- a two-graph fixture exercising the whole assembly loop -------------------

GRAPHS = [
    _graph("g1", "document", "Document", "Un manuscrit"),
    _graph("g2", "person", "Person"),
]

NODES = [
    _node(
        "n1",
        "g1",
        "semantic",
        name="Document",
        istopnode=True,
        ontologyclass=CIDOC + "E22_Human-Made_Object",
    ),
    _node(
        "ng1",
        "g1",
        "string",
        name="Identifier",
        nodegroup="ng1",
        isrequired=True,
        ontologyclass=CIDOC + "E41_Appellation",
    ),
    _node(
        "n3",
        "g1",
        "concept",
        name="Type",
        nodegroup="ng1",
        ontologyclass=CIDOC + "E55_Type",
        config={"rdmCollection": "coll-1", "junk": 1},
    ),
    _node(
        "n4",
        "g1",
        "resource-instance",
        name="Related person",
        nodegroup="ng1",
        ontologyclass=CIDOC + "E22_Human-Made_Object",
        config={"graphs": [{"graphid": "g2"}]},
    ),
    _node(
        "m1",
        "g2",
        "semantic",
        name="Person",
        istopnode=True,
        ontologyclass=CIDOC + "E21_Person",
    ),
    _node(
        "ng2",
        "g2",
        "string",
        name="Name",
        nodegroup="ng2",
        ontologyclass=CIDOC + "E41_Appellation",
    ),
]

EDGES = [
    _edge("ng1", "n1", CIDOC + "P1_is_identified_by"),
    _edge("n3", "ng1", CIDOC + "P2_has_type"),
    _edge("n4", "ng1", CIDOC + "P128_carries"),
    _edge("ng2", "m1", CIDOC + "P1_is_identified_by"),
]

LABELS = [
    {"node_id": "n3", "label": {"fr": "Type FR", "en": "Type EN"}},
    {"node_id": "n4", "label": None},
    {"node_id": "ng2", "label": "Full name"},
    {"node_id": "ng1", "label": "  none  "},
]

NODEGROUPS = [
    {"nodegroupid": "ng1", "cardinality": "n", "parentnodegroup_id": "ng0"},
    {"nodegroupid": "ng2", "cardinality": "", "parentnodegroup_id": None},
]

LIFECYCLE_STATES = [
    {"id": "draft", "is_initial_state": True, "resource_instance_lifecycle_id": "L1"},
    {"id": "active", "is_initial_state": False, "resource_instance_lifecycle_id": "L1"},
]

INSTANCES = [
    {"graph_id": "g1", "resource_instance_lifecycle_state_id": "draft", "n": 3},
    {"graph_id": "g1", "resource_instance_lifecycle_state_id": "active", "n": 7},
]

VALUES = [
    {"concept_id": "coll-1", "value": "Pigments", "language_id": "en-US"},
    {"concept_id": "coll-1", "value": "Pigments FR", "language_id": "fr"},
]

RELATIONS = [{"conceptfrom_id": "coll-1", "n": 312}]


def build_fixture(**overrides):
    kwargs = dict(
        graphs=GRAPHS,
        nodes=NODES,
        edges=EDGES,
        instances=INSTANCES,
        lifecycle_states=LIFECYCLE_STATES,
        nodegroups=NODEGROUPS,
        labels=LABELS,
        concepts=20000,
        thesauri=12,
        values=VALUES,
        relations=RELATIONS,
    )
    kwargs.update(overrides)
    language = kwargs.pop("language", "en")
    with patched_orm(**kwargs):
        return build_model_graph(language)


class BuildModelGraphEnvelopeTests(SimpleTestCase):
    def test_envelope_keys_and_groups(self):
        payload = build_fixture()
        self.assertEqual(
            set(payload),
            {
                "language",
                "generated_at",
                "stats",
                "groups",
                "datatypes",
                "models",
                "relations",
            },
        )
        self.assertEqual(payload["language"], "en")
        self.assertIs(payload["groups"], GROUPS)

    def test_generated_at_is_an_iso_timestamp(self):
        from datetime import datetime

        stamp = build_fixture()["generated_at"]
        self.assertIsInstance(datetime.fromisoformat(stamp), datetime)


class BuildModelGraphStatsTests(SimpleTestCase):
    """`stats` is derived from the graphs, never hardcoded — the pinned figures.

    Every number below is computable by hand from the fixture above, so a change
    to the assembly rules (what counts as a field, what a nodegroup is, which
    resources are public) moves exactly one of them and fails here.
    """

    def setUp(self):
        self.stats = build_fixture()["stats"]

    def test_model_nodegroup_and_field_counts(self):
        self.assertEqual(self.stats["models"], 2)
        self.assertEqual(self.stats["nodegroups"], 2)
        self.assertEqual(self.stats["nodes"], 4)

    def test_total_nodes_counts_the_top_nodes_that_nodes_excludes(self):
        self.assertEqual(self.stats["total_nodes"], 6)

    def test_relations_and_datatype_counts(self):
        self.assertEqual(self.stats["relations"], 1)
        self.assertEqual(self.stats["datatypes"], 3)

    def test_records_excludes_draft_gated_resources(self):
        self.assertEqual(self.stats["records"], 7)
        self.assertEqual(self.stats["records_draft"], 3)

    def test_empty_models_counts_graphs_with_no_published_instances(self):
        self.assertEqual(self.stats["empty_models"], 1)

    def test_thesaurus_share_is_a_percentage_of_data_nodes(self):
        self.assertEqual(self.stats["thesaurus_nodes"], 1)
        self.assertEqual(self.stats["thesaurus_pct"], 25)

    def test_distinct_cidoc_classes_and_properties(self):
        self.assertEqual(self.stats["cidoc_classes"], 4)
        self.assertEqual(self.stats["properties"], 3)

    def test_rdm_totals_come_from_the_concept_table(self):
        self.assertEqual(self.stats["concepts"], 20000)
        self.assertEqual(self.stats["thesauri"], 12)

    def test_draft_resources_are_absent_from_the_owning_model(self):
        models = build_fixture()["models"]
        self.assertEqual(models[0]["instances"], 7)
        self.assertEqual(models[1]["instances"], 0)


class BuildModelGraphModelTests(SimpleTestCase):
    def setUp(self):
        self.models = build_fixture()["models"]

    def test_model_header_fields(self):
        self.assertEqual(
            {
                k: v
                for k, v in self.models[0].items()
                if not isinstance(v, (dict, list))
            },
            {
                "id": "g1",
                "name": "Document",
                "slug": "document",
                "description": "Un manuscrit",
                "group": "studied-object",
                "cidoc": "E22 Human-Made Object",
                "instances": 7,
            },
        )

    def test_per_model_counts_exclude_the_top_node(self):
        self.assertEqual(self.models[0]["counts"], {"nodegroups": 1, "nodes": 3})
        self.assertEqual(self.models[1]["counts"], {"nodegroups": 1, "nodes": 1})

    def test_nodegroup_is_named_after_its_collector_node(self):
        ng = self.models[0]["nodegroups"]
        self.assertEqual([g["id"] for g in ng], ["ng1"])
        self.assertEqual(ng[0]["name"], "Identifier")

    def test_nodegroup_carries_every_field_but_the_top_node(self):
        nodes = self.models[0]["nodegroups"][0]["nodes"]
        self.assertEqual(
            [n["name"] for n in nodes], ["Identifier", "Type EN", "Related person"]
        )
        self.assertEqual(
            nodes[0],
            {
                "name": "Identifier",
                "datatype": "string",
                "cidoc": "E41 Appellation",
                "required": True,
                "is_collector": True,
                "config": {},
            },
        )

    def test_structure_holds_the_top_node_the_counts_dropped(self):
        structure = self.models[0]["structure"]
        self.assertEqual(structure["root"], "n1")
        self.assertEqual(
            [n["id"] for n in structure["nodes"]], ["n1", "ng1", "n4", "n3"]
        )

    def test_structure_node_carries_its_edge_property_and_nodegroup_metadata(self):
        by_id = {n["id"]: n for n in self.models[0]["structure"]["nodes"]}
        self.assertEqual(
            by_id["n3"],
            {
                "id": "n3",
                "name": "Type EN",
                "datatype": "concept",
                "cidoc": "E55 Type",
                "cidoc_uri": CIDOC + "E55_Type",
                "required": False,
                "property": "P2 has type",
                "property_code": "P2",
                "property_uri": CIDOC + "P2_has_type",
                "nodegroup": "ng1",
                "is_collector": False,
                "config": {
                    "collection": "coll-1",
                    "collection_label": "Pigments",
                    "collection_size": 312,
                },
                "parent": "ng1",
                "depth": 2,
                "cardinality": "n",
                "parent_nodegroup": "ng0",
            },
        )

    def test_root_has_no_property_and_no_nodegroup_metadata(self):
        root = self.models[0]["structure"]["nodes"][0]
        self.assertEqual(root["parent"], None)
        self.assertEqual(root["depth"], 0)
        self.assertEqual(root["property"], "")
        self.assertEqual(root["property_code"], "")
        self.assertEqual(root["property_uri"], "")
        self.assertEqual(root["nodegroup"], None)
        self.assertIs(root["is_collector"], False)
        self.assertIsNone(root["cardinality"])

    def test_blank_cardinality_becomes_null(self):
        by_id = {n["id"]: n for n in self.models[1]["structure"]["nodes"]}
        self.assertIsNone(by_id["ng2"]["cardinality"])
        self.assertIsNone(by_id["ng2"]["parent_nodegroup"])


class BuildModelGraphLabelTests(SimpleTestCase):
    def test_widget_label_overrides_the_node_name(self):
        models = build_fixture()["models"]
        by_id = {n["id"]: n for n in models[0]["structure"]["nodes"]}
        self.assertEqual(by_id["n3"]["name"], "Type EN")

    def test_plain_string_widget_label_is_used(self):
        models = build_fixture()["models"]
        by_id = {n["id"]: n for n in models[1]["structure"]["nodes"]}
        self.assertEqual(by_id["ng2"]["name"], "Full name")

    def test_null_and_none_sentinel_labels_fall_back_to_the_node_name(self):
        models = build_fixture()["models"]
        by_id = {n["id"]: n for n in models[0]["structure"]["nodes"]}
        self.assertEqual(by_id["ng1"]["name"], "Identifier")
        self.assertEqual(by_id["n4"]["name"], "Related person")

    def test_label_dict_is_read_in_the_requested_language(self):
        models = build_fixture(language="fr")["models"]
        by_id = {n["id"]: n for n in models[0]["structure"]["nodes"]}
        self.assertEqual(by_id["n3"]["name"], "Type FR")

    def test_label_dict_falls_back_to_english_when_the_language_is_missing(self):
        labels = [{"node_id": "n3", "label": {"en": "English only"}}]
        models = build_fixture(language="fr", labels=labels)["models"]
        by_id = {n["id"]: n for n in models[0]["structure"]["nodes"]}
        self.assertEqual(by_id["n3"]["name"], "English only")

    def test_regional_language_falls_back_to_its_base_language(self):
        labels = [{"node_id": "n3", "label": {"fr": "Type FR", "en": "Type EN"}}]
        models = build_fixture(language="fr-CA", labels=labels)["models"]
        by_id = {n["id"]: n for n in models[0]["structure"]["nodes"]}
        self.assertEqual(by_id["n3"]["name"], "Type FR")

    def test_nodegroup_name_ignores_the_widget_label_its_own_node_uses(self):
        models = build_fixture()["models"]
        by_id = {n["id"]: n for n in models[1]["structure"]["nodes"]}
        self.assertEqual(by_id["ng2"]["name"], "Full name")
        self.assertEqual(models[1]["nodegroups"][0]["name"], "Name")


class BuildModelGraphDatatypeTests(SimpleTestCase):
    def test_datatypes_are_ranked_by_use_and_exclude_semantic(self):
        self.assertEqual(
            build_fixture()["datatypes"],
            [
                {"id": "string", "label": "String", "color": "#3b82f6", "count": 2},
                {"id": "concept", "label": "Concept", "color": "#8b5cf6", "count": 1},
                {
                    "id": "resource-instance",
                    "label": "Resource Instance",
                    "color": "#e67e22",
                    "count": 1,
                },
            ],
        )

    def test_unregistered_datatype_gets_a_titled_label_and_the_fallback_color(self):
        nodes = [
            _node("t1", "g1", "semantic", name="Doc", istopnode=True),
            _node("s1", "g1", "spectral-curve", name="Curve", nodegroup="s1"),
        ]
        payload = build_fixture(graphs=[GRAPHS[0]], nodes=nodes, edges=[], labels=[])
        self.assertEqual(
            payload["datatypes"],
            [
                {
                    "id": "spectral-curve",
                    "label": "Spectral Curve",
                    "color": "#94a3b8",
                    "count": 1,
                }
            ],
        )

    def test_cidoc_class_without_a_code_separator_is_passed_through(self):
        nodes = [
            _node(
                "t1",
                "g1",
                "semantic",
                name="Doc",
                istopnode=True,
                ontologyclass=CIDOC + "E22",
            )
        ]
        payload = build_fixture(graphs=[GRAPHS[0]], nodes=nodes, edges=[], labels=[])
        self.assertEqual(payload["models"][0]["cidoc"], "E22")


class BuildModelGraphRelationTests(SimpleTestCase):
    def test_relation_is_emitted_for_a_resource_instance_node(self):
        self.assertEqual(
            build_fixture()["relations"],
            [
                {
                    "source": "g1",
                    "target": "g2",
                    "property": "P128 carries",
                    "label": "Related person",
                    "count": 1,
                    "fields": ["Related person"],
                }
            ],
        )

    def test_self_reference_and_unknown_target_produce_no_relation(self):
        nodes = list(NODES) + [
            _node(
                "n5",
                "g1",
                "resource-instance-list",
                name="Parent doc",
                nodegroup="ng1",
                config={"graphs": [{"graphid": "g1"}, {"graphid": "g99"}]},
            )
        ]
        self.assertEqual(len(build_fixture(nodes=nodes)["relations"]), 1)

    def test_two_fields_sharing_a_property_collapse_into_one_counted_relation(self):
        nodes = list(NODES) + [
            _node(
                "n5",
                "g1",
                "resource-instance",
                name="Scribe",
                nodegroup="ng1",
                config={"graphs": [{"graphid": "g2"}]},
            )
        ]
        edges = list(EDGES) + [_edge("n5", "ng1", CIDOC + "P128_carries")]
        relations = build_fixture(nodes=nodes, edges=edges)["relations"]
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["count"], 2)
        self.assertEqual(relations[0]["fields"], ["Related person", "Scribe"])

    def test_a_different_property_to_the_same_target_is_its_own_relation(self):
        nodes = list(NODES) + [
            _node(
                "n5",
                "g1",
                "resource-instance",
                name="Scribe",
                nodegroup="ng1",
                config={"graphs": [{"graphid": "g2"}]},
            )
        ]
        edges = list(EDGES) + [_edge("n5", "ng1", CIDOC + "P94_has_created")]
        relations = build_fixture(nodes=nodes, edges=edges)["relations"]
        self.assertEqual(
            [(r["property"], r["count"]) for r in relations],
            [("P128 carries", 1), ("P94 has created", 1)],
        )

    def test_relation_with_no_edge_property_falls_back_to_the_field_name(self):
        nodes = [
            _node("t1", "g1", "semantic", name="Doc", istopnode=True),
            _node(
                "r1",
                "g1",
                "resource-instance",
                name="Owner",
                nodegroup="r1",
                config={"graphs": [{"graphid": "g2"}]},
            ),
            _node("t2", "g2", "semantic", name="Person", istopnode=True),
        ]
        relations = build_fixture(nodes=nodes, edges=[], labels=[])["relations"]
        self.assertEqual(relations[0]["property"], "Owner")
        self.assertEqual(relations[0]["label"], "Owner")


class BuildModelGraphExclusionTests(SimpleTestCase):
    def test_system_settings_graph_and_scratch_graphs_are_dropped(self):
        from arches.app.models.system_settings import SystemSettings

        graphs = [
            GRAPHS[0],
            _graph(
                str(SystemSettings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID),
                "system-settings",
                "System Settings",
            ),
            _graph("g3", "test_ressource", "Scratch"),
            _graph("g4", "keep-me", "  Test Resource  "),
        ]
        payload = build_fixture(graphs=graphs)
        self.assertEqual([m["id"] for m in payload["models"]], ["g1"])

    def test_a_real_model_whose_name_merely_contains_test_is_kept(self):
        graphs = [_graph("g9", "contest-entry", "Contest Entry")]
        nodes = [_node("t9", "g9", "semantic", name="Contest", istopnode=True)]
        payload = build_fixture(graphs=graphs, nodes=nodes, edges=[], labels=[])
        self.assertEqual([m["id"] for m in payload["models"]], ["g9"])

    def test_a_node_whose_parent_lives_in_another_graph_becomes_a_root(self):
        edges = [_edge("ng2", "ng1", CIDOC + "P1_is_identified_by")]
        models = build_fixture(edges=edges)["models"]
        by_id = {n["id"]: n for n in models[1]["structure"]["nodes"]}
        self.assertIsNone(by_id["ng2"]["parent"])
        self.assertEqual(by_id["ng2"]["depth"], 0)
        self.assertEqual(by_id["ng2"]["property"], "P1 is identified by")

    def test_no_graphs_yields_a_zeroed_payload(self):
        payload = build_fixture(graphs=[], nodes=[], edges=[])
        self.assertEqual(payload["models"], [])
        self.assertEqual(payload["relations"], [])
        self.assertEqual(payload["datatypes"], [])
        self.assertEqual(payload["stats"]["nodes"], 0)
        self.assertEqual(payload["stats"]["thesaurus_pct"], 0)
        self.assertEqual(payload["stats"]["records"], 0)


class BuildModelGraphRdmEnrichmentTests(SimpleTestCase):
    def _concept_config(self, payload, model=0, node_id="n3"):
        by_id = {n["id"]: n for n in payload["models"][model]["structure"]["nodes"]}
        return by_id[node_id]["config"]

    def test_collection_gains_a_label_and_a_size(self):
        cfg = self._concept_config(build_fixture())
        self.assertEqual(cfg["collection_label"], "Pigments")
        self.assertEqual(cfg["collection_size"], 312)

    def test_collection_label_follows_the_requested_language(self):
        cfg = self._concept_config(build_fixture(language="fr"))
        self.assertEqual(cfg["collection_label"], "Pigments FR")

    def test_collection_label_falls_back_to_english(self):
        values = [{"concept_id": "coll-1", "value": "Pigments", "language_id": "en"}]
        cfg = self._concept_config(build_fixture(language="fr", values=values))
        self.assertEqual(cfg["collection_label"], "Pigments")

    def test_collection_label_falls_back_to_any_available_language(self):
        values = [{"concept_id": "coll-1", "value": "Pigmente", "language_id": "de"}]
        cfg = self._concept_config(build_fixture(language="fr", values=values))
        self.assertEqual(cfg["collection_label"], "Pigmente")

    def test_unlabelled_collection_keeps_only_its_uuid(self):
        cfg = self._concept_config(build_fixture(values=[], relations=[]))
        self.assertEqual(cfg, {"collection": "coll-1"})

    def test_enrichment_reaches_the_nodegroup_view_as_well(self):
        payload = build_fixture()
        concept_field = payload["models"][0]["nodegroups"][0]["nodes"][1]
        self.assertEqual(concept_field["config"]["collection_label"], "Pigments")

    def test_an_rdm_failure_degrades_to_the_bare_uuid_instead_of_raising(self):
        payload = build_fixture(Value=_raising_manager(RuntimeError("no rdm")))
        self.assertEqual(self._concept_config(payload), {"collection": "coll-1"})

    def test_a_missing_concept_table_degrades_the_totals_to_zero(self):
        payload = build_fixture(
            Concept=_raising_manager(RuntimeError("relation does not exist"))
        )
        self.assertEqual(payload["stats"]["concepts"], 0)
        self.assertEqual(payload["stats"]["thesauri"], 0)


class ExcludedGraphIdsTests(SimpleTestCase):
    def test_defaults_to_the_arches_system_settings_model_id(self):
        from arches.app.models.system_settings import SystemSettings

        self.assertEqual(
            _excluded_graph_ids(),
            {str(SystemSettings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID)},
        )

    @override_settings(
        SYSTEM_SETTINGS_RESOURCE_MODEL_ID="11111111-2222-3333-4444-555555555555"
    )
    def test_a_django_setting_wins_over_the_class_attribute(self):
        self.assertEqual(
            _excluded_graph_ids(), {"11111111-2222-3333-4444-555555555555"}
        )

    def test_no_id_anywhere_excludes_nothing(self):
        from arches.app.models.system_settings import SystemSettings

        with mock.patch.object(
            SystemSettings, "SYSTEM_SETTINGS_RESOURCE_MODEL_ID", None
        ):
            self.assertEqual(_excluded_graph_ids(), set())


class TopOntologyClassTests(SimpleTestCase):
    def test_returns_the_class_of_the_top_node(self):
        nodes = [
            _node("a", "g", ontologyclass=CIDOC + "E41_Appellation"),
            _node(
                "b",
                "g",
                istopnode=True,
                ontologyclass=CIDOC + "E22_Human-Made_Object",
            ),
        ]
        self.assertEqual(_top_ontologyclass(nodes), CIDOC + "E22_Human-Made_Object")

    def test_returns_none_when_no_node_is_the_top_node(self):
        self.assertIsNone(_top_ontologyclass([_node("a", "g")]))

    def test_returns_none_for_an_empty_graph(self):
        self.assertIsNone(_top_ontologyclass([]))
