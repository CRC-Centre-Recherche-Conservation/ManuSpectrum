"""AnnotationPages and AnnotationCollections built from document facts, without the database.

Usage:
    python manage.py test tests.test_iiif_pages --settings=tests.test_settings
"""

from unittest import mock

from django.test import SimpleTestCase

from manuspectrum.iiif import pages
from manuspectrum.iiif.facts import AnalysisFact, DocumentFacts, Zone


def analysis(analysis_id, *zones):
    return AnalysisFact(
        analysis_id, {}, zones, (), (), {}, {}, {}, {}, {}, {}, {}, {}, None, False
    )


def document(*analyses):
    return DocumentFacts("d", {}, None, ("c1", "c2", "c3"), ("1", "2", "3"), analyses)


def encoded(doc, fact, zone):
    return {"id": f"{fact.id}/{zone.feature}"}


class PageTests(SimpleTestCase):
    def setUp(self):
        self.doc = document(
            analysis("a", Zone("f1", "c1", 1, None), Zone("f3", "c3", 3, None)),
            analysis("b", Zone("f2", "c3", 3, None)),
        )

    def test_a_page_encodes_only_its_own_zones(self):
        with mock.patch.object(
            pages, "analysis_annotation", side_effect=encoded
        ) as encode:
            page = pages.annotation_page(self.doc, 3)

        self.assertEqual([a["id"] for a in page["items"]], ["a/f3", "b/f2"])
        self.assertEqual(encode.call_count, 2)
        self.assertEqual(page["prev"]["id"], pages.ids.page("d", 1))

    def test_the_collection_counts_zones_without_encoding_them(self):
        with mock.patch.object(pages, "analysis_annotation") as encode:
            collection = pages.annotation_collection(self.doc)

        encode.assert_not_called()
        self.assertEqual(collection["total"], 3)
        self.assertEqual(collection["last"]["id"], pages.ids.page("d", 3))
