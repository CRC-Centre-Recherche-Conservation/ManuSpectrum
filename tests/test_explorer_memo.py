"""Data version, corpus bundle memo and its invalidation.

Usage:
    python manage.py test tests.test_explorer_memo --settings="tests.test_settings"
"""

import threading
import time
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase
from guardian.models import GroupObjectPermission

from arches.app.models.models import (
    GraphXPublishedGraph,
    ResourceInstance,
    TileModel,
    UserProfile,
)

from manuspectrum.utils.data_version import data_version, prune_data_changes
from manuspectrum.utils.public_visibility import explorer_scope
from manuspectrum.views import explorer_memo, explorer_service
from manuspectrum.views.explorer_service import (
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
        return {r["id"]: r["id"] in payload["kept"]["analyses"] for r in rows}

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

    def test_a_stored_bundle_is_read_without_building(self):
        cache.set("k-stored", {"stored": True})

        found = explorer_memo.remember(
            "k-stored", "public", "en", mock.Mock(side_effect=AssertionError)
        )

        self.assertEqual(found, {"stored": True})
