"""The Sample summary counts the analyses that USED the sample (D11), in the seed and in the stored row.

Usage:
    python manage.py test tests.test_summary_sample_hop --settings="tests.test_settings"
"""

import importlib
import uuid

from django.apps import apps
from django.test import TestCase

from arches.app.models.models import FunctionXGraph, GraphModel

from manuspectrum.constants.summary_configs import SEED_CONFIGS
from manuspectrum.functions.resource_summary import SUMMARY_FUNCTION_ID

migration = importlib.import_module("manuspectrum.migrations.0005_sample_summary_hop")
LIFECYCLE = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"


class SampleHopTests(TestCase):
    def hops(self, config):
        return [hop for rollup in config["rollups"] for hop in rollup["path"]]

    def test_the_seed_follows_sample_used(self):
        self.assertEqual(
            self.hops(SEED_CONFIGS["sample"]),
            [
                {
                    "graph_slug": "analysis",
                    "alias": "sample_used",
                    "direction": "incoming",
                }
            ],
        )

    def test_the_stored_row_is_fixed_once_and_nothing_else_moves(self):
        graph = GraphModel.objects.create(
            graphid=uuid.uuid4(),
            name="sample",
            slug="sample",
            isresource=True,
            is_active=True,
            resource_instance_lifecycle_id=LIFECYCLE,
        )
        config = {
            "fields": [{"alias": "label_of_name", "style": "text"}],
            "rollups": [
                {
                    "key": "analyses",
                    "path": [dict(migration.OLD_HOP)],
                    "aggregate": [{"op": "count"}],
                },
                {
                    "key": "other",
                    "path": [
                        {"graph_slug": "project", "alias": "x", "direction": "outgoing"}
                    ],
                    "aggregate": [],
                },
            ],
        }
        row = FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID, graph=graph, config=config
        )

        migration.fix_sample_hop(apps, None)
        migration.fix_sample_hop(apps, None)

        row.refresh_from_db()
        self.assertEqual(row.config["rollups"][0]["path"][0]["alias"], "sample_used")
        self.assertEqual(row.config["rollups"][1], config["rollups"][1])
        self.assertEqual(row.config["fields"], config["fields"])

    def test_a_database_without_the_sample_model_is_left_alone(self):
        with self.assertNumQueries(1):
            migration.fix_sample_hop(apps, None)
