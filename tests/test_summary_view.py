"""HTTP contract of the summary endpoint: guard, memo, ETag, headers, batch.

Elasticsearch is never reached: the client, the graph index and the
configuration reader of the service are patched, so a request exercises the
view and the assembly together against recorded responses. The fixtures come
from ``test_summary_service`` rather than being copied here. The permission
guard is patched as well, except in ``SummaryBatchParityTests``, which decides
on real resources and grants.
"""

import contextlib
import json
import uuid
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.db.models.signals import post_delete, post_save
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from elasticsearch import NotFoundError, TransportError
from guardian.shortcuts import assign_perm

from guardian.models import GroupObjectPermission

from arches.app.models.models import (
    GraphModel,
    GraphXPublishedGraph,
    Node,
    NodeGroup,
    ResourceInstance,
    UserProfile,
)
from arches.app.utils import permission_backend

from manuspectrum.functions.resource_summary import ResourceSummary, details
from manuspectrum.views import summary as summary_view
from manuspectrum.views.summary_service import (
    RESTRICTED_CACHE_KEY,
    RESTRICTED_NODEGROUPS_CACHE_KEY,
    SLUG_CACHE_KEY,
    GraphIndex,
    _count_nodegroup_restrictions,
)

from tests.test_summary_service import (
    SUMMARY_CONFIG,
    FakeES,
    component_index,
    link_page,
    one_hop_response,
    summary_doc,
    summary_index,
)

DOC_ONE = str(uuid.uuid4())
DOC_TWO = str(uuid.uuid4())

#: Seeded by ``models.11042_add_resource_instance_lifecycle``.
DEFAULT_LIFECYCLE_ID = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"


class SavedRow:
    """What ``after_function_save`` touches of a ``FunctionXGraph`` row."""

    def __init__(self, graph_id="g-document"):
        self.graph_id = graph_id
        self.config = dict(details["defaultconfig"])

    def save(self):
        pass


class SummaryTestCase(TestCase):
    """Fixtures and patches shared by the single and the batch endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user("summary_reader", password="pw")

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.force_login(self.reader)
        self.indexes = {"g-document": summary_index(), "g-component": component_index()}

    def patched(self, es, config=SUMMARY_CONFIG, readable=True, real_guard=False):
        """Every reader of the database or of the cluster, replaced.

        The read check of both endpoints answers ``readable``; ``real_guard``
        leaves it to Arches, on the rows and grants of the test database.
        """
        patches = [
            mock.patch(
                "manuspectrum.views.summary_service.es_client",
                return_value=(es, "test_resources"),
            ),
            mock.patch.object(
                GraphIndex,
                "for_graph",
                side_effect=lambda graph_id: self.indexes.get(str(graph_id)),
            ),
            mock.patch.object(
                GraphIndex,
                "for_slug",
                side_effect=lambda slug: self.indexes["g-component"],
            ),
            mock.patch(
                "manuspectrum.views.summary_service.load_summary_config",
                return_value=config,
            ),
            mock.patch(
                "manuspectrum.views.summary_service.list_labels",
                return_value={"blue": "Bleu", "red": "Rouge"},
            ),
        ]
        if not real_guard:
            patches.append(
                mock.patch(
                    "manuspectrum.views.summary.user_can_read_resource",
                    return_value=readable,
                )
            )
        return patches

    def get(
        self,
        es,
        resourceid=DOC_ONE,
        config=SUMMARY_CONFIG,
        readable=True,
        real_guard=False,
        **extra,
    ):
        with contextlib.ExitStack() as stack:
            for patch in self.patched(
                es, config=config, readable=readable, real_guard=real_guard
            ):
                stack.enter_context(patch)
            return self.client.get(reverse("api-summary", args=[resourceid]), **extra)

    def batch(self, es, ids, config=SUMMARY_CONFIG, readable=True, real_guard=False):
        with contextlib.ExitStack() as stack:
            for patch in self.patched(
                es, config=config, readable=readable, real_guard=real_guard
            ):
                stack.enter_context(patch)
            return self.client.get(reverse("api-summary-batch"), {"ids": ids})

    def one_document(self, count=1):
        return FakeES(
            source=summary_doc(DOC_ONE),
            docs={
                "place-1": {"displayname": [{"language": "en", "value": "Avranches"}]}
            },
            searches=[one_hop_response() for _ in range(count)],
        )


class SummaryEndpointTests(SummaryTestCase):
    def test_a_resource_the_reader_may_not_open_is_refused(self):
        response = self.get(self.one_document(), readable=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content), {"error": "forbidden"})
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_an_id_the_index_does_not_hold_is_not_found(self):
        es = FakeES(get_error=NotFoundError("missing", meta=None, body=None))
        response = self.get(es)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content), {"error": "not_found"})

    def test_the_payload_is_the_summary_of_the_resource(self):
        response = self.get(self.one_document())
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["id"], DOC_ONE)
        self.assertEqual(payload["graph"]["slug"], "document")
        self.assertEqual(payload["rollups"][0]["count"], 20)
        self.assertNotIn("<", response.content.decode())

    def test_a_public_deployment_lets_a_shared_cache_keep_the_payload(self):
        response = self.get(self.one_document())
        self.assertEqual(response["Cache-Control"], "public, max-age=300")

    def test_a_restricted_deployment_keeps_the_payload_private(self):
        with mock.patch(
            "manuspectrum.views.summary_service._count_restrictions", return_value=2
        ):
            response = self.get(self.one_document())
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_the_payload_is_built_once_for_two_requests(self):
        es = self.one_document()
        self.assertEqual(self.get(es).status_code, 200)
        self.assertEqual(self.get(es).status_code, 200)
        self.assertEqual(es.count("get"), 1)

    def test_a_conditional_request_is_answered_without_a_body(self):
        es = self.one_document()
        first = self.get(es)
        etag = first["ETag"]
        self.assertTrue(etag)
        second = self.get(es, HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second["ETag"], etag)
        self.assertEqual(second.content, b"")

    def test_a_client_holding_any_representation_is_answered_without_a_body(self):
        es = self.one_document()
        etag = self.get(es)["ETag"]
        response = self.get(es, HTTP_IF_NONE_MATCH="*")
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response["ETag"], etag)

    def test_a_conditional_request_listing_several_tags_names_the_payload(self):
        es = self.one_document()
        etag = self.get(es)["ETag"]
        response = self.get(es, HTTP_IF_NONE_MATCH=f'"other", {etag}')
        self.assertEqual(response.status_code, 304)

    def test_a_conditional_request_holding_the_weak_tag_names_the_payload(self):
        es = self.one_document()
        etag = self.get(es)["ETag"]
        response = self.get(es, HTTP_IF_NONE_MATCH=f"W/{etag}")
        self.assertEqual(response.status_code, 304)

    def test_a_configuration_saved_in_the_designer_rebuilds_the_payload(self):
        es = self.one_document(count=2)
        self.get(es)
        with self.captureOnCommitCallbacks(execute=True):
            ResourceSummary().after_function_save(SavedRow(), None)
        self.assertEqual(self.get(es).status_code, 200)
        self.assertEqual(es.count("get"), 2)

    def test_the_configuration_stamp_is_read_once_per_request(self):
        with mock.patch(
            "manuspectrum.views.summary.config_stamp", return_value="stamp"
        ) as stamp:
            self.get(self.one_document())
        self.assertEqual(stamp.call_count, 1)

    def test_a_degraded_payload_expires_from_its_build_not_from_its_last_read(self):
        es = FakeES(get_error=TransportError("connection refused"))
        with (
            mock.patch(
                "manuspectrum.views.summary_service.ResourceInstance"
            ) as resource,
            mock.patch(
                "manuspectrum.views.summary.shorten_degraded",
                wraps=summary_view.shorten_degraded,
            ) as shorten,
        ):
            resource.objects.filter.return_value.values.return_value.first.return_value = {
                "descriptors": {"en": {"name": "Ms. 59"}},
                "name": None,
                "graph_id": "g-document",
            }
            with mock.patch.object(
                summary_view.cache, "set", wraps=summary_view.cache.set
            ) as cache_set:
                first = self.get(es)
            self.get(es)
        self.assertTrue(json.loads(first.content)["degraded"])
        self.assertEqual(shorten.call_count, 1)
        self.assertEqual(es.count("get"), 1)
        self.assertTrue(
            any(
                call.args[1].get("degraded")
                and call.args[2] == summary_view.DEGRADED_TTL
                for call in cache_set.call_args_list
                if len(call.args) >= 3 and isinstance(call.args[1], dict)
            )
        )

    def test_two_readers_of_a_restricted_deployment_do_not_share_the_memo(self):
        other = User.objects.create_user("summary_other", password="pw")
        es = self.one_document(count=2)
        with mock.patch(
            "manuspectrum.views.summary_service._count_restrictions", return_value=2
        ):
            self.get(es)
            self.client.force_login(other)
            self.get(es)
        self.assertEqual(es.count("get"), 2)

    def test_two_readers_under_a_nodegroup_grant_do_not_share_the_memo(self):
        other = User.objects.create_user("summary_other", password="pw")
        es = self.one_document(count=2)
        with (
            mock.patch(
                "manuspectrum.views.summary_service._count_nodegroup_restrictions",
                return_value=1,
            ),
            mock.patch.object(
                UserProfile,
                "viewable_nodegroups",
                new_callable=mock.PropertyMock,
                return_value={"ng-analysis_technique_used"},
            ),
        ):
            first = self.get(es)
            self.client.force_login(other)
            self.get(es)
        self.assertEqual(es.count("get"), 2)
        self.assertEqual(first["Cache-Control"], "private, no-store")
        self.assertEqual(
            [field["key"] for field in json.loads(first.content)["fields"]],
            ["analysis_technique_used"],
        )

    def test_a_model_without_configuration_carries_the_core_popup(self):
        response = self.get(FakeES(source=summary_doc(DOC_ONE)), config=None)
        payload = json.loads(response.content)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["map_popup"], "Ms. 59, Avranches")

    def test_a_malformed_id_does_not_resolve(self):
        response = self.client.get("/en/api/summary/not-a-uuid")
        self.assertEqual(response.status_code, 404)


class SummaryBatchEndpointTests(SummaryTestCase):
    def two_documents(self):
        return FakeES(
            docs={DOC_ONE: summary_doc(DOC_ONE), DOC_TWO: summary_doc(DOC_TWO)},
            rounds=[[link_page(), one_hop_response(), link_page(), one_hop_response()]],
        )

    def test_more_ids_than_the_bound_are_refused(self):
        ids = ",".join(str(uuid.uuid4()) for _ in range(26))
        response = self.batch(FakeES(), ids)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {"error": "too_many_ids"})

    def test_a_batch_answers_one_payload_per_id(self):
        response = self.batch(self.two_documents(), f"{DOC_ONE},{DOC_TWO}")
        self.assertEqual(response.status_code, 200)
        summaries = json.loads(response.content)["summaries"]
        self.assertEqual(sorted(summaries), sorted([DOC_ONE, DOC_TWO]))
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_a_malformed_id_is_ignored_rather_than_refused(self):
        es = FakeES(
            docs={DOC_ONE: summary_doc(DOC_ONE)},
            rounds=[[link_page(), one_hop_response()]],
        )
        response = self.batch(es, f"{DOC_ONE},not-a-uuid,")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(json.loads(response.content)["summaries"]), [DOC_ONE])

    def test_an_id_the_reader_may_not_open_is_omitted(self):
        response = self.batch(
            self.two_documents(), f"{DOC_ONE},{DOC_TWO}", readable=False
        )
        self.assertEqual(json.loads(response.content)["summaries"], {})

    def test_an_id_already_memoised_is_not_rebuilt(self):
        single = self.one_document()
        self.get(single)
        es = FakeES(
            docs={DOC_TWO: summary_doc(DOC_TWO)},
            rounds=[[link_page(), one_hop_response()]],
        )
        response = self.batch(es, f"{DOC_ONE},{DOC_TWO}")
        summaries = json.loads(response.content)["summaries"]
        self.assertEqual(sorted(summaries), sorted([DOC_ONE, DOC_TWO]))
        self.assertEqual(es.calls[0], ("mget", [DOC_TWO]))

    def test_the_configuration_stamp_is_read_once_for_the_whole_batch(self):
        with mock.patch(
            "manuspectrum.views.summary.config_stamp", return_value="stamp"
        ) as stamp:
            self.batch(self.two_documents(), f"{DOC_ONE},{DOC_TWO}")
        self.assertEqual(stamp.call_count, 1)

    def test_a_configuration_saved_in_the_designer_rebuilds_a_warmed_payload(self):
        self.batch(self.two_documents(), f"{DOC_ONE},{DOC_TWO}")
        with self.captureOnCommitCallbacks(execute=True):
            ResourceSummary().after_function_save(SavedRow(), None)
        es = self.two_documents()
        self.batch(es, f"{DOC_ONE},{DOC_TWO}")
        self.assertEqual(es.calls[0], ("mget", [DOC_ONE, DOC_TWO]))

    def test_nothing_asked_answers_nothing(self):
        response = self.batch(FakeES(), "")
        self.assertEqual(json.loads(response.content), {"summaries": {}})


class ParityES(FakeES):
    """Answers ``get`` per id, and raises for an id the index does not hold."""

    def get(self, index, id):  # noqa: A002 — the elasticsearch-py keyword
        self.calls.append(("get", id))
        if id not in self.docs:
            raise NotFoundError("missing", meta=None, body=None)
        return {"_source": self.docs[id]}


class SummaryBatchParityTests(SummaryTestCase):
    """The batch keeps exactly the ids the single endpoint would not refuse."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        graph = GraphModel.objects.create(
            name="sp_readable",
            slug="sp_readable",
            isresource=True,
            resource_instance_lifecycle_id=DEFAULT_LIFECYCLE_ID,
        )
        Node.objects.create(
            graph=graph,
            nodegroup=NodeGroup.objects.create(cardinality="1"),
            name="sp_node",
            alias="sp_node",
            datatype="string",
            istopnode=False,
        )
        cls.open_one = str(ResourceInstance.objects.create(graph=graph).pk)
        cls.open_two = str(ResourceInstance.objects.create(graph=graph).pk)
        forbidden = ResourceInstance.objects.create(graph=graph)
        assign_perm("no_access_to_resourceinstance", cls.reader, forbidden)
        cls.forbidden = str(forbidden.pk)
        cls.missing = str(uuid.uuid4())

    def parity_es(self):
        """The index as the batch reads it.

        The forbidden resource is held under both spellings of its id, so only
        the read check keeps it out of an answer.
        """
        return ParityES(
            docs={
                rid: {"displayname": [{"language": "en", "value": "x"}]}
                for rid in (
                    self.open_one,
                    self.open_two,
                    self.forbidden,
                    self.forbidden.upper(),
                )
            }
        )

    def batch_ids(self, ids, es=None):
        """The summaries the batch answers for ``ids``, under Arches' own check."""
        response = self.batch(es or self.parity_es(), ",".join(ids), real_guard=True)
        return json.loads(response.content)["summaries"]

    def test_the_batch_keeps_the_ids_the_single_endpoint_serves(self):
        es = self.parity_es()
        ids = [self.open_one, self.open_two, self.forbidden, self.missing]
        summaries = self.batch_ids(ids, es)
        single = {rid: self.get(es, rid, real_guard=True).status_code for rid in ids}
        self.assertEqual(
            single,
            {
                self.open_one: 200,
                self.open_two: 200,
                self.forbidden: 403,
                self.missing: 404,
            },
        )
        self.assertEqual(
            {rid for rid, status in single.items() if status == 200}, set(summaries)
        )
        self.assertNotIn(self.forbidden, summaries)
        self.assertFalse(
            any(self.forbidden in call[1] for call in es.calls if call[0] == "mget")
        )
        self.assertNotIn(self.missing, summaries)

    def test_the_batch_loads_its_rows_once(self):
        ids = [self.open_one, self.open_two, self.forbidden]
        with CaptureQueriesContext(connection) as queries:
            self.batch_ids(ids)
        # django-silk, when a local settings file loads it, adds an EXPLAIN per
        # statement and one INSERT carrying every statement's text.
        loads = [
            q["sql"]
            for q in queries
            if q["sql"].startswith("SELECT") and 'FROM "resource_instances"' in q["sql"]
        ]
        self.assertEqual(len(loads), 1, "\n".join(loads))

    def test_each_loaded_row_is_handed_to_the_core_check(self):
        with mock.patch(
            "manuspectrum.views.summary.user_can_read_resource",
            wraps=permission_backend.user_can_read_resource,
        ) as check:
            self.batch_ids([self.open_one, self.missing])
        by_row = [
            c for c in check.call_args_list if c.kwargs.get("resource") is not None
        ]
        by_id = [
            c for c in check.call_args_list if c.kwargs.get("resourceid") is not None
        ]
        self.assertEqual(
            [str(c.kwargs["resource"].pk) for c in by_row], [self.open_one]
        )
        self.assertEqual([c.kwargs["resourceid"] for c in by_id], [self.missing])

    def test_an_id_asked_in_upper_case_meets_its_grant(self):
        summaries = self.batch_ids([self.forbidden.upper(), self.open_one])
        self.assertEqual(list(summaries), [self.open_one])


class NodegroupRestrictionCountTests(TestCase):
    def test_a_grant_on_a_nodegroup_counts_whatever_its_codename(self):
        reader = User.objects.create_user("nodegroup_reader", password="pw")
        nodegroup = NodeGroup.objects.create(nodegroupid=uuid.uuid4(), cardinality="n")
        baseline = _count_nodegroup_restrictions()
        assign_perm("write_nodegroup", reader, nodegroup)
        self.assertEqual(_count_nodegroup_restrictions(), baseline + 1)


class GraphSlugInvalidationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_a_publication_saved_drops_the_slug_map_once_committed(self):
        cache.set(SLUG_CACHE_KEY, {"document": "g-document"}, 3600)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            post_save.send(
                sender=GraphXPublishedGraph,
                instance=GraphXPublishedGraph(),
                created=True,
            )
            self.assertEqual(cache.get(SLUG_CACHE_KEY), {"document": "g-document"})
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        self.assertIsNone(cache.get(SLUG_CACHE_KEY))

    def test_a_publication_deleted_drops_the_slug_map(self):
        cache.set(SLUG_CACHE_KEY, {"document": "g-document"}, 3600)
        with self.captureOnCommitCallbacks(execute=True):
            post_delete.send(
                sender=GraphXPublishedGraph, instance=GraphXPublishedGraph()
            )
        self.assertIsNone(cache.get(SLUG_CACHE_KEY))

    def test_an_object_grant_written_drops_the_restriction_counts(self):
        cache.set(RESTRICTED_CACHE_KEY, 0, 60)
        cache.set(RESTRICTED_NODEGROUPS_CACHE_KEY, 0, 60)
        with self.captureOnCommitCallbacks(execute=True):
            post_save.send(
                sender=GroupObjectPermission,
                instance=GroupObjectPermission(),
                created=True,
            )
        self.assertIsNone(cache.get(RESTRICTED_CACHE_KEY))
        self.assertIsNone(cache.get(RESTRICTED_NODEGROUPS_CACHE_KEY))

    def test_another_model_saved_keeps_the_slug_map(self):
        cache.set(SLUG_CACHE_KEY, {"document": "g-document"}, 3600)
        post_save.send(sender=NodeGroup, instance=NodeGroup(), created=True)
        self.assertEqual(cache.get(SLUG_CACHE_KEY), {"document": "g-document"})
