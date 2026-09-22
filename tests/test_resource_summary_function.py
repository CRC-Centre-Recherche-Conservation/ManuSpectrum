import uuid

from django.core.cache import cache
from django.db import transaction
from django.test import SimpleTestCase, TestCase

from arches.app.models import models

from manuspectrum.functions.resource_summary import (
    CONFIG_VERSION,
    SUMMARY_CONFIG_STAMP_KEY,
    SUMMARY_FUNCTION_ID,
    ResourceSummary,
    bump_config_stamp,
    config_cache_key,
    config_stamp,
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


class SavedRow:
    """What ``after_function_save`` touches of a ``FunctionXGraph`` row."""

    def __init__(self, graph_id="g-1"):
        self.graph_id = graph_id
        self.config = dict(details["defaultconfig"])
        self.saved = 0

    def save(self):
        self.saved += 1


class ConfigStampTests(SimpleTestCase):
    def setUp(self):
        cache.delete(SUMMARY_CONFIG_STAMP_KEY)
        self.addCleanup(cache.delete, SUMMARY_CONFIG_STAMP_KEY)

    def test_the_stamp_holds_until_a_save_drops_it(self):
        first = config_stamp()
        self.assertEqual(config_stamp(), first)
        bump_config_stamp()
        self.assertNotEqual(config_stamp(), first)


class AfterFunctionSaveTests(TestCase):
    def setUp(self):
        cache.delete(SUMMARY_CONFIG_STAMP_KEY)
        self.addCleanup(cache.delete, SUMMARY_CONFIG_STAMP_KEY)

    def test_after_function_save_stores_the_config_and_renews_the_stamp(self):
        row = SavedRow()
        first = config_stamp()
        with self.captureOnCommitCallbacks(execute=True):
            ResourceSummary().after_function_save(row, None)
        self.assertEqual(row.saved, 1)
        self.assertEqual(row.config, details["defaultconfig"])
        self.assertNotEqual(config_stamp(), first)

    def test_after_function_save_drops_the_cached_config_of_the_graph(self):
        cache.set(config_cache_key("g-1"), {"stale": True}, 60)
        self.addCleanup(cache.delete, config_cache_key("g-1"))
        with self.captureOnCommitCallbacks(execute=True):
            ResourceSummary().after_function_save(SavedRow(), None)
        self.assertIsNone(cache.get(config_cache_key("g-1")))

    def test_the_caches_are_dropped_only_once_the_transaction_commits(self):
        cache.set(config_cache_key("g-1"), {"stale": True}, 60)
        self.addCleanup(cache.delete, config_cache_key("g-1"))
        first = config_stamp()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            with transaction.atomic():
                ResourceSummary().after_function_save(SavedRow(), None)
                self.assertEqual(cache.get(config_cache_key("g-1")), {"stale": True})
                self.assertEqual(config_stamp(), first)
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        self.assertIsNone(cache.get(config_cache_key("g-1")))
        self.assertNotEqual(config_stamp(), first)


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


class SeedConfigTests(SimpleTestCase):
    def test_every_seed_config_is_valid_and_warning_free(self):
        from manuspectrum.constants.summary_configs import SEED_CONFIGS

        self.assertEqual(
            set(SEED_CONFIGS),
            {"document", "component", "analysis", "characterization", "sample"},
        )
        for slug, config in SEED_CONFIGS.items():
            cleaned, warnings = normalize_config(config)
            self.assertEqual(warnings, [], slug)
            self.assertEqual(cleaned, config, slug)


class MigrationTests(TestCase):
    def test_the_function_row_exists_and_is_attached_to_seeded_graphs(self):
        from manuspectrum.constants.summary_configs import SEED_CONFIGS

        self.assertTrue(models.Function.objects.filter(pk=SUMMARY_FUNCTION_ID).exists())
        for slug in SEED_CONFIGS:
            graph = models.GraphModel.objects.filter(slug=slug).first()
            if graph is None:
                continue
            row = models.FunctionXGraph.objects.get(
                function_id=SUMMARY_FUNCTION_ID, graph=graph
            )
            self.assertEqual(row.config["config_version"], CONFIG_VERSION)
            self.assertNotIn("triggering_nodegroups", row.config)

    def test_the_descriptor_function_row_exists_without_attachments_of_its_own(self):
        from manuspectrum.functions.multi_descriptor import details as descriptor

        row = models.Function.objects.get(pk=descriptor["functionid"])
        self.assertEqual(row.modulename, "multi_descriptor.py")
        self.assertEqual(row.functiontype, descriptor["type"])
        self.assertFalse(
            models.FunctionXGraph.objects.filter(
                function_id=descriptor["functionid"]
            ).exists()
        )


class SummaryCheckTests(TestCase):
    def test_w003_fires_when_a_package_graph_carries_the_function_but_the_row_is_missing(
        self,
    ):
        from manuspectrum.checks import check_summary_function_registered

        models.FunctionXGraph.objects.filter(function_id=SUMMARY_FUNCTION_ID).delete()
        models.Function.objects.filter(pk=SUMMARY_FUNCTION_ID).delete()
        with self.settings(
            SUMMARY_PACKAGE_GRAPH_IDS=["0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"]
        ):
            messages = check_summary_function_registered(None, databases=["default"])
        self.assertEqual([m.id for m in messages], ["manuspectrum.W003"])

    def test_no_message_when_the_checked_databases_exclude_default(self):
        from manuspectrum.checks import check_summary_function_registered

        models.Function.objects.filter(pk=SUMMARY_FUNCTION_ID).delete()
        with self.settings(
            SUMMARY_PACKAGE_GRAPH_IDS=["0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"]
        ):
            self.assertEqual(check_summary_function_registered(None, databases=[]), [])
            self.assertEqual(
                check_summary_function_registered(None, databases=None), []
            )

    def test_nothing_fires_when_no_package_graph_references_the_function(self):
        from manuspectrum.checks import check_summary_function_registered

        models.Function.objects.filter(pk=SUMMARY_FUNCTION_ID).delete()
        with self.settings(SUMMARY_PACKAGE_GRAPH_IDS=[]):
            self.assertEqual(
                check_summary_function_registered(None, databases=["default"]), []
            )
