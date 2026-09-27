"""``iiif.memo``: the visitor's view is memoised and revalidated; no other reader's ever is.

Usage:
    python manage.py test tests.test_iiif_memo --settings=tests.test_settings
"""

from unittest import mock

from django.core.cache import cache
from django.test import Client

from tests.explorer_fixtures import IIIFCase


def memo_keys():
    return [k for k in cache._cache if ":iiif:" in k and not k.endswith(":lock")]


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
