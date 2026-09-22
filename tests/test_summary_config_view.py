"""Tests for the summary configuration endpoint the designer form reads and writes.

The graph is built here rather than loaded from the package, so the suite runs
on the empty database CI creates. It is slugged ``sc_*`` so it never collides
with a project model on a database that carries the package.
"""

import json
import uuid

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from arches.app.models import models

from manuspectrum.functions.resource_summary import (
    CONFIG_VERSION,
    SUMMARY_FUNCTION_ID,
    config_cache_key,
    details,
)


def valid_config():
    return {
        "config_version": CONFIG_VERSION,
        "fields": [
            {"alias": "label_of_name", "style": "text"},
            {"alias": "period_production", "style": "chip", "max_values": 3},
        ],
        "rollups": [
            {
                "key": "analyses",
                "label": {"en": "Analyses", "fr": "Analyses"},
                "path": [
                    {
                        "graph_slug": "sc_analysis",
                        "alias": "component_observed",
                        "direction": "incoming",
                    }
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


class SummaryConfigViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user("sc_editor", password="pw")
        cls.editor.groups.add(Group.objects.get_or_create(name="Graph Editor")[0])
        cls.outsider = User.objects.create_user("sc_outsider", password="pw")
        cls.outsider.groups.add(Group.objects.get_or_create(name="Guest")[0])

        cls.graph = models.GraphModel.objects.create(
            name={"en": "Document", "fr": "Document"},
            slug="sc_document",
            isresource=True,
        )
        models.Function.objects.get_or_create(
            functionid=SUMMARY_FUNCTION_ID,
            defaults={
                "name": details["name"],
                "functiontype": details["type"],
                "description": details["description"],
                "defaultconfig": details["defaultconfig"],
                "modulename": "resource_summary.py",
                "classname": details["classname"],
                "component": details["component"],
            },
        )

    def setUp(self):
        self.client.force_login(self.editor)
        self.url = reverse("summary-config", args=[self.graph.graphid])
        self.cache_key = config_cache_key(str(self.graph.graphid))
        cache.delete(self.cache_key)

    def put(self, body):
        return self.client.put(self.url, data=body, content_type="application/json")

    def attachment(self):
        return models.FunctionXGraph.objects.get(
            function_id=SUMMARY_FUNCTION_ID, graph_id=self.graph.graphid
        )

    def test_get_on_an_unattached_graph_answers_the_default_configuration(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["graphid"], str(self.graph.graphid))
        self.assertIs(data["attached"], False)
        self.assertEqual(data["config"], details["defaultconfig"])
        self.assertEqual(data["warnings"], [])

    def test_get_on_an_attached_graph_answers_the_stored_configuration(self):
        models.FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID,
            graph_id=self.graph.graphid,
            config=valid_config(),
        )
        data = self.client.get(self.url).json()
        self.assertIs(data["attached"], True)
        self.assertEqual(
            [field["alias"] for field in data["config"]["fields"]],
            ["label_of_name", "period_production"],
        )
        self.assertEqual([r["key"] for r in data["config"]["rollups"]], ["analyses"])
        self.assertEqual(data["warnings"], [])

    def test_get_normalizes_a_stored_configuration_and_reports_its_problems(self):
        config = valid_config()
        config["fields"].append({"alias": "broken", "style": "html"})
        models.FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID,
            graph_id=self.graph.graphid,
            config=config,
        )
        data = self.client.get(self.url).json()
        self.assertNotIn("broken", [f["alias"] for f in data["config"]["fields"]])
        self.assertEqual(len(data["warnings"]), 1)

    def test_put_attaches_the_function_without_triggering_nodegroups(self):
        response = self.put(json.dumps({"config": valid_config()}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIs(data["attached"], True)
        self.assertEqual(data["warnings"], [])
        stored = self.attachment().config
        self.assertNotIn("triggering_nodegroups", stored)
        self.assertEqual(
            [field["alias"] for field in stored["fields"]],
            ["label_of_name", "period_production"],
        )
        self.assertEqual(data["config"], stored)

    def test_put_drops_triggering_nodegroups_the_form_sends_back(self):
        config = valid_config()
        config["triggering_nodegroups"] = []
        self.put(json.dumps({"config": config}))
        self.assertNotIn("triggering_nodegroups", self.attachment().config)

    def test_put_replaces_the_configuration_of_an_already_attached_graph(self):
        models.FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID,
            graph_id=self.graph.graphid,
            config=valid_config(),
        )
        self.put(
            json.dumps(
                {
                    "config": {
                        "config_version": CONFIG_VERSION,
                        "fields": [{"alias": "label_of_name", "style": "text"}],
                        "rollups": [],
                    }
                }
            )
        )
        self.assertEqual(
            models.FunctionXGraph.objects.filter(
                function_id=SUMMARY_FUNCTION_ID, graph_id=self.graph.graphid
            ).count(),
            1,
        )
        self.assertEqual(self.attachment().config["rollups"], [])

    def test_put_invalidates_the_cached_configuration_of_the_graph(self):
        cache.set(self.cache_key, {"stale": True}, 60)
        self.put(json.dumps({"config": valid_config()}))
        self.assertIsNone(cache.get(self.cache_key))

    def test_put_saves_a_configuration_without_its_invalid_entries_and_warns(self):
        config = valid_config()
        config["fields"].append({"alias": "broken", "style": "html"})
        response = self.put(json.dumps({"config": config}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("broken", [f["alias"] for f in data["config"]["fields"]])
        self.assertEqual(len(data["warnings"]), 1)
        self.assertNotIn(
            "broken", [f["alias"] for f in self.attachment().config["fields"]]
        )

    def test_put_of_a_body_that_is_not_json_is_rejected(self):
        response = self.client.put(
            self.url, data="not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            models.FunctionXGraph.objects.filter(
                function_id=SUMMARY_FUNCTION_ID, graph_id=self.graph.graphid
            ).exists()
        )

    def test_put_of_a_json_body_that_is_not_an_object_is_rejected(self):
        response = self.put(json.dumps(["config"]))
        self.assertEqual(response.status_code, 400)

    def test_put_of_an_unsupported_config_version_stores_an_empty_configuration(self):
        response = self.put(json.dumps({"config": {"config_version": 99}}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.attachment().config, details["defaultconfig"])
        self.assertEqual(len(response.json()["warnings"]), 1)

    def test_an_unknown_graph_is_not_found(self):
        url = reverse("summary-config", args=[uuid.uuid4()])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.put(
                url, data="{}", content_type="application/json"
            ).status_code,
            404,
        )

    def test_rejects_a_member_of_no_configuration_group(self):
        self.client.logout()
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.put(json.dumps({"config": valid_config()})).status_code, 403
        )

    def test_rejects_anonymous_callers(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_rejects_a_put_without_a_csrf_token(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.editor)
        response = client.put(
            self.url,
            data=json.dumps({"config": valid_config()}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
