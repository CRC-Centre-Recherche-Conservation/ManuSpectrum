"""Tests for the summary configuration endpoint the designer form reads and writes.

The graph is built here rather than loaded from the package, so the suite runs
on the empty database CI creates. It is slugged ``sc_*`` so it never collides
with a project model on a database that carries the package.
"""

import json
import threading
import time
import uuid
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import translation

from arches.app.models import models

from manuspectrum.functions.resource_summary import (
    CONFIG_VERSION,
    SUMMARY_FUNCTION_ID,
    config_cache_key,
    config_stamp,
    details,
)
from manuspectrum.views.summary_config import SummaryConfigView


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


def build_fixtures(holder):
    """Editor, outsider, the ``sc_document`` model and the summary Function."""
    holder.editor = User.objects.create_user("sc_editor", password="pw")
    holder.editor.groups.add(Group.objects.get_or_create(name="Graph Editor")[0])
    holder.outsider = User.objects.create_user("sc_outsider", password="pw")
    holder.outsider.groups.add(Group.objects.get_or_create(name="Guest")[0])

    holder.graph = models.GraphModel.objects.create(
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


class SummaryConfigViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        build_fixtures(cls)

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
        with self.captureOnCommitCallbacks(execute=True):
            self.put(json.dumps({"config": valid_config()}))
        self.assertIsNone(cache.get(self.cache_key))

    def test_put_renews_the_stamp_the_memoised_summaries_carry(self):
        before = config_stamp()
        with self.captureOnCommitCallbacks(execute=True):
            self.put(json.dumps({"config": valid_config()}))
        self.assertNotEqual(config_stamp(), before)

    def test_put_of_an_empty_configuration_over_a_stored_one_warns(self):
        models.FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID,
            graph_id=self.graph.graphid,
            config=valid_config(),
        )
        response = self.put(json.dumps({"config": details["defaultconfig"]}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.attachment().config, details["defaultconfig"])
        self.assertEqual(
            response.json()["warnings"],
            ["config: an empty configuration replaces the stored one"],
        )

    def test_put_of_a_body_without_a_configuration_over_a_stored_one_warns(self):
        models.FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID,
            graph_id=self.graph.graphid,
            config=valid_config(),
        )
        response = self.put(json.dumps({}))
        self.assertEqual(
            response.json()["warnings"],
            ["config: an empty configuration replaces the stored one"],
        )

    def test_the_empty_configuration_warning_is_written_in_the_active_language(self):
        models.FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID,
            graph_id=self.graph.graphid,
            config=valid_config(),
        )
        with translation.override("fr"):
            response = self.client.put(
                reverse("summary-config", args=[self.graph.graphid]),
                data=json.dumps({"config": details["defaultconfig"]}),
                content_type="application/json",
            )
        self.assertEqual(
            response.json()["warnings"],
            ["config : une configuration vide remplace celle enregistrée"],
        )

    def test_put_of_an_empty_configuration_over_nothing_stored_does_not_warn(self):
        response = self.put(json.dumps({"config": details["defaultconfig"]}))
        self.assertEqual(response.json()["warnings"], [])

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

    def etag(self):
        return self.client.get(self.url)["ETag"]

    def attach(self, config=None):
        return models.FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID,
            graph=self.graph,
            config=config or valid_config(),
        )

    def put_config(self, config, **headers):
        return self.client.put(
            self.url,
            data=json.dumps({"config": config}),
            content_type="application/json",
            headers=headers,
        )

    def test_get_carries_an_etag(self):
        self.assertRegex(self.client.get(self.url)["ETag"], r'^"[0-9a-f]{32}"$')

    def test_the_etag_moves_when_the_stored_configuration_changes(self):
        before = self.etag()
        self.attach()
        self.assertNotEqual(before, self.etag())

    def test_the_etag_is_stable_between_two_reads(self):
        self.attach()
        self.assertEqual(self.etag(), self.etag())

    def test_put_carrying_the_current_etag_is_accepted(self):
        response = self.put_config(valid_config(), **{"If-Match": self.etag()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["ETag"], self.etag())

    def test_put_carrying_a_stale_etag_is_refused_without_writing(self):
        stale = self.etag()
        self.attach()
        response = self.put_config(
            {"config_version": 1, "fields": [], "rollups": []}, **{"If-Match": stale}
        )
        self.assertEqual(response.status_code, 412)
        self.assertEqual(response["ETag"], self.etag())
        self.assertIn("error", json.loads(response.content))
        stored = models.FunctionXGraph.objects.get(
            function_id=SUMMARY_FUNCTION_ID, graph=self.graph
        )
        self.assertEqual(stored.config, valid_config())

    def test_the_conflict_message_is_translated(self):
        stale = self.etag()
        self.attach()
        with translation.override("fr"):
            url = reverse("summary-config", args=[self.graph.graphid])
            response = self.client.put(
                url,
                data=json.dumps({"config": valid_config()}),
                content_type="application/json",
                headers={"If-Match": stale},
            )
        self.assertEqual(response.status_code, 412)
        self.assertIn("Rechargez", json.loads(response.content)["error"])

    def test_put_without_if_match_writes_unconditionally(self):
        self.attach()
        self.assertEqual(self.put_config(valid_config()).status_code, 200)

    def test_a_tag_weakened_by_a_compressing_proxy_still_matches(self):
        response = self.put_config(valid_config(), **{"If-Match": "W/" + self.etag()})
        self.assertEqual(response.status_code, 200)

    def test_a_weakened_stale_tag_is_still_refused(self):
        stale = self.etag()
        self.attach()
        response = self.put_config(valid_config(), **{"If-Match": "W/" + stale})
        self.assertEqual(response.status_code, 412)

    def test_a_star_matches_any_version(self):
        self.attach()
        self.assertEqual(
            self.put_config(valid_config(), **{"If-Match": "*"}).status_code, 200
        )

    def test_one_of_several_listed_tags_matching_is_enough(self):
        response = self.put_config(
            valid_config(), **{"If-Match": f'"0000", {self.etag()}'}
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_detaches_the_function(self):
        self.attach()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(self.url, headers={"If-Match": self.etag()})
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertFalse(body["attached"])
        self.assertEqual(body["config"], details["defaultconfig"])
        self.assertFalse(
            models.FunctionXGraph.objects.filter(
                function_id=SUMMARY_FUNCTION_ID, graph=self.graph
            ).exists()
        )
        self.assertEqual(response["ETag"], self.etag())

    def test_delete_drops_the_cached_configuration_and_the_stamp_on_commit(self):
        self.attach()
        stamp = config_stamp()
        cache.set(self.cache_key, {"stale": True}, 60)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.client.delete(self.url)
        self.assertIsNotNone(cache.get(self.cache_key))
        for callback in callbacks:
            callback()
        self.assertIsNone(cache.get(self.cache_key))
        self.assertNotEqual(config_stamp(), stamp)

    def test_delete_carrying_a_stale_etag_is_refused(self):
        stale = self.etag()
        self.attach()
        response = self.client.delete(self.url, headers={"If-Match": stale})
        self.assertEqual(response.status_code, 412)
        self.assertTrue(
            models.FunctionXGraph.objects.filter(
                function_id=SUMMARY_FUNCTION_ID, graph=self.graph
            ).exists()
        )

    def test_put_after_a_delete_by_someone_else_is_refused(self):
        self.attach()
        loaded = self.etag()
        self.client.delete(self.url, headers={"If-Match": loaded})
        self.assertEqual(
            self.put_config(valid_config(), **{"If-Match": loaded}).status_code, 412
        )

    def test_delete_of_an_unattached_model_answers_the_detached_state(self):
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json.loads(response.content)["attached"])

    def test_delete_is_refused_to_a_reader_outside_the_editor_groups(self):
        self.attach()
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.delete(self.url).status_code, 403)
        self.assertTrue(
            models.FunctionXGraph.objects.filter(
                function_id=SUMMARY_FUNCTION_ID, graph=self.graph
            ).exists()
        )

    def test_delete_of_something_that_is_not_a_resource_model_is_not_found(self):
        url = reverse("summary-config", args=[uuid.uuid4()])
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_delete_without_the_csrf_token_is_refused(self):
        self.attach()
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.editor)
        self.assertEqual(client.delete(self.url).status_code, 403)

    def test_a_row_deleted_by_the_function_manager_drops_the_configuration(self):
        row = self.attach()
        cache.set(self.cache_key, {"stale": True}, 60)
        with self.captureOnCommitCallbacks(execute=True):
            row.delete()
        self.assertIsNone(cache.get(self.cache_key))

    def test_another_function_deleted_keeps_the_configuration(self):
        other = models.Function.objects.exclude(functionid=SUMMARY_FUNCTION_ID).first()
        if other is None:
            self.skipTest("no other function on this database")
        row = models.FunctionXGraph.objects.create(
            function=other, graph=self.graph, config={}
        )
        cache.set(self.cache_key, {"kept": True}, 60)
        with self.captureOnCommitCallbacks(execute=True):
            row.delete()
        self.assertEqual(cache.get(self.cache_key), {"kept": True})


class SummaryConfigConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        build_fixtures(self)
        models.FunctionXGraph.objects.create(
            function_id=SUMMARY_FUNCTION_ID, graph=self.graph, config=valid_config()
        )
        self.url = reverse("summary-config", args=[self.graph.graphid])

    def race(self, *writes):
        """Run the writes on two threads, each on its own connection, reading slowly."""
        client = Client()
        client.force_login(self.editor)
        etag = client.get(self.url)["ETag"]
        read = SummaryConfigView.attachment
        statuses = []

        def slow_read(view, graphid):
            row = read(view, graphid)
            time.sleep(0.3)
            return row

        def run(write):
            try:
                writer = Client()
                writer.force_login(self.editor)
                statuses.append(write(writer, etag).status_code)
            finally:
                connection.close()

        with mock.patch.object(SummaryConfigView, "attachment", slow_read):
            threads = [threading.Thread(target=run, args=(write,)) for write in writes]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        return sorted(statuses)

    def put_with(self, config):
        return lambda writer, etag: writer.put(
            self.url,
            data=json.dumps({"config": config}),
            content_type="application/json",
            headers={"If-Match": etag},
        )

    def delete_with(self):
        return lambda writer, etag: writer.delete(self.url, headers={"If-Match": etag})

    def test_two_writers_carrying_the_same_etag_cannot_both_write(self):
        first, second = valid_config(), valid_config()
        first["fields"] = first["fields"][:1]
        second["rollups"] = []
        self.assertEqual(
            self.race(self.put_with(first), self.put_with(second)), [200, 412]
        )

    def test_a_save_racing_a_removal_cannot_both_succeed(self):
        changed = valid_config()
        changed["fields"] = changed["fields"][:1]
        self.assertEqual(
            self.race(self.put_with(changed), self.delete_with()), [200, 412]
        )

    def test_two_first_saves_of_an_unattached_model_cannot_both_write(self):
        models.FunctionXGraph.objects.filter(
            function_id=SUMMARY_FUNCTION_ID, graph=self.graph
        ).delete()
        first, second = valid_config(), valid_config()
        first["fields"] = first["fields"][:1]
        second["rollups"] = []
        self.assertEqual(
            self.race(self.put_with(first), self.put_with(second)), [200, 412]
        )
        rows = models.FunctionXGraph.objects.filter(
            function_id=SUMMARY_FUNCTION_ID, graph=self.graph
        )
        self.assertEqual(rows.count(), 1)
