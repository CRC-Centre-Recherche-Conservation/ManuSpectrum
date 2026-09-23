"""Contract with the live Biblissima services the import depends on.

Skipped unless ``BIBLISSIMA_LIVE_TESTS=1``: the tests reach
data.biblissima.fr without mocks. They pin stable facts about real records.
A failure means an outage or a change on Biblissima's side that the
unit-test fixtures no longer reflect.

Run:
    BIBLISSIMA_LIVE_TESTS=1 /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_live_contract \\
        --settings="tests.test_settings" --noinput
"""

import os
import time
import unittest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from manuspectrum.views import biblissima_proxy as bp

live = unittest.skipUnless(
    os.environ.get("BIBLISSIMA_LIVE_TESTS") == "1",
    "set BIBLISSIMA_LIVE_TESTS=1 to reach the live Biblissima services",
)


class LiveContractTestCase(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)


@live
class WikibasePlaceContractTests(LiveContractTestCase):
    def test_paris_carries_its_geonames_id_and_coordinates(self):
        geo = bp._get_place_geo("Q27392")

        self.assertIsNotNone(geo, "Wikibase unreadable: outage or API change")
        self.assertEqual(geo["geonamesId"], "2988507")
        self.assertAlmostEqual(geo["latitude"], 48.85, delta=0.1)
        self.assertAlmostEqual(geo["longitude"], 2.35, delta=0.1)

    def test_the_collection_of_francais_11_resolves_to_paris(self):
        manuscript = bp._get_wikibase_entity("Q45769")
        self.assertIsNotNone(manuscript, "Wikibase unreadable: outage or API change")

        result = bp._resolve_collection(manuscript["collection"])

        self.assertEqual(result["locationQid"], "Q27392")
        self.assertEqual(result["geonamesId"], "2988507")


@live
class SuggestPrefixContractTests(LiveContractTestCase):
    def _search(self, text):
        payload = bp._suggest_call(
            {
                "action": "wbsearchentities",
                "search": text,
                "language": "fr",
                "format": "json",
                "limit": 50,
            },
            time.monotonic() + 10,
        )
        return [hit["id"] for hit in payload["search"]]

    def test_case_and_accents_do_not_change_the_upstream_hits(self):
        self.assertEqual(self._search("jero"), self._search("Jéro"))

    def test_an_entity_id_is_matched_exactly_not_by_prefix(self):
        self.assertIn("Q8844", self._search("q8844"))
        self.assertNotIn("Q8844", self._search("q884"))

    def test_a_derived_answer_holds_every_upstream_hit(self):
        entry = bp._suggest_prefix_entry("drag", "fr", time.monotonic() + 10)
        self.assertTrue(
            entry["complete"], "'drag' now has more than 50 hits: use a rarer prefix"
        )
        cache.set(bp._suggest_prefix_key("drag", "fr"), entry, 60)
        with patch.object(bp, "_suggest_call", wraps=bp._suggest_call) as calls:
            derived = bp._suggest_prefix_results(
                "dragon", "fr", "Q304387", 15, time.monotonic() + 10
            )
        self.assertNotIn(
            "wbsearchentities", [c.args[0]["action"] for c in calls.call_args_list]
        )
        cache.clear()

        fresh = bp._suggest_prefix_results(
            "dragon", "fr", "Q304387", 15, time.monotonic() + 10
        )

        self.assertLessEqual({r["id"] for r in fresh}, {r["id"] for r in derived})
