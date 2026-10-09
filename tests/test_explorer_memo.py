"""Data version, corpus bundle memo and its invalidation.

Usage:
    python manage.py test tests.test_explorer_memo --settings="tests.test_settings"
"""

import json
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
from django.utils import translation
from guardian.models import GroupObjectPermission

from arches.app.models.models import (
    GraphXPublishedGraph,
    ResourceInstance,
    TileModel,
)

from manuspectrum.utils.data_version import data_version, prune_data_changes
from manuspectrum.utils.public_visibility import VisibleSet, forget_visibility
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

    def rename_by_sql(self, resource, name, language="en"):
        node = self.nodes[("analysis", "label_of_name")]
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tiles SET tiledata = jsonb_set(tiledata, %s, %s::jsonb) "
                "WHERE resourceinstanceid = %s AND nodegroupid = %s",
                [
                    [str(node.nodeid), language],
                    json.dumps({"value": name, "direction": "ltr"}),
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

    def test_a_prune_whose_mark_fails_deletes_nothing(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO ms_data_change (txid, at) "
                "VALUES (-1, now() - interval '8 days')"
            )
        before = data_version()

        with (
            mock.patch("manuspectrum.utils.data_version._MARK_SQL", "SELECT nope"),
            self.assertRaises(Exception),
        ):
            prune_data_changes(7)

        self.assertEqual(data_version(), before)


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


class BundleKeyTests(MemoCase):
    def test_readers_with_other_rights_never_share_a_bundle(self):
        self.embargo(self.documents["embargoed"])
        with mock.patch.object(
            explorer_service, "build_bundle", wraps=explorer_service.build_bundle
        ) as build:
            corpus_bundle(self.anonymous, "en")
            corpus_bundle(self.editor, "en")

        self.assertEqual(build.call_count, 2)
        readers = {call.args[0] for call in build.call_args_list}
        self.assertEqual(readers, {self.anonymous, self.editor})

    def test_readers_with_the_same_rights_share_one_bundle(self):
        self.embargo(self.documents["embargoed"])
        other = User.objects.create_user("explorer_editor_2", password="pw")
        other.groups.add(Group.objects.get(name="Resource Editor"))
        with mock.patch.object(
            explorer_service, "build_bundle", wraps=explorer_service.build_bundle
        ) as build:
            first = corpus_bundle(self.editor, "en")
            second = corpus_bundle(other, "en")

        self.assertEqual(build.call_count, 1)
        self.assertIs(second, first)

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
            results.append(explorer_memo.remember("k-par", "en", build))

        threads = [threading.Thread(target=call) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(builds), 1)
        self.assertEqual(len({id(r) for r in results}), 1)

    def test_a_process_keeps_at_most_its_local_entries(self):
        for n in range(explorer_memo.LOCAL_ENTRIES + 2):
            explorer_memo.remember(f"k-local-{n}", "en", lambda: {"n": 1})

        self.assertEqual(len(explorer_memo._local), explorer_memo.LOCAL_ENTRIES)
        self.assertNotIn("k-local-0", explorer_memo._local)

    def test_only_the_last_live_entries_of_a_language_stay_stored(self):
        keys = [f"k-live-{n}" for n in range(explorer_memo.LIVE_ENTRIES + 1)]
        for key in keys:
            explorer_memo.remember(key, "en", lambda: {"n": 1})
        explorer_memo.remember("k-other", "fr", lambda: {"n": 1})

        self.assertIsNone(cache.get(keys[0]))
        for key in keys[1:] + ["k-other"]:
            self.assertIsNotNone(cache.get(key))

    def test_concurrent_retirements_keep_every_new_key_live(self):
        real_live = explorer_memo._live

        def slow_live(language):
            found = real_live(language)
            time.sleep(0.2)
            return found

        with mock.patch.object(explorer_memo, "_live", slow_live):
            threads = [
                threading.Thread(
                    target=explorer_memo._retire_previous,
                    args=("en", f"k-race-{n}", "g", f"1.{n}"),
                )
                for n in (1, 2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(
            {key for key, _, _ in real_live("en")}, {"k-race-1", "k-race-2"}
        )

    def test_a_stored_bundle_is_compressed_and_round_trips(self):
        bundle = {"rows": ["same row"] * 500}
        explorer_memo.remember("k-packed", "en", lambda: bundle)
        explorer_memo.forget_local()

        stored = cache.get("k-packed")
        found = explorer_memo.remember(
            "k-packed", "en", mock.Mock(side_effect=AssertionError)
        )

        self.assertIsInstance(stored, bytes)
        self.assertLess(len(stored), len(pickle.dumps(bundle)))
        self.assertEqual(found, bundle)

    def test_a_build_that_returns_nothing_is_not_stored(self):
        found = explorer_memo.remember("k-none", "en", lambda: None)

        self.assertIsNone(found)
        self.assertFalse(cache.has_key("k-none"))

    def test_a_stored_bundle_is_read_without_building(self):
        cache.set("k-stored", explorer_memo.pack({"stored": True}))

        found = explorer_memo.remember(
            "k-stored", "en", mock.Mock(side_effect=AssertionError)
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

    def test_a_french_rebuild_run_under_another_language_keeps_french_labels(self):
        first = corpus_bundle(self.anonymous, "fr")
        self.rename_by_sql(self.analyses["open"], "X01 renommée", language="fr")

        stale = corpus_bundle(self.anonymous, "fr")
        with translation.override("en"):
            self.pending[0]()

        self.assertIs(stale, first)
        self.assertEqual(
            self.name_of(corpus_bundle(self.anonymous, "fr")), "X01 renommée"
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

        cache.delete(explorer_memo._rebuild_failed("en"))
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
                "reason",
                "background",
                "stale_served",
            )
        }
        self.assertEqual(
            {k: fields[k] for k in ("language", "reason", "background")},
            {
                "language": "en",
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
            (record.reason, record.background, record.stale_served),
            ("data", True, 2),
        )


REAL_SPAWN = explorer_memo.spawn


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
        return cache.get(explorer_memo._rebuild_lock("en"))

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
        cache.delete(explorer_memo._rebuild_lock("en"))
        explorer_memo._rebuilding.clear()

    def run_versions(self, versions):
        for version in versions:
            self.state["version"] = version
            self.bundle()
            while self.pending:
                self.pending.pop()()

    @override_settings(EXPLORER_REBUILD_MIN_INTERVAL=30)
    def test_data_versions_within_the_interval_run_one_rebuild(self):
        clock = [1000.0]
        with mock.patch.object(explorer_memo, "_clock", lambda: clock[0]):
            self.bundle()
            self.run_versions([f"1.{n}" for n in range(2, 12)])
            self.assertEqual(self.builds, ["1.1:g1", "1.2:g1"])
            self.assertEqual(self.bundle(), "1.2:g1")

            clock[0] += 29
            self.run_versions(["1.12"])
            self.assertEqual(self.builds, ["1.1:g1", "1.2:g1"])

            clock[0] += 2
            self.run_versions(["1.13"])
        self.assertEqual(self.builds, ["1.1:g1", "1.2:g1", "1.13:g1"])
        self.assertEqual(self.bundle(), "1.13:g1")

    @override_settings(EXPLORER_REBUILD_MIN_INTERVAL=30)
    def test_a_permission_change_inside_the_interval_builds_at_once(self):
        with mock.patch.object(explorer_memo, "_clock", lambda: 1000.0):
            self.bundle()
            self.run_versions(["1.2"])
            self.state["gates"] = "g2"
            self.state["version"] = "1.3"

            self.assertEqual(self.bundle(), "1.3:g2")
        self.assertEqual(self.builds, ["1.1:g1", "1.2:g1", "1.3:g2"])

    @override_settings(EXPLORER_REBUILD_MIN_INTERVAL=0)
    def test_no_interval_rebuilds_every_new_version(self):
        with mock.patch.object(explorer_memo, "_clock", lambda: 1000.0):
            self.bundle()
            self.run_versions(["1.2", "1.3", "1.4"])
        self.assertEqual(self.builds, ["1.1:g1", "1.2:g1", "1.3:g1", "1.4:g1"])

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

    def test_a_process_runs_one_background_rebuild_across_languages(self):
        def served(language):
            return explorer_memo.corpus_bundle(None, language, self.build).digest

        for language in ("en", "fr"):
            served(language)
        self.state["version"] = "1.2"
        answers = [served(language) for language in ("en", "fr")]
        self.assertEqual(len(self.pending), 1)

        self.pending.pop()()
        self.assertEqual(served("fr"), "1.1:g1")

        self.assertEqual(answers, ["1.1:g1"] * 2)
        self.assertEqual(len(self.pending), 1)

    def test_two_commits_sharing_a_last_sequence_answer_from_the_later_one(self):
        self.state["version"] = "6.11"
        self.bundle()
        self.state["version"] = "7.11"
        self.bundle()
        self.pending.pop()()
        self.state["version"] = "8.12"

        self.assertEqual(self.bundle(), "7.11:g1")

    @override_settings(EXPLORER_BACKGROUND_REBUILD=True)
    def test_a_rebuild_in_a_real_thread_builds_in_the_language_of_its_ticket(self):
        languages, threads, go = [], [], threading.Event()

        def build(user, language, visible):
            if threading.current_thread() is not threading.main_thread():
                go.wait(5)
            languages.append(translation.get_language())
            return FakeBundle(visible.digest, visible)

        def start(target):
            threads.append(REAL_SPAWN(target))

        explorer_memo.corpus_bundle(None, "fr", build)
        self.state["version"] = "1.2"
        with (
            mock.patch.object(explorer_memo, "spawn", start),
            translation.override("en"),
        ):
            served = explorer_memo.corpus_bundle(None, "fr", build).digest
            go.set()
            threads[0].join(5)

        self.assertEqual(served, "1.1:g1")
        self.assertFalse(threads[0].is_alive())
        self.assertEqual(languages[-1], "fr")
        self.assertEqual(
            explorer_memo.corpus_bundle(None, "fr", build).digest, "1.2:g1"
        )

    def test_a_rebuild_releases_only_the_lock_it_holds(self):
        self.bundle()
        self.state["version"] = "1.2"
        self.bundle()
        lock = explorer_memo._rebuild_lock("en")
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
        cache.delete(explorer_memo._rebuild_lock("en"))
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

    def test_a_previous_bundle_gone_before_it_is_read_builds_as_cold(self):
        self.bundle()
        self.state["version"] = "1.2"

        with mock.patch.object(explorer_memo, "_load", return_value=None):
            held = explorer_memo.ticket(None, "en", self.build)

        self.assertEqual((held.stale, held.reason), (False, "cold"))
        self.assertEqual(self.pending, [])

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
        cache.delete(explorer_memo._rebuild_lock("en"))
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

    def failing_cache(self, method, key):
        """``explorer_memo.cache`` with *method* raising for *key*, the rest untouched."""
        wrapped = mock.MagicMock(wraps=cache)
        real = getattr(cache, method)

        def call(name, *args, **kwargs):
            if name == key:
                raise ConnectionError("cache unreachable")
            return real(name, *args, **kwargs)

        getattr(wrapped, method).side_effect = call
        return mock.patch.object(explorer_memo, "cache", wrapped)

    def test_a_cache_error_releasing_the_lock_still_lets_the_next_rebuild_start(self):
        self.bundle()
        self.state["version"] = "1.2"
        self.bundle()
        lock = explorer_memo._rebuild_lock("en")

        with (
            self.failing_cache("get", lock),
            self.assertLogs("manuspectrum.explorer", "ERROR") as logs,
        ):
            self.pending.pop()()
        cache.delete(lock)
        self.state["version"] = "1.3"

        self.assertEqual(self.bundle(), "1.2:g1")
        self.assertEqual(len(self.pending), 1)
        self.assertEqual(len(logs.output), 1)

    def test_a_cache_error_recording_a_failed_rebuild_still_releases_it(self):
        self.bundle()
        self.state["version"] = "1.2"
        explorer_memo.ticket(None, "en", lambda *args: None)
        failed = explorer_memo._rebuild_failed("en")

        with (
            self.failing_cache("set", failed),
            self.assertLogs("manuspectrum.explorer", "ERROR") as logs,
        ):
            self.pending.pop()()

        self.assertIsNone(self.rebuild_lock())
        self.assertEqual(explorer_memo._rebuilding, set())
        self.assertEqual(len(logs.output), 1)

    def test_a_cache_error_before_a_rebuild_starts_frees_its_guard_and_lock(self):
        self.bundle()
        self.state["version"] = "1.2"
        held = explorer_memo.ticket(None, "en", self.build)
        self.pending.clear()
        cache.delete(explorer_memo._rebuild_lock("en"))
        explorer_memo._rebuilding.clear()

        with (
            self.failing_cache("has_key", held.current),
            self.assertLogs("manuspectrum.explorer", "ERROR"),
        ):
            explorer_memo._rebuild_in_background(held, None, self.build)

        self.assertEqual(self.pending, [])
        self.assertIsNone(self.rebuild_lock())
        self.assertEqual(explorer_memo._rebuilding, set())

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
