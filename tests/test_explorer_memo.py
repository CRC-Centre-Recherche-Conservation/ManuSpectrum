"""Data version, corpus bundle memo and its invalidation.

Usage:
    python manage.py test tests.test_explorer_memo --settings="tests.test_settings"
"""

import pickle
import threading
import time
from dataclasses import dataclass
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase, override_settings
from guardian.models import GroupObjectPermission

from arches.app.models.models import (
    GraphXPublishedGraph,
    ResourceInstance,
    TileModel,
    UserProfile,
)

from manuspectrum.utils.data_version import data_version, prune_data_changes
from manuspectrum.utils.public_visibility import (
    VisibleSet,
    explorer_scope,
    forget_visibility,
)
from manuspectrum.views.explorer import memo as explorer_memo
from manuspectrum.views.explorer import service as explorer_service
from manuspectrum.views.explorer.service import (
    analysis_payload,
    corpus_bundle,
    document_payload,
    match_payload,
    search_payload,
)
from manuspectrum.views.summary_service import graph_index_key
from tests.explorer_fixtures import DRAFT
from tests.test_explorer_service import XRF, ServiceCase

RAMAN = "http://vocab/raman"


class MemoCase(ServiceCase):
    def setUp(self):
        super().setUp()
        explorer_memo.forget_local()
        self.addCleanup(explorer_memo.forget_local)
        guards = mock.patch.object(explorer_memo, "_rebuilding", set())
        guards.start()
        self.addCleanup(guards.stop)

    def rename_by_sql(self, resource, name):
        node = self.nodes[("analysis", "label_of_name")]
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tiles SET tiledata = jsonb_set(tiledata, %s, %s::jsonb) "
                "WHERE resourceinstanceid = %s AND nodegroupid = %s",
                [
                    [str(node.nodeid), "en", "value"],
                    f'"{name}"',
                    str(resource.pk),
                    str(node.nodegroup_id),
                ],
            )

    def names_found(self, text=""):
        payload = search_payload(QueryDict(text), self.anonymous, "en")
        return {r["name"]["value"] for r in payload["results"]}


class DataVersionTests(MemoCase):
    def test_an_orm_tile_save_moves_the_data_version(self):
        before = data_version()
        self.tile(self.analyses["open"], "analysis_start_date", "2024-06-01")
        self.assertNotEqual(data_version(), before)

    def test_a_raw_sql_update_moves_the_data_version(self):
        before = data_version()
        self.rename_by_sql(self.analyses["open"], "X01 renamed")
        self.assertNotEqual(data_version(), before)

    def test_a_bulk_create_of_tiles_moves_the_data_version(self):
        node = self.nodes[("analysis", "analysis_start_date")]
        before = data_version()
        TileModel.objects.bulk_create(
            [
                TileModel(
                    resourceinstance=self.analyses[key],
                    nodegroup_id=node.nodegroup_id,
                    data={str(node.nodeid): "2020-01-01"},
                )
                for key in ("open", "on_document")
            ]
        )
        self.assertNotEqual(data_version(), before)

    def test_a_bulk_created_object_grant_moves_the_data_version(self):
        before = data_version()
        GroupObjectPermission.objects.bulk_create(
            [
                GroupObjectPermission(
                    permission=Permission.objects.filter(
                        codename="no_access_to_resourceinstance"
                    ).first(),
                    group=Group.objects.get(name="Resource Editor"),
                    content_type=ContentType.objects.get_for_model(ResourceInstance),
                    object_pk=str(self.documents["open"].pk),
                )
            ]
        )
        self.assertNotEqual(data_version(), before)

    def test_a_lifecycle_change_by_queryset_update_moves_the_data_version(self):
        before = data_version()
        ResourceInstance.objects.filter(pk=self.analyses["open"].pk).update(
            resource_instance_lifecycle_state_id=DRAFT
        )
        self.assertNotEqual(data_version(), before)

    def test_a_read_leaves_the_data_version_alone(self):
        before = data_version()
        search_payload(QueryDict(""), self.anonymous, "en")
        self.assertEqual(data_version(), before)

    def test_a_prune_deletes_old_rows_and_moves_the_data_version(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO ms_data_change (txid, at) "
                "VALUES (-1, now() - interval '8 days')"
            )
        before = data_version()

        self.assertEqual(prune_data_changes(7), 1)
        self.assertNotEqual(data_version(), before)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM ms_data_change WHERE txid = -1")
            self.assertEqual(cursor.fetchone()[0], 0)


class NextReadTests(MemoCase):
    def builds(self):
        return mock.patch.object(
            explorer_service,
            "build_bundle",
            wraps=explorer_service.build_bundle,
        )

    def test_the_bundle_is_built_once_until_the_data_changes(self):
        with self.builds() as build:
            self.names_found()
            document_payload(self.documents["open"].pk, self.anonymous, "en")
            self.assertEqual(build.call_count, 1)

            self.rename_by_sql(self.analyses["open"], "X01 renamed by SQL")
            found = self.names_found()

        self.assertEqual(build.call_count, 2)
        self.assertIn("X01 renamed by SQL", found)

    def test_a_draft_state_written_by_queryset_update_shows_at_the_next_read(self):
        search_payload(QueryDict(""), self.anonymous, "en")
        ResourceInstance.objects.filter(pk=self.analyses["open"].pk).update(
            resource_instance_lifecycle_state_id=DRAFT
        )

        payload = search_payload(QueryDict("grain=analyses"), self.anonymous, "en")

        opened = next(
            r for r in payload["results"] if r["id"] == str(self.analyses["open"].pk)
        )
        self.assertIs(opened["unpublished"], True)

    def test_the_process_memo_never_serves_after_the_data_version_moves(self):
        first = corpus_bundle(self.anonymous, "en")
        with (
            mock.patch.object(
                explorer_memo, "get_or_build", side_effect=AssertionError
            ),
            mock.patch.object(explorer_memo, "cache") as shared,
        ):
            shared.get.side_effect = AssertionError
            self.assertIs(corpus_bundle(self.anonymous, "en"), first)

        self.rename_by_sql(self.analyses["open"], "X01 after the memo")
        second = corpus_bundle(self.anonymous, "en")

        self.assertIsNot(second, first)
        self.assertEqual(
            second.by_id[str(self.analyses["open"].pk)]["name"]["value"],
            "X01 after the memo",
        )


class ScopeTests(MemoCase):
    def test_every_reader_is_on_the_public_scope_while_nothing_is_restricted(self):
        self.assertEqual(explorer_scope(self.anonymous), "public")
        self.assertEqual(explorer_scope(self.editor), "public")

    def test_a_restriction_puts_each_reader_on_its_own_scope(self):
        self.embargo(self.documents["embargoed"])

        self.assertEqual(explorer_scope(self.anonymous), "anonymous")
        self.assertEqual(explorer_scope(self.editor), str(self.editor.pk))

    def test_a_reader_without_a_profile_is_never_on_the_public_scope(self):
        reader = User.objects.create_user("explorer_no_profile", password="pw")
        UserProfile.objects.filter(user=reader).delete()
        reader = User.objects.get(pk=reader.pk)

        self.assertEqual(explorer_scope(reader), str(reader.pk))

    def test_restricted_readers_never_share_a_bundle(self):
        self.embargo(self.documents["embargoed"])
        with mock.patch.object(
            explorer_service, "build_bundle", wraps=explorer_service.build_bundle
        ) as build:
            corpus_bundle(self.anonymous, "en")
            corpus_bundle(self.editor, "en")

        self.assertEqual(build.call_count, 2)
        readers = {call.args[0] for call in build.call_args_list}
        self.assertEqual(readers, {self.anonymous, self.editor})

    def test_one_reader_has_one_bundle_per_language(self):
        english = corpus_bundle(self.anonymous, "en")
        french = corpus_bundle(self.anonymous, "fr")

        self.assertIsNot(english, french)


class UniverseTests(MemoCase):
    def setUp(self):
        super().setUp()
        self.tile(
            self.analyses["embargoed"],
            "analysis_technique_used",
            self.reference_value(RAMAN, "Raman"),
        )

    def matches(self, text):
        payload = match_payload(
            self.documents["open"].pk, QueryDict(text), self.anonymous, "en"
        )
        rows = corpus_bundle(self.anonymous, "en").by_document[
            str(self.documents["open"].pk)
        ]
        kept = payload["kept"]["analyses"]
        return {r["id"]: kept is None or r["id"] in kept for r in rows}

    def test_a_value_selected_elsewhere_in_the_corpus_drops_the_analyses_without_it(
        self,
    ):
        self.assertEqual(set(self.matches(f"technique={RAMAN}").values()), {False})

    def test_a_value_carried_nowhere_is_ignored(self):
        self.assertEqual(
            set(self.matches("technique=http://vocab/nowhere").values()), {True}
        )

    def test_a_value_of_the_document_keeps_its_analyses(self):
        found = self.matches(f"technique={XRF}")

        self.assertIs(found[str(self.analyses["open"].pk)], True)
        self.assertIs(found[str(self.analyses["on_document"].pk)], False)


class RepublicationTests(MemoCase):
    def test_a_republication_drops_the_memoised_graph_index(self):
        graph = self.graphs["analysis"]
        cache.set(graph_index_key(graph.pk), "stale")

        with self.captureOnCommitCallbacks(execute=True):
            GraphXPublishedGraph.objects.create(graph=graph)

        self.assertIsNone(cache.get(graph_index_key(graph.pk)))


class RememberTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        explorer_memo.forget_local()
        self.addCleanup(cache.clear)
        self.addCleanup(explorer_memo.forget_local)

    def test_parallel_callers_of_one_key_build_it_once(self):
        builds, results = [], []

        def build():
            builds.append(1)
            time.sleep(0.3)
            return {"bundle": len(builds)}

        def call():
            results.append(explorer_memo.remember("k-par", "public", "en", build))

        threads = [threading.Thread(target=call) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(builds), 1)
        self.assertEqual(len({id(r) for r in results}), 1)

    def test_a_process_keeps_at_most_its_local_entries(self):
        for n in range(explorer_memo.LOCAL_ENTRIES + 2):
            explorer_memo.remember(f"k-local-{n}", f"s{n}", "en", lambda: {"n": 1})

        self.assertEqual(len(explorer_memo._local), explorer_memo.LOCAL_ENTRIES)
        self.assertNotIn("k-local-0", explorer_memo._local)

    def test_only_the_last_live_entries_of_a_scope_stay_stored(self):
        keys = [f"k-live-{n}" for n in range(explorer_memo.LIVE_ENTRIES + 1)]
        for key in keys:
            explorer_memo.remember(key, "public", "en", lambda: {"n": 1})
        explorer_memo.remember("k-other", "public", "fr", lambda: {"n": 1})

        self.assertIsNone(cache.get(keys[0]))
        for key in keys[1:] + ["k-other"]:
            self.assertIsNotNone(cache.get(key))

    def test_a_stored_bundle_is_compressed_and_round_trips(self):
        bundle = {"rows": ["same row"] * 500}
        explorer_memo.remember("k-packed", "public", "en", lambda: bundle)
        explorer_memo.forget_local()

        stored = cache.get("k-packed")
        found = explorer_memo.remember(
            "k-packed", "public", "en", mock.Mock(side_effect=AssertionError)
        )

        self.assertIsInstance(stored, bytes)
        self.assertLess(len(stored), len(pickle.dumps(bundle)))
        self.assertEqual(found, bundle)

    def test_a_build_that_returns_nothing_is_not_stored(self):
        found = explorer_memo.remember("k-none", "public", "en", lambda: None)

        self.assertIsNone(found)
        self.assertFalse(cache.has_key("k-none"))

    def test_a_stored_bundle_is_read_without_building(self):
        cache.set("k-stored", explorer_memo.pack({"stored": True}))

        found = explorer_memo.remember(
            "k-stored", "public", "en", mock.Mock(side_effect=AssertionError)
        )

        self.assertEqual(found, {"stored": True})


class StaleWhileRebuildTests(MemoCase):
    def setUp(self):
        super().setUp()
        self.pending = []
        spawn = mock.patch.object(explorer_memo, "spawn", self.pending.append)
        spawn.start()
        self.addCleanup(spawn.stop)

    def builds(self, **kwargs):
        return mock.patch.object(
            explorer_service,
            "build_bundle",
            **(kwargs or {"wraps": explorer_service.build_bundle}),
        )

    def name_of(self, bundle):
        return bundle.by_id[str(self.analyses["open"].pk)]["name"]["value"]

    def test_a_data_change_answers_from_the_previous_bundle_while_one_rebuild_runs(
        self,
    ):
        first = corpus_bundle(self.anonymous, "en")
        self.rename_by_sql(self.analyses["open"], "X01 renamed meanwhile")

        with self.builds() as build:
            served = [corpus_bundle(self.anonymous, "en") for _ in range(3)]
            self.assertEqual(build.call_count, 0)
            self.assertEqual(len(self.pending), 1)
            self.pending[0]()

        self.assertEqual(build.call_count, 1)
        self.assertTrue(all(bundle is first for bundle in served))
        self.assertEqual(
            self.name_of(corpus_bundle(self.anonymous, "en")), "X01 renamed meanwhile"
        )

    def test_the_rebuilt_bundle_is_read_from_the_cache_by_another_process(self):
        corpus_bundle(self.anonymous, "en")
        self.rename_by_sql(self.analyses["open"], "X01 in another process")
        corpus_bundle(self.anonymous, "en")
        self.pending[0]()
        explorer_memo.forget_local()

        with self.builds(side_effect=AssertionError):
            found = corpus_bundle(self.anonymous, "en")

        self.assertEqual(self.name_of(found), "X01 in another process")

    def test_a_lifecycle_change_answers_from_the_previous_bundle(self):
        first = corpus_bundle(self.anonymous, "en")
        ResourceInstance.objects.filter(pk=self.analyses["open"].pk).update(
            resource_instance_lifecycle_state_id=DRAFT
        )

        self.assertIs(corpus_bundle(self.anonymous, "en"), first)
        self.assertEqual(len(self.pending), 1)

    def test_a_new_permission_epoch_builds_in_the_request(self):
        first = corpus_bundle(self.anonymous, "en")
        forget_visibility()

        with self.builds() as build:
            second = corpus_bundle(self.anonymous, "en")

        self.assertEqual(build.call_count, 1)
        self.assertEqual(self.pending, [])
        self.assertIsNot(second, first)

    def test_an_embargo_builds_in_the_request(self):
        corpus_bundle(self.anonymous, "en")
        self.embargo(self.documents["open"])

        with self.builds() as build:
            bundle = corpus_bundle(self.anonymous, "en")

        self.assertEqual(build.call_count, 1)
        self.assertEqual(self.pending, [])
        self.assertNotIn(str(self.documents["open"].pk), bundle.visible.documents)

    def test_an_analysis_linked_under_a_hidden_project_is_never_served_stale(self):
        self.embargo(self.projects["side"])
        first = corpus_bundle(self.anonymous, "en")
        analysis = str(self.analyses["open"].pk)
        self.tile(
            self.analyses["open"],
            "analysis_by_project",
            self.refs(self.projects["side"]),
        )

        with self.builds() as build:
            bundle = corpus_bundle(self.anonymous, "en")
            payload = analysis_payload(analysis, self.anonymous, "en")

        self.assertIn(analysis, first.visible.analyses)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(self.pending, [])
        self.assertNotIn(analysis, bundle.visible.analyses)
        self.assertIsNone(payload)

    def test_a_deleted_analysis_is_never_served_stale(self):
        first = corpus_bundle(self.anonymous, "en")
        gone = str(self.analyses["on_document"].pk)
        ResourceInstance.objects.filter(pk=gone).delete()

        with self.builds() as build:
            bundle = corpus_bundle(self.anonymous, "en")

        self.assertIn(gone, first.visible.analyses)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(self.pending, [])
        self.assertNotIn(gone, bundle.visible.analyses)

    def test_a_stale_answer_drops_the_reference_to_a_deleted_operator(self):
        first = corpus_bundle(self.anonymous, "en")
        analysis = str(self.analyses["open"].pk)
        ResourceInstance.objects.filter(pk=self.operator.pk).delete()

        payload = analysis_payload(analysis, self.anonymous, "en")

        self.assertIs(corpus_bundle(self.anonymous, "en"), first)
        self.assertEqual(len(self.pending), 1)
        self.assertEqual(payload["operators"], [])
        self.assertEqual(payload["id"], analysis)

    def test_a_group_change_builds_in_the_request(self):
        corpus_bundle(self.editor, "en")
        with self.captureOnCommitCallbacks(execute=True):
            self.editor.groups.add(Group.objects.get(name="Resource Reviewer"))

        with self.builds() as build:
            corpus_bundle(self.editor, "en")

        self.assertEqual(build.call_count, 1)
        self.assertEqual(self.pending, [])

    def test_without_a_previous_bundle_the_request_builds(self):
        with self.builds() as build:
            corpus_bundle(self.anonymous, "en")

        self.assertEqual(build.call_count, 1)
        self.assertEqual(self.pending, [])

    def test_a_failing_rebuild_is_logged_once_and_retried_after_its_delay(self):
        first = corpus_bundle(self.anonymous, "en")
        self.rename_by_sql(self.analyses["open"], "X01 after a failure")

        with (
            self.builds(side_effect=RuntimeError("boom")),
            self.assertLogs("manuspectrum.explorer", "ERROR") as logs,
        ):
            self.assertIs(corpus_bundle(self.anonymous, "en"), first)
            self.pending.pop()()
            served = [corpus_bundle(self.anonymous, "en") for _ in range(3)]

        self.assertTrue(all(bundle is first for bundle in served))
        self.assertEqual(self.pending, [])
        self.assertEqual(len(logs.records), 1)
        self.assertIn("rebuild failed", logs.output[0])

        cache.delete(
            explorer_memo._rebuild_failed(explorer_scope(self.anonymous), "en")
        )
        self.assertIs(corpus_bundle(self.anonymous, "en"), first)
        self.pending.pop()()
        self.assertEqual(
            self.name_of(corpus_bundle(self.anonymous, "en")), "X01 after a failure"
        )

    @override_settings(EXPLORER_REBUILD_RETRY_AFTER=0)
    def test_without_a_retry_delay_the_next_request_retries_a_failed_rebuild(self):
        first = corpus_bundle(self.anonymous, "en")
        self.rename_by_sql(self.analyses["open"], "X01 retried at once")

        with (
            self.builds(side_effect=RuntimeError("boom")),
            self.assertLogs("manuspectrum.explorer", "ERROR"),
        ):
            corpus_bundle(self.anonymous, "en")
            self.pending.pop()()
        self.assertIs(corpus_bundle(self.anonymous, "en"), first)

        self.assertEqual(len(self.pending), 1)

    def test_the_etag_of_a_stale_answer_names_the_bundle_served(self):
        before = self.client.get("/en/api/explorer/search")
        self.rename_by_sql(self.analyses["open"], "X01 behind the etag")

        stale = self.client.get("/en/api/explorer/search")
        revalidated = self.client.get(
            "/en/api/explorer/search", HTTP_IF_NONE_MATCH=before["ETag"]
        )
        self.pending[0]()
        fresh = self.client.get("/en/api/explorer/search")

        self.assertEqual(stale["ETag"], before["ETag"])
        self.assertEqual(stale.content, before.content)
        self.assertEqual(stale["Cache-Control"], before["Cache-Control"])
        self.assertEqual(revalidated.status_code, 304)
        self.assertNotEqual(fresh["ETag"], before["ETag"])
        self.assertIn(b"X01 behind the etag", fresh.content)

    def test_the_build_log_carries_its_fields_and_no_user_id(self):
        self.embargo(self.documents["embargoed"])
        with self.assertLogs("manuspectrum.explorer", "INFO") as logs:
            corpus_bundle(self.editor, "en")

        record = logs.records[0]
        fields = {
            name: getattr(record, name)
            for name in (
                "duration_s",
                "rows",
                "stored_bytes",
                "language",
                "scope_kind",
                "reason",
                "background",
                "stale_served",
            )
        }
        self.assertEqual(
            {k: fields[k] for k in ("language", "scope_kind", "reason", "background")},
            {
                "language": "en",
                "scope_kind": "reader",
                "reason": "cold",
                "background": False,
            },
        )
        self.assertGreater(fields["rows"], 0)
        self.assertGreater(fields["stored_bytes"], 0)
        self.assertNotIn(self.editor.username, record.getMessage())
        self.assertNotIn(self.editor.pk, fields.values())
        self.assertFalse(hasattr(record, "user"))

    def test_a_background_build_logs_the_stale_answers_it_covered(self):
        corpus_bundle(self.anonymous, "en")
        self.rename_by_sql(self.analyses["open"], "X01 counted")
        corpus_bundle(self.anonymous, "en")
        corpus_bundle(self.anonymous, "en")

        with self.assertLogs("manuspectrum.explorer", "INFO") as logs:
            self.pending[0]()

        record = logs.records[-1]
        self.assertEqual(
            (record.reason, record.background, record.stale_served, record.scope_kind),
            ("data", True, 2, "public"),
        )


@dataclass(frozen=True)
class FakeBundle:
    digest: str
    visible: VisibleSet = VisibleSet()


class TicketGatesTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        explorer_memo.forget_local()
        self.addCleanup(cache.clear)
        self.addCleanup(explorer_memo.forget_local)
        self.pending = []
        guards = mock.patch.object(explorer_memo, "_rebuilding", set())
        guards.start()
        self.addCleanup(guards.stop)
        self.state = {
            "version": "1.1",
            "gates": "g1",
            "epoch": "e1",
            "analyses": {"a1", "a2"},
        }
        for name, fake in (
            ("spawn", self.pending.append),
            ("data_version", lambda: self.state["version"]),
            ("permission_epoch", lambda: self.state["epoch"]),
            ("explorer_scope", lambda user: "public"),
            (
                "visible_set",
                lambda user, version: VisibleSet(
                    analyses=frozenset(self.state["analyses"]),
                    digest=f"{version}:{self.state['gates']}",
                    gates=self.state["gates"],
                ),
            ),
        ):
            patcher = mock.patch.object(explorer_memo, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.builds = []

    def build(self, user, language, visible):
        self.builds.append(visible.digest)
        return FakeBundle(visible.digest, visible)

    def bundle(self):
        return explorer_memo.corpus_bundle(None, "en", self.build).digest

    def rebuild_lock(self):
        return cache.get(explorer_memo._rebuild_lock("public", "en"))

    def test_data_versions_in_a_row_run_one_rebuild_at_a_time(self):
        self.bundle()
        for version in ("1.2", "1.3", "1.4", "1.5"):
            self.state["version"] = version
            self.assertEqual(self.bundle(), "1.1:g1")
        self.assertEqual(len(self.pending), 1)

        self.pending.pop()()
        self.assertEqual(self.bundle(), "1.2:g1")
        self.assertEqual(len(self.pending), 1)
        self.pending.pop()()

        self.assertEqual(self.bundle(), "1.5:g1")
        self.assertEqual(self.builds, ["1.1:g1", "1.2:g1", "1.5:g1"])

    def release_rebuild(self):
        cache.delete(explorer_memo._rebuild_lock("public", "en"))
        explorer_memo._rebuilding.clear()

    def test_rebuilds_ending_out_of_order_never_answer_older_data(self):
        self.bundle()
        self.state["version"] = "1.2"
        self.bundle()
        self.release_rebuild()
        self.state["version"] = "1.3"
        self.bundle()
        older, newer = self.pending

        newer()
        older()
        self.state["version"] = "1.4"

        self.assertEqual(self.bundle(), "1.3:g1")

    def test_a_rebuild_releases_only_the_lock_it_holds(self):
        self.bundle()
        self.state["version"] = "1.2"
        self.bundle()
        lock = explorer_memo._rebuild_lock("public", "en")
        cache.set(lock, "another owner")

        self.pending.pop()()

        self.assertEqual(cache.get(lock), "another owner")

    def test_a_rebuild_running_in_another_process_starts_none_here(self):
        self.bundle()
        self.state["version"] = "1.2"
        self.bundle()
        explorer_memo._rebuilding.clear()
        self.state["version"] = "1.3"

        self.assertEqual(self.bundle(), "1.1:g1")
        self.assertEqual(len(self.pending), 1)

    def test_a_rebuild_running_in_this_process_starts_none_after_its_lock_expired(
        self,
    ):
        self.bundle()
        self.state["version"] = "1.2"
        self.bundle()
        cache.delete(explorer_memo._rebuild_lock("public", "en"))
        self.state["version"] = "1.3"

        self.assertEqual(self.bundle(), "1.1:g1")
        self.assertEqual(len(self.pending), 1)

    def test_new_hidden_resources_with_the_same_data_build_in_the_request(self):
        self.bundle()
        self.state["gates"] = "g2"

        self.assertEqual(self.bundle(), "1.1:g2")
        self.assertEqual(self.pending, [])

    def test_new_hidden_resources_and_new_data_build_in_the_request(self):
        self.bundle()
        self.state.update(version="1.2", gates="g2")

        self.assertEqual(self.bundle(), "1.2:g2")
        self.assertEqual(self.pending, [])

    def test_new_data_under_the_same_gates_answers_from_the_previous_bundle(self):
        self.bundle()
        self.state["version"] = "1.2"

        self.assertEqual(self.bundle(), "1.1:g1")
        self.assertEqual(len(self.pending), 1)

    def test_new_data_hiding_a_resource_the_previous_bundle_shows_builds_in_the_request(
        self,
    ):
        self.bundle()
        self.state.update(version="1.2", analyses={"a1"})
        held = explorer_memo.ticket(None, "en", self.build)

        self.assertEqual(self.bundle(), "1.2:g1")
        self.assertEqual((held.stale, held.reason), (False, "visibility"))
        self.assertEqual(self.pending, [])

    def test_new_data_adding_a_resource_answers_from_the_previous_bundle(self):
        self.bundle()
        self.state.update(version="1.2", analyses={"a1", "a2", "a3"})

        self.assertEqual(self.bundle(), "1.1:g1")
        self.assertEqual(len(self.pending), 1)

    def test_a_previous_bundle_gone_from_the_cache_is_rebuilt_in_the_request(self):
        self.bundle()
        self.state["version"] = "1.2"
        held = explorer_memo.ticket(None, "en", self.build)
        explorer_memo.forget_local()
        cache.delete(held.key)

        found = explorer_memo.corpus_bundle(None, "en", self.build, held=held)

        self.assertEqual(found.digest, "1.2:g1")

    def test_a_previous_bundle_held_by_the_cache_only_is_loaded_from_it(self):
        self.bundle()
        explorer_memo.forget_local()
        self.state["version"] = "1.2"

        self.assertEqual(self.bundle(), "1.1:g1")
        self.assertEqual(self.builds, ["1.1:g1"])

    def test_a_rebuild_that_cannot_start_releases_its_lock_and_is_logged(self):
        self.bundle()
        self.state["version"] = "1.2"

        with (
            mock.patch.object(
                explorer_memo, "spawn", side_effect=RuntimeError("no thread")
            ),
            self.assertLogs("manuspectrum.explorer", "ERROR") as logs,
        ):
            held = explorer_memo.ticket(None, "en", self.build)

        self.assertTrue(held.stale)
        self.assertIsNone(self.rebuild_lock())
        self.assertIn("could not start", logs.output[0])

    def test_a_rebuild_whose_bundle_is_already_stored_does_not_start(self):
        self.bundle()
        self.state["version"] = "1.2"
        held = explorer_memo.ticket(None, "en", self.build)
        self.pending.clear()
        cache.delete(explorer_memo._rebuild_lock("public", "en"))
        explorer_memo._rebuilding.clear()
        cache.set(held.current, explorer_memo.pack(FakeBundle("elsewhere")))

        explorer_memo._rebuild_in_background(held, None, self.build)

        self.assertEqual(self.pending, [])
        self.assertIsNone(self.rebuild_lock())

    def test_a_rebuild_that_returns_nothing_stores_nothing_and_warns(self):
        self.bundle()
        self.state["version"] = "1.2"
        held = explorer_memo.ticket(None, "en", lambda *args: None)

        with self.assertLogs("manuspectrum.explorer", "WARNING") as logs:
            self.pending[0]()

        self.assertIn("returned nothing", logs.output[0])
        self.assertFalse(cache.has_key(held.current))
        self.assertIsNone(self.rebuild_lock())

    def test_a_synchronous_rebuild_answers_from_the_new_bundle(self):
        self.bundle()
        self.state["version"] = "1.2"

        with mock.patch.object(explorer_memo, "spawn", lambda target: target()):
            self.assertEqual(self.bundle(), "1.2:g1")
        self.assertEqual(self.builds, ["1.1:g1", "1.2:g1"])

    def test_one_caller_holding_the_build_lock_leaves_the_others_on_the_previous_bundle(
        self,
    ):
        self.bundle()
        self.state["version"] = "1.2"
        explorer_memo.ticket(None, "en", self.build)
        self.pending.clear()
        held = explorer_memo.ticket(None, "en", self.build)

        self.assertTrue(self.rebuild_lock())
        self.assertTrue(held.stale)
        self.assertEqual(self.pending, [])


class SpawnTests(SimpleTestCase):
    @override_settings(EXPLORER_BACKGROUND_REBUILD=True)
    def test_a_background_rebuild_runs_in_a_daemon_thread_that_closes_its_connections(
        self,
    ):
        ran = []
        with mock.patch.object(explorer_memo, "connections") as connections:
            thread = explorer_memo.spawn(lambda: ran.append(threading.current_thread()))
            thread.join(5)

        self.assertIs(ran[0], thread)
        self.assertTrue(thread.daemon)
        connections.close_all.assert_called_once_with()

    @override_settings(EXPLORER_BACKGROUND_REBUILD=False)
    def test_without_background_rebuilds_the_target_runs_in_the_caller(self):
        ran = []

        self.assertIsNone(explorer_memo.spawn(lambda: ran.append(1)))
        self.assertEqual(ran, [1])
