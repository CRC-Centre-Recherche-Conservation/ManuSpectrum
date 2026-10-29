"""A language-prefixed request for an xyReading document is sent to its unprefixed id.

Usage:
    python manage.py test tests.test_iiif_xy_reading_redirect --settings=tests.test_settings
"""

from django.test import Client, TestCase

PATHS = ("1.jsonld", "1", "1/schema.json")


class PrefixedXYReadingRedirectTests(TestCase):
    def test_every_prefixed_path_redirects_for_good_to_the_unprefixed_one(self):
        for lang in ("en", "fr"):
            for suffix in PATHS:
                with self.subTest(lang=lang, suffix=suffix):
                    response = Client().get(f"/{lang}/iiif/context/xy-reading/{suffix}")
                    self.assertEqual(response.status_code, 301)
                    self.assertEqual(
                        response["Location"], f"/iiif/context/xy-reading/{suffix}"
                    )

    def test_the_query_string_is_kept(self):
        response = Client().get("/fr/iiif/context/xy-reading/1?x=1")
        self.assertEqual(response["Location"], "/iiif/context/xy-reading/1?x=1")

    def test_the_unprefixed_documents_still_answer(self):
        for suffix in PATHS:
            with self.subTest(suffix=suffix):
                response = Client().get(f"/iiif/context/xy-reading/{suffix}")
                self.assertEqual(response.status_code, 200)

    def test_other_prefixed_paths_are_not_redirected(self):
        response = Client().get("/en/iiif/context/xy-reading/2")
        self.assertNotEqual(response.status_code, 301)
