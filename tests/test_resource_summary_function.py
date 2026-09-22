import uuid

from django.test import SimpleTestCase, TestCase

from arches.app.models import models

from manuspectrum.functions.resource_summary import (
    CONFIG_VERSION,
    SUMMARY_FUNCTION_ID,
    details,
    normalize_config,
)


def valid_config():
    return {
        "config_version": CONFIG_VERSION,
        "fields": [
            {"alias": "label_of_name", "style": "text"},
            {
                "alias": "period_production",
                "style": "chip",
                "max_values": 3,
                "label": {"en": "Period", "fr": "Période"},
            },
        ],
        "rollups": [
            {
                "key": "analyses",
                "label": {"en": "Analyses", "fr": "Analyses"},
                "path": [
                    {
                        "graph_slug": "component",
                        "alias": "item_visual_is_part_of_document",
                        "direction": "incoming",
                    },
                    {
                        "graph_slug": "analysis",
                        "alias": "component_observed",
                        "direction": "incoming",
                    },
                ],
                "aggregate": [
                    {"op": "count"},
                    {
                        "op": "distinct",
                        "alias": "analysis_technique_used",
                        "style": "chip",
                        "limit": 8,
                    },
                ],
                "max_related": 500,
            }
        ],
    }


class NormalizeConfigTests(SimpleTestCase):
    def test_a_valid_config_passes_through_without_warnings(self):
        cleaned, warnings = normalize_config(valid_config())
        self.assertEqual(warnings, [])
        self.assertEqual(cleaned, valid_config())

    def test_triggering_nodegroups_is_always_removed(self):
        config = valid_config()
        config["triggering_nodegroups"] = []
        cleaned, _ = normalize_config(config)
        self.assertNotIn("triggering_nodegroups", cleaned)

    def test_unknown_style_op_or_direction_drops_the_entry_with_a_warning(self):
        config = valid_config()
        config["fields"].append({"alias": "x", "style": "html"})
        config["rollups"][0]["aggregate"].append({"op": "range", "alias": "d"})
        config["rollups"][0]["path"][0]["direction"] = "sideways"
        cleaned, warnings = normalize_config(config)
        self.assertEqual(
            [f["alias"] for f in cleaned["fields"]],
            ["label_of_name", "period_production"],
        )
        self.assertEqual(cleaned["rollups"], [])
        self.assertEqual(len(warnings), 3)

    def test_limits_are_clamped_and_a_third_hop_is_refused(self):
        config = valid_config()
        config["fields"][1]["max_values"] = 99
        config["rollups"][0]["aggregate"][1]["limit"] = 99
        config["rollups"][0]["max_related"] = 99999
        cleaned, warnings = normalize_config(config)
        self.assertEqual(cleaned["fields"][1]["max_values"], 10)
        self.assertEqual(cleaned["rollups"][0]["aggregate"][1]["limit"], 10)
        self.assertEqual(cleaned["rollups"][0]["max_related"], 500)
        config["rollups"][0]["path"].append(
            {"graph_slug": "sample", "alias": "x", "direction": "incoming"}
        )
        cleaned, warnings = normalize_config(config)
        self.assertEqual(cleaned["rollups"], [])
        self.assertTrue(any("path" in w for w in warnings))

    def test_a_missing_or_foreign_version_yields_an_empty_config(self):
        for config in (None, {}, {"config_version": 99, "fields": [{"alias": "a"}]}):
            cleaned, warnings = normalize_config(config)
            self.assertEqual(cleaned["fields"], [])
            self.assertEqual(cleaned["rollups"], [])
            self.assertEqual(cleaned["config_version"], CONFIG_VERSION)

    def test_details_declare_a_summary_function_without_triggering_nodegroups(self):
        self.assertEqual(details["functionid"], SUMMARY_FUNCTION_ID)
        self.assertEqual(details["type"], "summary")
        self.assertNotIn("triggering_nodegroups", details["defaultconfig"])
        self.assertEqual(
            details["component"], "views/components/functions/resource-summary"
        )


class TileSaveExclusionTests(TestCase):
    """The query Arches runs before and after every tile save
    (arches/app/models/tile.py:826-844) must never select this function."""

    def test_the_tile_save_function_query_does_not_match_a_summary_config(self):
        from django.db.models import Q

        function, _ = models.Function.objects.get_or_create(
            functionid=SUMMARY_FUNCTION_ID,
            defaults={
                "name": details["name"],
                "functiontype": details["type"],
                "defaultconfig": details["defaultconfig"],
                "modulename": "resource_summary.py",
                "classname": details["classname"],
                "component": details["component"],
            },
        )
        graph = (
            models.GraphModel.objects.filter(isresource=True)
            .exclude(graphid="ff623370-fa12-11e6-b98b-6c4008b05c4c")
            .first()
        ) or models.GraphModel.objects.create(
            name="summary exclusion test",
            isresource=True,
            slug="summary_exclusion_test",
        )
        models.FunctionXGraph.objects.update_or_create(
            function=function, graph=graph, defaults={"config": valid_config()}
        )
        nodegroup_id = str(uuid.uuid4())
        matched = models.FunctionXGraph.objects.filter(
            Q(graph_id=graph.graphid),
            Q(config__contains={"triggering_nodegroups": [nodegroup_id]})
            | Q(config__triggering_nodegroups__exact=[]),
            ~Q(function__functiontype="primarydescriptors"),
        )
        self.assertFalse(matched.filter(function=function).exists())
