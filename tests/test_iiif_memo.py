"""``iiif.memo``: the visitor's view is memoised and revalidated; no other reader's ever is.

Usage:
    python manage.py test tests.test_iiif_memo --settings=tests.test_settings
"""

import time
import uuid
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from arches.app.models.models import TileModel

from tests.explorer_fixtures import FEATURES, IIIFCase


def memo_keys():
    return [k for k in cache._cache if ":iiif:" in k and not k.endswith(":lock")]


def app_queries(context):
    """The queries of *context* the application ran (Silk's own left out)."""
    return len(
        [
            q
            for q in context.captured_queries
            if "silk_" not in q["sql"] and "SAVEPOINT" not in q["sql"]
        ]
    )


class MemoTests(IIIFCase):
    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.reader = Client()
        self.reader.force_login(self.editor)
        self.url = f"/iiif/v3/annotation-collection/{self.documents['open'].pk}/page-1"

    def test_a_privileged_build_never_serves_a_visitor(self):
        file_id = self.stored_file(self.analyses["open"], "X01.csv", b"x,y\n1,2\n")
        self.restrict_nodegroup(
            self.nodes[("analysis", "measurement_point_data")].nodegroup_id, self.editor
        )

        granted = self.reader.get(self.url)
        visitor = self.visitor.get(self.url)
        granted_again = self.reader.get(self.url)

        self.assertIn(file_id, granted.content.decode())
        self.assertEqual(granted["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", granted)
        self.assertNotIn(file_id, visitor.content.decode())
        self.assertEqual(visitor["Cache-Control"], "public, no-cache")
        self.assertIn(file_id, granted_again.content.decode())
        self.assertEqual(len(memo_keys()), 1)

    def test_a_reader_who_sees_what_the_visitor_sees_shares_the_memo(self):
        visitor = self.visitor.get(self.url)
        reader = self.reader.get(self.url)

        self.assertEqual(reader["Cache-Control"], "public, no-cache")
        self.assertEqual(reader["ETag"], visitor["ETag"])
        self.assertEqual(len(memo_keys()), 1)

    def test_the_etag_answers_304_before_building(self):
        first = self.visitor.get(self.url)

        with mock.patch(
            "manuspectrum.iiif.facts.document_facts",
            side_effect=AssertionError("built"),
        ):
            again = self.visitor.get(self.url, HTTP_IF_NONE_MATCH=first["ETag"])

        self.assertEqual(again.status_code, 304)
        self.assertEqual(again["ETag"], first["ETag"])

    def test_a_memo_hit_builds_nothing(self):
        first = self.visitor.get(self.url)

        with mock.patch(
            "manuspectrum.iiif.facts.document_facts",
            side_effect=AssertionError("built"),
        ):
            again = self.visitor.get(self.url)

        self.assertEqual(again.content, first.content)

    def test_a_data_change_moves_the_key(self):
        first = self.visitor.get(self.url)
        self.tile(self.analyses["open"], "bibliographic_title", self.string_value("B"))

        again = self.visitor.get(self.url)

        self.assertNotEqual(again["ETag"], first["ETag"])

    def test_a_permission_change_moves_the_key(self):
        first = self.visitor.get(self.url)
        self.embargo(self.samples["s1"])

        again = self.visitor.get(self.url)

        self.assertNotEqual(again["ETag"], first["ETag"])

    def test_the_key_has_no_language(self):
        english = self.visitor.get(self.url, HTTP_ACCEPT_LANGUAGE="en")
        french = self.visitor.get(self.url, HTTP_ACCEPT_LANGUAGE="fr")

        self.assertEqual(english["ETag"], french["ETag"])
        self.assertEqual(english.content, french.content)
        self.assertEqual(len(memo_keys()), 1)
        self.assertNotIn("accept-language", english.get("Vary", "").lower())

    def test_a_recompiled_catalogue_moves_the_key(self):
        with mock.patch("manuspectrum.iiif.memo.locale_stamp", return_value="a"):
            first = self.visitor.get(self.url)
        with mock.patch("manuspectrum.iiif.memo.locale_stamp", return_value="b"):
            again = self.visitor.get(self.url, HTTP_IF_NONE_MATCH=first["ETag"])

        self.assertEqual(again.status_code, 200)
        self.assertNotEqual(again["ETag"], first["ETag"])

    def test_a_new_code_version_moves_the_key(self):
        with self.settings(CACHE_CODE_VERSION="a"):
            first = self.visitor.get(self.url)
        with self.settings(CACHE_CODE_VERSION="b"):
            again = self.visitor.get(self.url)

        self.assertNotEqual(again["ETag"], first["ETag"])

    def only(self, *names, n=1):
        named = ",".join(
            str(self.analyses[name].pk) if name in self.analyses else name
            for name in names
        )
        return f"{self.url[: -len('page-1')]}page-{n}?only={named}"

    def test_a_filtered_page_stores_nothing_of_its_own(self):
        self.visitor.get(self.url)

        one = self.visitor.get(self.only("open"))
        two = self.visitor.get(self.only("open", "on_document"))

        self.assertEqual((one.status_code, two.status_code), (200, 200))
        self.assertEqual(len(memo_keys()), 1)

    def test_a_filtered_page_is_served_from_the_canonical_page(self):
        self.visitor.get(self.url)

        with mock.patch(
            "manuspectrum.iiif.facts.document_facts",
            side_effect=AssertionError("built"),
        ):
            filtered = self.visitor.get(self.only("open"))

        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(
            [a["id"].split("/")[-2] for a in filtered.json()["items"]],
            [str(self.analyses["open"].pk)],
        )

    def test_a_warm_filtered_page_costs_the_queries_of_the_warm_canonical_page(self):
        self.visitor.get(self.url)
        self.visitor.get(self.only("open"))

        with CaptureQueriesContext(connection) as canonical:
            self.visitor.get(self.url)
        with CaptureQueriesContext(connection) as filtered:
            self.visitor.get(self.only("open"))

        self.assertLessEqual(app_queries(filtered), app_queries(canonical))

    def test_only_is_intersected_with_the_analyses_of_the_page(self):
        first = self.visitor.get(self.only("open"))
        again = self.visitor.get(self.only("open", "on_document", n=3))
        elsewhere = self.visitor.get(self.only("open", n=3))

        self.assertEqual(
            again.json()["id"].split("?only=")[1], str(self.analyses["on_document"].pk)
        )
        self.assertNotEqual(again["ETag"], first["ETag"])
        self.assertEqual(elsewhere.status_code, 404)
        self.assertEqual(elsewhere.content, b"")

    def test_ids_outside_the_page_share_the_etag_of_the_ids_on_it(self):
        first = self.visitor.get(self.only("open"))
        again = self.visitor.get(self.only("open", str(uuid.uuid4())))
        other_page = self.visitor.get(self.only("open", "on_document"))

        self.assertEqual(again["ETag"], first["ETag"])
        self.assertEqual(again.content, first.content)
        self.assertNotEqual(other_page["ETag"], first["ETag"])

    def test_a_filtered_etag_differs_from_the_canonical_etag_and_answers_304(self):
        canonical = self.visitor.get(self.url)
        filtered = self.visitor.get(self.only("open"))
        again = self.visitor.get(self.only("open"), HTTP_IF_NONE_MATCH=filtered["ETag"])
        star = self.visitor.get(self.only("open"), HTTP_IF_NONE_MATCH="*")

        self.assertNotEqual(filtered["ETag"], canonical["ETag"])
        self.assertRegex(filtered["ETag"], r'^"[0-9a-f]{40}"$')
        self.assertEqual((again.status_code, star.status_code), (304, 304))
        self.assertEqual(again["ETag"], filtered["ETag"])

    def test_only_naming_nothing_of_the_page_is_a_404_stored_nowhere(self):
        response = self.visitor.get(self.only(str(uuid.uuid4())))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_a_filtered_page_drops_an_analysis_hidden_from_the_reader(self):
        self.embargo(self.analyses["open"])

        both = self.visitor.get(self.only("open", "on_document"))
        hidden = self.visitor.get(self.only("open"))

        self.assertEqual(
            [a["id"].split("/")[-2] for a in both.json()["items"]],
            [str(self.analyses["on_document"].pk)],
        )
        self.assertEqual(hidden.status_code, 404)

    def test_a_private_reader_gets_a_private_filtered_page_stored_nowhere(self):
        file_id = self.stored_file(self.analyses["open"], "X01.csv", b"x,y\n1,2\n")
        self.restrict_nodegroup(
            self.nodes[("analysis", "measurement_point_data")].nodegroup_id, self.editor
        )

        granted = self.reader.get(self.only("open"))

        self.assertEqual(granted.status_code, 200)
        self.assertIn(file_id, granted.content.decode())
        self.assertEqual(granted["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", granted)
        self.assertEqual(memo_keys(), [])

    def test_a_v2_filtered_page_lists_the_kept_analyses(self):
        analysis = str(self.analyses["open"].pk)
        url = self.only("open").replace("/iiif/v3/", "/iiif/v2/")
        v3 = self.visitor.get(self.only("open"))

        page = self.visitor.get(url)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(
            [a["@id"].split("/")[-2] for a in page.json()["resources"]], [analysis]
        )
        self.assertTrue(page.json()["@id"].endswith(f"page-1?only={analysis}"))
        self.assertNotEqual(page["ETag"], v3["ETag"])

    def test_if_none_match_star_on_a_missing_page_is_a_404(self):
        doc = self.documents["open"].pk
        response = self.visitor.get(
            f"/iiif/v3/annotation-collection/{doc}/page-9999", HTTP_IF_NONE_MATCH="*"
        )

        self.assertEqual(response.status_code, 404)

    def test_if_none_match_star_on_a_missing_zone_is_a_404(self):
        response = self.visitor.get(
            f"/iiif/v3/annotation/{self.analyses['open'].pk}/{uuid.uuid4()}",
            HTTP_IF_NONE_MATCH="*",
        )

        self.assertEqual(response.status_code, 404)

    def test_if_none_match_star_on_an_existing_page_is_a_304(self):
        response = self.visitor.get(self.url, HTTP_IF_NONE_MATCH="*")

        self.assertEqual(response.status_code, 304)

    def test_a_missing_zone_is_built_once(self):
        url = f"/iiif/v3/annotation/{self.analyses['open'].pk}/{uuid.uuid4()}"
        first = self.visitor.get(url)

        with mock.patch(
            "manuspectrum.iiif.facts.annotated_fact",
            side_effect=AssertionError("built"),
        ):
            again = self.visitor.get(url)

        self.assertEqual(first.status_code, 404)
        self.assertEqual(again.status_code, 404)
        self.assertEqual(again.content, b"")

    def remaining(self, key):
        return cache._expire_info[key] - time.time()

    def test_an_unreadable_source_manifest_is_kept_for_the_degraded_lifetime(self):
        self.fetch.side_effect = lambda url: None
        collection = f"/iiif/v3/annotation-collection/{self.documents['open'].pk}"

        built = self.visitor.get(collection)
        (collection_key,) = memo_keys()
        page = self.visitor.get(self.url)
        (page_key,) = set(memo_keys()) - {collection_key}

        for key in (collection_key, page_key):
            self.assertLessEqual(self.remaining(key), settings.IIIF_DEGRADED_TTL)
            self.assertGreater(self.remaining(key), settings.IIIF_DEGRADED_TTL - 5)
        self.assertEqual(built.status_code, 200)
        self.assertNotIn("ETag", built)
        self.assertEqual(page.status_code, 404)

    def test_a_local_manifest_missing_from_the_database_is_degraded(self):
        node = self.nodes[("document", "facsimiles")]
        TileModel.objects.filter(
            resourceinstance=self.documents["open"], nodegroup_id=node.nodegroup_id
        ).update(data={str(node.nodeid): f"/manifest/{uuid.uuid4()}"})

        built = self.visitor.get(
            f"/iiif/v3/annotation-collection/{self.documents['open'].pk}"
        )

        (key,) = memo_keys()
        self.assertEqual(built.status_code, 200)
        self.assertLessEqual(self.remaining(key), settings.IIIF_DEGRADED_TTL)

    def test_a_readable_source_manifest_is_kept_for_the_memo_lifetime(self):
        self.visitor.get(f"/iiif/v3/annotation-collection/{self.documents['open'].pk}")

        (key,) = memo_keys()
        self.assertGreater(self.remaining(key), settings.IIIF_DEGRADED_TTL)

    def test_a_iiif_request_reads_the_data_version_once(self):
        file_id = self.stored_file(self.analyses["open"], "X01.csv", b"x,y\n1,2\n")
        document = self.documents["open"].pk
        analysis = self.analyses["open"].pk
        urls = [
            self.url,
            self.url,
            self.only("open"),
            f"/iiif/v3/annotation-collection/{document}",
            f"/iiif/v3/annotation/{analysis}",
            f"/iiif/v3/content-state/{analysis}/{FEATURES['open']}",
            f"/iiif/data/{file_id}/raw",
        ]
        for url in urls:
            with self.subTest(url=url):
                with CaptureQueriesContext(connection) as context:
                    response = self.visitor.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    sum("ms_data_change" in q["sql"] for q in context.captured_queries),
                    1,
                )
