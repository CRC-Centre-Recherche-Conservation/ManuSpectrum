"""Field extraction of the summary popup, from a recorded Elasticsearch document.

Every function exercised here is pure: the graph index is built by hand, the
Elasticsearch client is a fake recording its kwargs, and no query is made, so
the module stays a ``SimpleTestCase`` and the suite creates no database.
``GraphIndex.for_graph`` and ``load_summary_config``, which read the ORM, are
covered by the endpoint tests of Task 7.
"""

from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from elasticsearch import ApiError, NotFoundError, TransportError

from manuspectrum.views.summary_service import (
    GraphIndex,
    NodeInfo,
    ResourceNotFound,
    build_summaries,
    build_summary,
    display_name,
    distinct_aggs,
    extract_fields,
    find_preview,
    hop_query,
    list_labels,
    outgoing_ids,
    parse_rollup_response,
    perm_scope,
    run_rollup,
)


class FakeUser:
    """Only the id a permission filter reads."""

    def __init__(self, user_id):
        self.id = user_id


def make_index(**nodes):
    """nodes: alias=(datatype,) ; deterministic ids."""
    infos = {
        alias: NodeInfo(
            nodeid=f"node-{alias}",
            nodegroup_id=f"ng-{alias}",
            datatype=dt,
            alias=alias,
        )
        for alias, (dt,) in nodes.items()
    }
    labels = {
        f"node-{alias}": {"en": alias.replace("_", " ").title(), "fr": f"{alias} (fr)"}
        for alias in nodes
    }
    return GraphIndex(
        graph_id="g",
        slug="document",
        name={"en": "Document", "fr": "Document"},
        nodes=infos,
        labels=labels,
    )


class ExtractFieldsTests(SimpleTestCase):
    def setUp(self):
        self.index = make_index(
            label_of_name=("string",),
            period_production=("reference",),
            date_start=("date",),
            current_location=("resource-instance",),
            measurement_point_data=("file-list",),
        )
        self.doc = {
            "tiles": [
                {
                    "nodegroup_id": "ng-label_of_name",
                    "sortorder": 0,
                    "data": {
                        "node-label_of_name": {
                            "en": {"value": "Ms. 12"},
                            "fr": {"value": "Ms 12 (fr)"},
                        }
                    },
                },
                {
                    "nodegroup_id": "ng-period_production",
                    "sortorder": 0,
                    "data": {
                        "node-period_production": [
                            {
                                "uri": "61216",
                                "list_id": "L",
                                "labels": [
                                    {
                                        "value": "XIIth c.",
                                        "language_id": "en",
                                        "valuetype_id": "prefLabel",
                                    },
                                    {
                                        "value": "XIIe s.",
                                        "language_id": "fr",
                                        "valuetype_id": "prefLabel",
                                    },
                                ],
                            },
                            {
                                "uri": "61217",
                                "list_id": "L",
                                "labels": [
                                    {
                                        "value": "XIIIth c.",
                                        "language_id": "en",
                                        "valuetype_id": "prefLabel",
                                    }
                                ],
                            },
                        ]
                    },
                },
                {
                    "nodegroup_id": "ng-date_start",
                    "sortorder": 0,
                    "data": {"node-date_start": "1150-01-01"},
                },
                {
                    "nodegroup_id": "ng-current_location",
                    "sortorder": 0,
                    "data": {"node-current_location": [{"resourceId": "place-1"}]},
                },
                {
                    "nodegroup_id": "ng-measurement_point_data",
                    "sortorder": 0,
                    "data": {
                        "node-measurement_point_data": [
                            {"file_id": "f-bin", "name": "a.asd"},
                            {"file_id": "f-csv", "name": "a.csv"},
                        ]
                    },
                },
            ]
        }

    def test_each_style_yields_localized_values(self):
        config = {
            "fields": [
                {"alias": "label_of_name", "style": "text"},
                {"alias": "period_production", "style": "chip", "max_values": 1},
                {"alias": "date_start", "style": "date"},
                {"alias": "current_location", "style": "link", "label": {"fr": "Lieu"}},
            ]
        }
        fields, link_ids, preview = extract_fields(self.doc, config, self.index, "fr")
        self.assertEqual(
            [f["values"] for f in fields],
            [["Ms 12 (fr)"], ["XIIe s."], ["1150-01-01"], [{"id": "place-1"}]],
        )
        self.assertEqual(fields[1]["more"], 1)
        self.assertEqual(fields[3]["label"], "Lieu")
        self.assertEqual(fields[0]["label"], "label_of_name (fr)")
        self.assertEqual(link_ids, ["place-1"])
        self.assertIsNone(preview)

    def test_missing_language_falls_back_to_english_then_uri(self):
        config = {"fields": [{"alias": "period_production", "style": "chip"}]}
        fields, _, _ = extract_fields(self.doc, config, self.index, "fr")
        self.assertEqual(fields[0]["values"], ["XIIe s.", "XIIIth c."])

    def test_unknown_alias_is_skipped(self):
        config = {"fields": [{"alias": "nope", "style": "text"}]}
        fields, _, _ = extract_fields(self.doc, config, self.index, "en")
        self.assertEqual(fields, [])

    def test_image_style_picks_the_first_supported_file(self):
        config = {"fields": [{"alias": "measurement_point_data", "style": "image"}]}
        fields, _, preview = extract_fields(self.doc, config, self.index, "en")
        self.assertEqual(preview, {"file_id": "f-csv", "name": "a.csv"})
        self.assertEqual(fields, [])

    def test_display_name_prefers_the_language(self):
        doc = {
            "displayname": [
                {"language": "en", "value": "A"},
                {"language": "fr", "value": "B"},
            ]
        }
        self.assertEqual(display_name(doc, "fr"), "B")
        self.assertEqual(
            display_name({"displayname": [{"language": "en", "value": "A"}]}, "fr"), "A"
        )

    def test_key_and_style_travel_with_the_field(self):
        config = {"fields": [{"alias": "date_start", "style": "date"}]}
        fields, _, _ = extract_fields(self.doc, config, self.index, "en")
        self.assertEqual(fields[0]["key"], "date_start")
        self.assertEqual(fields[0]["style"], "date")
        self.assertEqual(fields[0]["more"], 0)

    def test_label_falls_back_to_the_widget_label_then_the_alias(self):
        index = make_index(label_of_name=("string",))
        index.labels.pop("node-label_of_name")
        config = {"fields": [{"alias": "label_of_name", "style": "text"}]}
        fields, _, _ = extract_fields(self.doc, config, index, "fr")
        self.assertEqual(fields[0]["label"], "label_of_name")

    def test_a_label_override_in_another_language_is_still_used(self):
        config = {
            "fields": [
                {"alias": "date_start", "style": "date", "label": {"fr": "Début"}}
            ]
        }
        fields, _, _ = extract_fields(self.doc, config, self.index, "en")
        self.assertEqual(fields[0]["label"], "Début")


class TileReadingTests(SimpleTestCase):
    """Values gathered across tiles, and the shapes a datatype may take."""

    def setUp(self):
        self.index = make_index(
            note=("string",),
            technique=("reference",),
            partner=("resource-instance",),
            thickness=("number",),
        )

    def test_values_of_several_tiles_follow_sortorder(self):
        doc = {
            "tiles": [
                {
                    "nodegroup_id": "ng-note",
                    "sortorder": 2,
                    "data": {"node-note": {"fr": {"value": "deux"}}},
                },
                {
                    "nodegroup_id": "ng-note",
                    "sortorder": 1,
                    "data": {"node-note": {"fr": {"value": "un"}}},
                },
                {
                    "nodegroup_id": "ng-other",
                    "sortorder": 0,
                    "data": {"node-note": {"fr": {"value": "autre carte"}}},
                },
            ]
        }
        config = {"fields": [{"alias": "note", "style": "text"}]}
        fields, _, _ = extract_fields(doc, config, self.index, "fr")
        self.assertEqual(fields[0]["values"], ["un", "deux"])

    def test_a_single_resource_instance_may_be_a_bare_object(self):
        doc = {
            "tiles": [
                {
                    "nodegroup_id": "ng-partner",
                    "sortorder": 0,
                    "data": {"node-partner": {"resourceId": "r-1"}},
                }
            ]
        }
        config = {"fields": [{"alias": "partner", "style": "link"}]}
        fields, link_ids, _ = extract_fields(doc, config, self.index, "en")
        self.assertEqual(fields[0]["values"], [{"id": "r-1"}])
        self.assertEqual(link_ids, ["r-1"])

    def test_link_ids_are_collected_once_in_order(self):
        doc = {
            "tiles": [
                {
                    "nodegroup_id": "ng-partner",
                    "sortorder": 0,
                    "data": {
                        "node-partner": [{"resourceId": "r-1"}, {"resourceId": "r-2"}]
                    },
                },
                {
                    "nodegroup_id": "ng-partner",
                    "sortorder": 1,
                    "data": {"node-partner": [{"resourceId": "r-1"}]},
                },
            ]
        }
        config = {"fields": [{"alias": "partner", "style": "link"}]}
        fields, link_ids, _ = extract_fields(doc, config, self.index, "en")
        self.assertEqual(
            fields[0]["values"], [{"id": "r-1"}, {"id": "r-2"}, {"id": "r-1"}]
        )
        self.assertEqual(link_ids, ["r-1", "r-2"])

    def test_a_reference_without_a_usable_label_falls_back_to_its_uri(self):
        doc = {
            "tiles": [
                {
                    "nodegroup_id": "ng-technique",
                    "sortorder": 0,
                    "data": {
                        "node-technique": [
                            {"uri": "61292", "list_id": "L", "labels": []},
                            {
                                "uri": "61216",
                                "list_id": "L",
                                "labels": [
                                    {
                                        "value": "XRF",
                                        "language_id": "de",
                                        "valuetype_id": "altLabel",
                                    }
                                ],
                            },
                        ]
                    },
                }
            ]
        }
        config = {"fields": [{"alias": "technique", "style": "chip"}]}
        fields, _, _ = extract_fields(doc, config, self.index, "fr")
        self.assertEqual(fields[0]["values"], ["61292", "XRF"])

    def test_numbers_keep_their_type_and_empty_tiles_are_dropped(self):
        doc = {
            "tiles": [
                {
                    "nodegroup_id": "ng-thickness",
                    "sortorder": 0,
                    "data": {"node-thickness": 2.5},
                },
                {
                    "nodegroup_id": "ng-thickness",
                    "sortorder": 1,
                    "data": {"node-thickness": None},
                },
            ]
        }
        config = {"fields": [{"alias": "thickness", "style": "number"}]}
        fields, _, _ = extract_fields(doc, config, self.index, "en")
        self.assertEqual(fields[0]["values"], [2.5])

    def test_an_indexed_timestamp_is_reduced_to_its_day(self):
        index = make_index(start=("date",), span=("edtf",))
        doc = {
            "tiles": [
                {
                    "nodegroup_id": "ng-start",
                    "sortorder": 0,
                    "data": {"node-start": "2025-02-07 00:00:00+01:00"},
                },
                {
                    "nodegroup_id": "ng-span",
                    "sortorder": 0,
                    "data": {"node-span": "1150-01-01/1199-12-31"},
                },
            ]
        }
        config = {
            "fields": [
                {"alias": "start", "style": "date"},
                {"alias": "span", "style": "date"},
            ]
        }
        fields, _, _ = extract_fields(doc, config, index, "fr")
        self.assertEqual(
            [f["values"] for f in fields],
            [["2025-02-07"], ["1150-01-01/1199-12-31"]],
        )

    def test_a_field_without_value_is_left_out(self):
        config = {"fields": [{"alias": "note", "style": "text"}]}
        fields, link_ids, preview = extract_fields({}, config, self.index, "en")
        self.assertEqual((fields, link_ids, preview), ([], [], None))

    def test_an_empty_configuration_yields_nothing(self):
        self.assertEqual(
            extract_fields({}, {"fields": []}, self.index, "en"), ([], [], None)
        )
        self.assertEqual(extract_fields({}, None, self.index, "en"), ([], [], None))


class FindPreviewTests(SimpleTestCase):
    def setUp(self):
        self.index = make_index(files=("file-list",))

    def doc_with(self, *files):
        return {
            "tiles": [
                {
                    "nodegroup_id": "ng-files",
                    "sortorder": 0,
                    "data": {"node-files": list(files)},
                }
            ]
        }

    def test_the_first_plottable_extension_wins(self):
        doc = self.doc_with(
            {"file_id": "f-0", "name": "spectrum.0"},
            {"file_id": "f-csv", "name": "SPECTRUM.CSV"},
            {"file_id": "f-second", "name": "other.csv"},
        )
        self.assertEqual(
            find_preview(doc, self.index.nodes["files"]),
            {"file_id": "f-csv", "name": "SPECTRUM.CSV"},
        )

    def test_the_formats_converted_upstream_are_not_plottable(self):
        doc = self.doc_with(
            {"file_id": "f-asd", "name": "spectrum.asd"},
            {"file_id": "f-mca", "name": "spectrum.mca"},
            {"file_id": "f-txt", "name": "spectrum.txt"},
            {"file_id": "f-none", "name": "spectrum"},
        )
        self.assertIsNone(find_preview(doc, self.index.nodes["files"]))

    @override_settings(XY_TEXT_FILE_FORMATS=["csv", "txt"])
    def test_the_plottable_formats_are_the_canonical_xy_ones(self):
        doc = self.doc_with({"file_id": "f-txt", "name": "spectrum.txt"})

        self.assertEqual(
            find_preview(doc, self.index.nodes["files"]),
            {"file_id": "f-txt", "name": "spectrum.txt"},
        )


class GraphIndexTests(SimpleTestCase):
    def test_name_for_falls_back_to_english_then_to_any_language(self):
        index = GraphIndex(
            graph_id="g", slug="document", name={"en": "Document"}, nodes={}, labels={}
        )
        self.assertEqual(index.name_for("fr"), "Document")
        other = index._replace(name={"de": "Dokument"})
        self.assertEqual(other.name_for("fr"), "Dokument")
        self.assertEqual(index._replace(name={}).name_for("fr"), "")

    def test_the_index_is_picklable(self):
        import pickle

        index = make_index(note=("string",))
        self.assertEqual(pickle.loads(pickle.dumps(index)), index)


class FakeSearchClient:
    """``es.search`` recording every call and answering canned responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def page(total, ids=(), sources=None):
    """A search response: a total and, optionally, its hits."""
    hits = [{"_id": resource_id} for resource_id in ids]
    for hit, source in zip(hits, sources or []):
        hit["_source"] = source
    return {"hits": {"total": {"value": total}, "hits": hits}}


def buckets(pairs, other=0):
    """The aggregation of the last hop: (uri, nested doc_count, root count)."""
    return {
        "aggregations": {
            "distinct": {
                "ng": {
                    "uris": {
                        "buckets": [
                            {"key": uri, "doc_count": nested, "n": {"doc_count": roots}}
                            for uri, nested, roots in pairs
                        ],
                        "sum_other_doc_count": other,
                    }
                }
            }
        }
    }


def component_index():
    index = make_index(
        item_visual_is_part_of_document=("resource-instance",),
        color_features=("reference",),
    )
    return index._replace(
        graph_id="g-component",
        slug="component",
        name={"en": "Component", "fr": "Composant"},
        targets={"item_visual_is_part_of_document": ["g-document"]},
        lists={"color_features": "list-colors"},
    )


def analysis_index():
    index = make_index(
        component_observed=("resource-instance",),
        analysis_technique_used=("reference",),
        label_of_name=("string",),
    )
    return index._replace(
        graph_id="g-analysis",
        slug="analysis",
        name={"en": "Analyses", "fr": "Analyses"},
        targets={"component_observed": ["g-component"]},
        lists={"analysis_technique_used": "list-techniques"},
    )


def document_index():
    index = make_index(evidence_analyses=("resource-instance",))
    return index._replace(
        graph_id="g-document",
        slug="document",
        targets={"evidence_analyses": ["g-analysis"]},
    )


def hop(slug, alias, direction):
    return {"graph_slug": slug, "alias": alias, "direction": direction}


TWO_HOPS = {
    "key": "analyses",
    "label": {"en": "Analyses", "fr": "Analyses"},
    "path": [
        hop("component", "item_visual_is_part_of_document", "incoming"),
        hop("analysis", "component_observed", "incoming"),
    ],
    "aggregate": [
        {"op": "count"},
        {
            "op": "distinct",
            "alias": "analysis_technique_used",
            "style": "chip",
            "limit": 5,
        },
    ],
    "max_related": 500,
}


class HopQueryTests(SimpleTestCase):
    def setUp(self):
        self.index = analysis_index()

    def test_incoming_matches_the_ids_indexed_under_the_relation_nodegroup(self):
        kwargs = hop_query(
            ["doc-1"],
            hop("analysis", "component_observed", "incoming"),
            self.index,
            2,
            500,
        )
        self.assertEqual(
            kwargs["query"]["bool"]["filter"],
            [
                {"term": {"graph_id": "g-analysis"}},
                {
                    "nested": {
                        "path": "ids",
                        "query": {
                            "bool": {
                                "filter": [
                                    {"terms": {"ids.id": ["doc-1"]}},
                                    {
                                        "term": {
                                            "ids.nodegroup_id": "ng-component_observed"
                                        }
                                    },
                                ]
                            }
                        },
                    }
                },
            ],
        )
        self.assertEqual(kwargs["size"], 500)
        self.assertEqual(kwargs["track_total_hits"], 10000)
        self.assertIs(kwargs["source"], False)

    def test_outgoing_fetches_the_ids_read_off_the_source_document(self):
        kwargs = hop_query(
            ["a-1", "a-2"],
            hop("document", "evidence_analyses", "outgoing"),
            self.index,
            2,
            0,
        )
        self.assertEqual(
            kwargs["query"]["bool"]["filter"],
            [
                {"term": {"graph_id": "g-analysis"}},
                {"ids": {"values": ["a-1", "a-2"]}},
            ],
        )
        self.assertEqual(kwargs["size"], 0)

    def test_both_directions_exclude_what_the_reader_may_not_open(self):
        denied = [
            {
                "nested": {
                    "path": "permissions",
                    "query": {"terms": {"permissions.users_with_no_access": ["2"]}},
                }
            }
        ]
        for direction in ("incoming", "outgoing"):
            with self.subTest(direction=direction):
                kwargs = hop_query(
                    ["x"],
                    hop("analysis", "component_observed", direction),
                    self.index,
                    2,
                    10,
                )
                self.assertEqual(kwargs["query"]["bool"]["must_not"], denied)


class DistinctAggsTests(SimpleTestCase):
    def setUp(self):
        self.node = analysis_index().nodes["analysis_technique_used"]

    def test_the_aggregation_counts_root_documents_per_uri(self):
        self.assertEqual(
            distinct_aggs(self.node, 5),
            {
                "distinct": {
                    "nested": {"path": "references"},
                    "aggs": {
                        "ng": {
                            "filter": {
                                "term": {
                                    "references.nodegroup_id": "ng-analysis_technique_used"
                                }
                            },
                            "aggs": {
                                "uris": {
                                    "terms": {"field": "references.uri", "size": 5},
                                    "aggs": {"n": {"reverse_nested": {}}},
                                }
                            },
                        }
                    },
                }
            },
        )

    def test_the_bucket_count_is_bounded_by_the_setting(self):
        terms = distinct_aggs(self.node, 99)["distinct"]["aggs"]["ng"]["aggs"]["uris"]
        self.assertEqual(terms["terms"]["size"], settings.SUMMARY_MAX_LIMIT)


class OutgoingIdsTests(SimpleTestCase):
    def setUp(self):
        self.node = document_index().nodes["evidence_analyses"]

    def test_tile_values_come_back_once_each_in_order(self):
        doc = {
            "tiles": [
                {
                    "nodegroup_id": "ng-evidence_analyses",
                    "sortorder": 0,
                    "data": {
                        "node-evidence_analyses": [
                            {"resourceId": "a-1"},
                            {"resourceId": "a-2"},
                        ]
                    },
                },
                {
                    "nodegroup_id": "ng-evidence_analyses",
                    "sortorder": 1,
                    "data": {"node-evidence_analyses": [{"resourceId": "a-1"}]},
                },
            ]
        }
        self.assertEqual(outgoing_ids(doc, self.node), ["a-1", "a-2"])

    def test_a_document_without_tiles_reads_the_ids_of_the_nodegroup(self):
        doc = {
            "ids": [
                {"id": "a-1", "nodegroup_id": "ng-evidence_analyses"},
                {"id": "z-9", "nodegroup_id": "ng-other"},
                {"id": "a-1", "nodegroup_id": "ng-evidence_analyses"},
            ]
        }
        self.assertEqual(outgoing_ids(doc, self.node), ["a-1"])

    def test_nothing_points_at_nothing(self):
        self.assertEqual(outgoing_ids({}, self.node), [])


class ParseRollupResponseTests(SimpleTestCase):
    def setUp(self):
        self.aggregate = {
            "op": "distinct",
            "alias": "analysis_technique_used",
            "limit": 5,
        }
        self.response = page(79) | buckets([("61216", 24, 5), ("61292", 8, 2)], other=9)

    def test_counts_come_from_the_reverse_nested_bucket_not_the_nested_one(self):
        parsed = parse_rollup_response(
            self.response, TWO_HOPS, self.aggregate, {"61216": "XRF", "61292": "MALDI"}
        )
        self.assertEqual(parsed["key"], "analyses")
        self.assertEqual(parsed["count"], 79)
        self.assertEqual(
            parsed["items"],
            [
                {"uri": "61216", "label": "XRF", "count": 5},
                {"uri": "61292", "label": "MALDI", "count": 2},
            ],
        )
        self.assertEqual(parsed["more"], 9)
        self.assertFalse(parsed["truncated"])

    def test_a_uri_without_a_label_travels_as_its_uri(self):
        parsed = parse_rollup_response(self.response, TWO_HOPS, self.aggregate, {})
        self.assertEqual(
            [item["label"] for item in parsed["items"]], ["61216", "61292"]
        )

    def test_a_rollup_that_only_counts_carries_no_item(self):
        parsed = parse_rollup_response(page(3), TWO_HOPS, None, {})
        self.assertEqual((parsed["count"], parsed["items"], parsed["more"]), (3, [], 0))


class RunRollupTests(SimpleTestCase):
    def setUp(self):
        self.indexes = {
            "document": document_index(),
            "component": component_index(),
            "analysis": analysis_index(),
        }
        self.doc = {
            "resourceinstanceid": "doc-1",
            "graph_id": "g-document",
            "tiles": [],
        }
        patch = mock.patch(
            "manuspectrum.views.summary_service.list_labels",
            return_value={"61216": "XRF"},
        )
        self.labels = patch.start()
        self.addCleanup(patch.stop)

    def test_a_two_hop_path_runs_exactly_one_search_per_hop(self):
        es = FakeSearchClient(
            page(20, [f"c-{i}" for i in range(20)]),
            page(79) | buckets([("61216", 24, 5)], other=2),
        )
        rollup = run_rollup(
            es, "test_resources", self.doc, TWO_HOPS, self.indexes, 2, "fr"
        )
        self.assertEqual(len(es.calls), 2)
        first, second = es.calls
        self.assertEqual(first["index"], "test_resources")
        self.assertEqual(first["size"], 500)
        self.assertNotIn("aggs", first)
        self.assertEqual(
            first["query"]["bool"]["filter"][1]["nested"]["query"]["bool"]["filter"][0],
            {"terms": {"ids.id": ["doc-1"]}},
        )
        self.assertEqual(
            second["query"]["bool"]["filter"][1]["nested"]["query"]["bool"]["filter"][
                0
            ],
            {"terms": {"ids.id": [f"c-{i}" for i in range(20)]}},
        )
        self.assertEqual(second["size"], 0)
        self.assertEqual(
            second["aggs"]["distinct"]["aggs"]["ng"]["aggs"]["uris"]["terms"]["size"], 5
        )
        self.assertEqual(
            rollup,
            {
                "key": "analyses",
                "label": "Analyses",
                "count": 79,
                "items": [{"uri": "61216", "label": "XRF", "count": 5}],
                "more": 2,
                "truncated": False,
            },
        )
        self.labels.assert_called_once_with("list-techniques", "fr")

    def test_an_intermediate_hop_past_max_related_stops_the_path(self):
        es = FakeSearchClient(page(501, ["c-1"]))
        rollup = run_rollup(
            es, "test_resources", self.doc, TWO_HOPS, self.indexes, 2, "fr"
        )
        self.assertEqual(len(es.calls), 1)
        self.assertTrue(rollup["truncated"])
        self.assertEqual(rollup["count"], 501)
        self.assertEqual(rollup["items"], [])

    def test_an_outgoing_hop_starts_from_the_ids_of_the_document(self):
        doc = {
            "resourceinstanceid": "doc-1",
            "tiles": [
                {
                    "nodegroup_id": "ng-evidence_analyses",
                    "sortorder": 0,
                    "data": {
                        "node-evidence_analyses": [
                            {"resourceId": "a-1"},
                            {"resourceId": "a-2"},
                        ]
                    },
                }
            ],
        }
        config = {
            "key": "evidence",
            "path": [hop("document", "evidence_analyses", "outgoing")],
            "aggregate": [{"op": "count"}],
            "max_related": 500,
        }
        es = FakeSearchClient(page(2))
        rollup = run_rollup(es, "test_resources", doc, config, self.indexes, 2, "en")
        self.assertEqual(len(es.calls), 1)
        self.assertEqual(
            es.calls[0]["query"]["bool"]["filter"],
            [
                {"term": {"graph_id": "g-analysis"}},
                {"ids": {"values": ["a-1", "a-2"]}},
            ],
        )
        self.assertEqual(rollup["count"], 2)
        self.assertEqual(rollup["label"], "Analyses")

    def test_a_hop_before_an_outgoing_one_asks_for_the_indexed_ids(self):
        config = {
            "key": "documents",
            "path": [
                hop("analysis", "component_observed", "incoming"),
                hop("component", "item_visual_is_part_of_document", "outgoing"),
            ],
            "aggregate": [{"op": "count"}],
            "max_related": 500,
        }
        es = FakeSearchClient(
            page(
                1,
                ["c-1"],
                sources=[
                    {
                        "ids": [
                            {
                                "id": "d-1",
                                "nodegroup_id": "ng-item_visual_is_part_of_document",
                            }
                        ]
                    }
                ],
            ),
            page(1),
        )
        rollup = run_rollup(
            es, "test_resources", self.doc, config, self.indexes, 2, "en"
        )
        self.assertEqual(es.calls[0]["source"], ["ids"])
        self.assertEqual(
            es.calls[1]["query"]["bool"]["filter"],
            [{"term": {"graph_id": "g-document"}}, {"ids": {"values": ["d-1"]}}],
        )
        self.assertEqual(rollup["count"], 1)

    def test_a_path_with_nothing_to_start_from_costs_no_search(self):
        config = {
            "key": "evidence",
            "path": [hop("document", "evidence_analyses", "outgoing")],
            "aggregate": [{"op": "count"}],
        }
        es = FakeSearchClient()
        rollup = run_rollup(
            es, "test_resources", self.doc, config, self.indexes, 2, "en"
        )
        self.assertEqual(es.calls, [])
        self.assertEqual(rollup["count"], 0)
        self.assertEqual(rollup["items"], [])

    def test_an_unknown_alias_drops_the_rollup(self):
        config = dict(TWO_HOPS, path=[hop("analysis", "nope", "incoming")])
        es = FakeSearchClient()
        with self.assertLogs("manuspectrum.views.summary_service", "WARNING"):
            self.assertIsNone(
                run_rollup(
                    es, "test_resources", self.doc, config, self.indexes, 2, "en"
                )
            )
        self.assertEqual(es.calls, [])

    def test_a_distinct_on_something_other_than_a_reference_is_skipped(self):
        config = dict(
            TWO_HOPS,
            aggregate=[
                {"op": "count"},
                {"op": "distinct", "alias": "label_of_name", "limit": 5},
            ],
        )
        es = FakeSearchClient(page(20, ["c-1"]), page(79))
        with self.assertLogs("manuspectrum.views.summary_service", "WARNING"):
            rollup = run_rollup(
                es, "test_resources", self.doc, config, self.indexes, 2, "en"
            )
        self.assertNotIn("aggs", es.calls[1])
        self.assertEqual(rollup["count"], 79)
        self.assertEqual(rollup["items"], [])

    def test_the_label_falls_back_to_the_name_of_the_model_reached(self):
        config = dict(TWO_HOPS)
        config.pop("label")
        es = FakeSearchClient(page(1, ["c-1"]), page(1))
        rollup = run_rollup(
            es, "test_resources", self.doc, config, self.indexes, 2, "fr"
        )
        self.assertEqual(rollup["label"], "Analyses")


class ListLabelsTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(cache.clear)

    def test_labels_are_resolved_per_language_and_read_once(self):
        rows = [
            ("61216", "en", "portable X-ray fluorescence"),
            ("61216", "fr", "Fluorescence X portable"),
            ("61292", "en", "MALDI"),
            ("61308", "fr", ""),
        ]
        with mock.patch(
            "manuspectrum.views.summary_service.ListItemValue"
        ) as list_item_value:
            list_item_value.objects.filter.return_value.values_list.return_value = rows
            self.assertEqual(
                list_labels("list-techniques", "fr"),
                {"61216": "Fluorescence X portable", "61292": "MALDI"},
            )
            self.assertEqual(
                list_labels("list-techniques", "fr"),
                {"61216": "Fluorescence X portable", "61292": "MALDI"},
            )
            list_item_value.objects.filter.assert_called_once_with(
                list_item__list_id="list-techniques", valuetype_id="prefLabel"
            )


class FakeES:
    """A client recording its calls and answering canned responses.

    ``get_error`` is raised by ``get``; ``searches`` feeds ``search`` one
    response per call and ``rounds`` feeds ``msearch`` one list of responses
    per round.
    """

    def __init__(self, source=None, docs=None, searches=(), rounds=(), get_error=None):
        self.source = source
        self.docs = docs or {}
        self.searches = list(searches)
        self.rounds = list(rounds)
        self.get_error = get_error
        self.calls = []

    def get(self, index, id):  # noqa: A002 — the elasticsearch-py keyword
        self.calls.append(("get", id))
        if self.get_error is not None:
            raise self.get_error
        return {"_source": self.source}

    def mget(self, index, ids, source_includes=None):
        self.calls.append(("mget", list(ids)))
        return {
            "docs": [
                {
                    "_id": resource_id,
                    "found": resource_id in self.docs,
                    "_source": self.docs.get(resource_id, {}),
                }
                for resource_id in ids
            ]
        }

    def search(self, index, **kwargs):
        self.calls.append(("search", kwargs))
        return self.searches.pop(0)

    def msearch(self, searches):
        self.calls.append(("msearch", searches))
        return {"responses": self.rounds.pop(0)}

    def count(self, name):
        return sum(1 for call in self.calls if call[0] == name)


def summary_index():
    """The Document model as the popup resolves it."""
    index = make_index(
        label_of_name=("string",),
        analysis_technique_used=("reference",),
        current_location=("resource-instance",),
        measurement_point_data=("file-list",),
    )
    return index._replace(
        graph_id="g-document",
        slug="document",
        name={"en": "Document", "fr": "Document"},
    )


ONE_HOP = {
    "key": "components",
    "label": {"en": "Components", "fr": "Composants"},
    "path": [hop("component", "item_visual_is_part_of_document", "incoming")],
    "aggregate": [
        {"op": "count"},
        {"op": "distinct", "alias": "color_features", "style": "chip", "limit": 5},
    ],
    "max_related": 500,
}

SUMMARY_CONFIG = {
    "config_version": 1,
    "fields": [
        {"alias": "label_of_name", "style": "text"},
        {"alias": "analysis_technique_used", "style": "chip"},
        {"alias": "current_location", "style": "link"},
        {"alias": "measurement_point_data", "style": "image"},
    ],
    "rollups": [ONE_HOP],
}


def summary_doc(resource_id="doc-1", geometries=(("point",))):
    return {
        "graph_id": "g-document",
        "resourceinstanceid": resource_id,
        "displayname": [{"language": "fr", "value": "Ms. 59"}],
        "map_popup": [{"language": "fr", "value": "Ms. 59, Avranches"}],
        "geometries": list(geometries),
        "tiles": [
            {
                "nodegroup_id": "ng-label_of_name",
                "sortorder": 0,
                "data": {"node-label_of_name": {"fr": {"value": "Ms. 59"}}},
            },
            {
                "nodegroup_id": "ng-analysis_technique_used",
                "sortorder": 0,
                "data": {
                    "node-analysis_technique_used": [
                        {
                            "uri": "61216",
                            "labels": [
                                {
                                    "value": "FORS",
                                    "language_id": "fr",
                                    "valuetype_id": "prefLabel",
                                }
                            ],
                        }
                    ]
                },
            },
            {
                "nodegroup_id": "ng-current_location",
                "sortorder": 0,
                "data": {"node-current_location": [{"resourceId": "place-1"}]},
            },
            {
                "nodegroup_id": "ng-measurement_point_data",
                "sortorder": 0,
                "data": {
                    "node-measurement_point_data": [
                        {"file_id": "file-1", "name": "spectrum.csv"}
                    ]
                },
            },
        ],
    }


def link_page():
    """The search naming the linked resources of one popup."""
    return page(
        1,
        ids=["place-1"],
        sources=[{"displayname": [{"language": "fr", "value": "Avranches"}]}],
    )


def one_hop_response():
    """The single search of ``ONE_HOP``: 20 components, two colours."""
    response = page(20)
    response.update(buckets([("blue", 9, 5), ("red", 7, 4)], other=2))
    return response


class BuildSummaryTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(cache.clear)
        cache.clear()
        self.index = summary_index()
        self.component = component_index()

    def run_build(self, es, config=SUMMARY_CONFIG, language="fr", user=None):
        indexes = {"g-document": self.index, "g-component": self.component}
        with (
            mock.patch(
                "manuspectrum.views.summary_service.es_client",
                return_value=(es, "test_resources"),
            ),
            mock.patch.object(
                GraphIndex,
                "for_graph",
                side_effect=lambda graph_id: indexes.get(str(graph_id)),
            ),
            mock.patch.object(
                GraphIndex, "for_slug", side_effect=lambda slug: self.component
            ),
            mock.patch(
                "manuspectrum.views.summary_service.load_summary_config",
                return_value=config,
            ),
            mock.patch(
                "manuspectrum.views.summary_service.list_labels",
                return_value={"blue": "Bleu", "red": "Rouge"},
            ),
        ):
            return build_summary("doc-1", language, user or FakeUser(2))

    def test_the_payload_carries_the_model_the_name_the_fields_and_the_rollups(self):
        es = FakeES(
            source=summary_doc(),
            docs={
                "place-1": {"displayname": [{"language": "fr", "value": "Avranches"}]}
            },
            searches=[one_hop_response()],
        )
        payload = self.run_build(es)
        self.assertEqual(payload["id"], "doc-1")
        self.assertTrue(payload["configured"])
        self.assertFalse(payload["degraded"])
        self.assertEqual(payload["graph"], {"slug": "document", "name": "Document"})
        self.assertEqual(payload["name"], "Ms. 59")
        self.assertTrue(payload["has_geometry"])
        self.assertEqual(
            [field["key"] for field in payload["fields"]],
            ["label_of_name", "analysis_technique_used", "current_location"],
        )
        self.assertEqual(
            payload["rollups"],
            [
                {
                    "key": "components",
                    "label": "Composants",
                    "count": 20,
                    "items": [
                        {"uri": "blue", "label": "Bleu", "count": 5},
                        {"uri": "red", "label": "Rouge", "count": 4},
                    ],
                    "more": 2,
                    "truncated": False,
                }
            ],
        )

    def test_a_linked_resource_is_named_by_a_single_mget(self):
        es = FakeES(
            source=summary_doc(),
            docs={
                "place-1": {"displayname": [{"language": "fr", "value": "Avranches"}]}
            },
            searches=[one_hop_response()],
        )
        payload = self.run_build(es)
        link = next(f for f in payload["fields"] if f["style"] == "link")
        self.assertEqual(link["values"], [{"id": "place-1", "label": "Avranches"}])
        self.assertEqual(es.count("mget"), 1)

    def test_a_linked_resource_the_reader_may_not_open_keeps_its_id_alone(self):
        es = FakeES(
            source=summary_doc(),
            docs={
                "place-1": {
                    "displayname": [{"language": "fr", "value": "Avranches"}],
                    "permissions": {"users_with_no_access": [2]},
                }
            },
            searches=[one_hop_response()],
        )
        payload = self.run_build(es)
        link = next(f for f in payload["fields"] if f["style"] == "link")
        self.assertEqual(link["values"], [{"id": "place-1", "label": ""}])

    def test_the_preview_label_is_the_first_technique_chip(self):
        es = FakeES(
            source=summary_doc(),
            docs={},
            searches=[one_hop_response()],
        )
        payload = self.run_build(es)
        self.assertEqual(payload["preview"], {"file_id": "file-1", "label": "FORS"})

    def test_a_preview_without_a_technique_field_carries_no_label(self):
        config = {
            "config_version": 1,
            "fields": [{"alias": "measurement_point_data", "style": "image"}],
            "rollups": [],
        }
        payload = self.run_build(FakeES(source=summary_doc(), docs={}), config=config)
        self.assertEqual(payload["preview"], {"file_id": "file-1", "label": None})

    def test_a_document_without_geometry_says_so(self):
        es = FakeES(
            source=summary_doc(geometries=()), docs={}, searches=[one_hop_response()]
        )
        self.assertFalse(self.run_build(es)["has_geometry"])

    def test_a_model_without_configuration_falls_back_to_the_core_popup(self):
        payload = self.run_build(FakeES(source=summary_doc()), config=None)
        self.assertEqual(
            payload,
            {
                "id": "doc-1",
                "configured": False,
                "graph": {"slug": "document", "name": "Document"},
                "name": "Ms. 59",
                "map_popup": "Ms. 59, Avranches",
            },
        )

    def test_an_id_the_index_does_not_hold_is_not_found(self):
        es = FakeES(get_error=NotFoundError("missing", meta=None, body=None))
        with self.assertRaises(ResourceNotFound):
            self.run_build(es)

    def test_an_unreachable_cluster_degrades_to_the_name_held_in_the_database(self):
        es = FakeES(get_error=TransportError("connection refused"))
        with mock.patch(
            "manuspectrum.views.summary_service.ResourceInstance"
        ) as resource:
            resource.objects.filter.return_value.values.return_value.first.return_value = {
                "descriptors": {"fr": {"name": "Ms. 59"}, "en": {"name": "Ms. 59 en"}},
                "name": {"en": "unused"},
                "graph_id": "g-document",
            }
            payload = self.run_build(es)
        self.assertEqual(
            payload,
            {
                "id": "doc-1",
                "configured": True,
                "graph": {"slug": "document", "name": "Document"},
                "name": "Ms. 59",
                "degraded": True,
            },
        )

    def test_a_failing_rollup_search_degrades_the_whole_payload(self):
        es = FakeES(source=summary_doc(), docs={})
        es.searches = []

        def boom(index, **kwargs):
            raise ApiError("cluster_block_exception", meta=None, body=None)

        es.search = boom
        with mock.patch(
            "manuspectrum.views.summary_service.ResourceInstance"
        ) as resource:
            resource.objects.filter.return_value.values.return_value.first.return_value = {
                "descriptors": {"fr": {"name": "Ms. 59"}},
                "name": None,
                "graph_id": "g-document",
            }
            payload = self.run_build(es)
        self.assertTrue(payload["degraded"])

    def test_a_resource_missing_from_the_database_degrades_without_a_name(self):
        es = FakeES(get_error=TransportError("connection refused"))
        with mock.patch(
            "manuspectrum.views.summary_service.ResourceInstance"
        ) as resource:
            resource.objects.filter.return_value.values.return_value.first.return_value = (
                None
            )
            payload = self.run_build(es)
        self.assertEqual(payload["name"], "")
        self.assertTrue(payload["degraded"])


class BuildSummariesTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(cache.clear)
        cache.clear()
        self.index = summary_index()
        self.component = component_index()

    def run_batch(self, es, ids, config=SUMMARY_CONFIG):
        indexes = {"g-document": self.index, "g-component": self.component}
        with (
            mock.patch(
                "manuspectrum.views.summary_service.es_client",
                return_value=(es, "test_resources"),
            ),
            mock.patch.object(
                GraphIndex,
                "for_graph",
                side_effect=lambda graph_id: indexes.get(str(graph_id)),
            ),
            mock.patch.object(
                GraphIndex, "for_slug", side_effect=lambda slug: self.component
            ),
            mock.patch(
                "manuspectrum.views.summary_service.load_summary_config",
                return_value=config,
            ),
            mock.patch(
                "manuspectrum.views.summary_service.list_labels",
                return_value={"blue": "Bleu", "red": "Rouge"},
            ),
        ):
            return build_summaries(ids, "fr", FakeUser(2))

    def test_a_batch_costs_one_mget_and_one_msearch(self):
        es = FakeES(
            docs={"doc-1": summary_doc("doc-1"), "doc-2": summary_doc("doc-2")},
            rounds=[[link_page(), one_hop_response(), link_page(), one_hop_response()]],
        )
        summaries = self.run_batch(es, ["doc-1", "doc-2"])
        self.assertEqual(sorted(summaries), ["doc-1", "doc-2"])
        self.assertEqual(es.count("mget"), 1)
        self.assertEqual(es.count("msearch"), 1)
        self.assertEqual(es.count("search"), 0)
        link = next(f for f in summaries["doc-2"]["fields"] if f["style"] == "link")
        self.assertEqual(link["values"], [{"id": "place-1", "label": "Avranches"}])
        self.assertEqual(summaries["doc-1"]["rollups"][0]["count"], 20)

    def test_an_id_the_index_does_not_hold_is_left_out(self):
        es = FakeES(
            docs={"doc-1": summary_doc("doc-1")},
            rounds=[[page(0), page(0)]],
        )
        summaries = self.run_batch(es, ["doc-1", "doc-9"])
        self.assertEqual(list(summaries), ["doc-1"])

    def test_an_unreachable_cluster_degrades_every_id_of_the_batch(self):
        es = FakeES(docs={})

        def boom(index, ids, source_includes=None):
            raise TransportError("connection refused")

        es.mget = boom
        with mock.patch(
            "manuspectrum.views.summary_service.ResourceInstance"
        ) as resource:
            resource.objects.filter.return_value.values.return_value.first.return_value = {
                "descriptors": {"fr": {"name": "Ms. 59"}},
                "name": None,
                "graph_id": "g-document",
            }
            summaries = self.run_batch(es, ["doc-1", "doc-2"])
        self.assertEqual(sorted(summaries), ["doc-1", "doc-2"])
        self.assertTrue(all(payload["degraded"] for payload in summaries.values()))

    def test_nothing_asked_costs_nothing(self):
        es = FakeES()
        self.assertEqual(self.run_batch(es, []), {})
        self.assertEqual(es.calls, [])


class PermScopeTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(cache.clear)
        cache.clear()

    def test_a_deployment_without_restriction_shares_one_scope(self):
        with mock.patch(
            "manuspectrum.views.summary_service._count_restrictions", return_value=0
        ):
            self.assertEqual(perm_scope(FakeUser(2)), "public")

    def test_a_restriction_anywhere_keys_the_scope_on_the_reader(self):
        with mock.patch(
            "manuspectrum.views.summary_service._count_restrictions", return_value=1
        ):
            self.assertEqual(perm_scope(FakeUser(7)), "7")

    def test_the_count_is_read_once_per_cache_cycle(self):
        with mock.patch(
            "manuspectrum.views.summary_service._count_restrictions", return_value=0
        ) as count:
            perm_scope(FakeUser(2))
            perm_scope(FakeUser(3))
            count.assert_called_once_with()
