"""GeoNames data of Places: Wikibase resolution, creation, link enrichment.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_place_geo_unit \\
        --settings="tests.test_settings" --noinput
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import TestCase

from manuspectrum.views import biblissima_proxy as bp

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "biblissima")
LOGGER = "manuspectrum.views.biblissima_proxy"
PARIS_GEO = {"geonamesId": "2988507", "latitude": 48.85341, "longitude": 2.3488}


def _claims(fixture, qid):
    with open(os.path.join(FIXTURE_DIR, fixture), encoding="utf-8") as f:
        return json.load(f)["entities"][qid]["claims"]


def _coordinates(
    latitude, longitude, globe="http://www.wikidata.org/entity/Q2", rank="normal"
):
    value = {"latitude": latitude, "longitude": longitude, "globe": globe}
    return [{"rank": rank, "mainsnak": {"datavalue": {"value": value}}}]


def _geonames(value):
    return [{"mainsnak": {"datavalue": {"value": value}}}]


class PlaceGeoFromClaimsTests(TestCase):
    def test_reads_the_geonames_id_and_the_coordinates_of_paris(self):
        geo = bp._place_geo_from_claims(_claims("entity_paris_Q27392.json", "Q27392"))

        self.assertEqual(geo, PARIS_GEO)

    def test_a_place_without_those_claims_has_neither(self):
        self.assertEqual(
            bp._place_geo_from_claims({}),
            {"geonamesId": None, "latitude": None, "longitude": None},
        )

    def test_coordinates_on_another_globe_are_ignored(self):
        geo = bp._place_geo_from_claims(
            {
                bp.P276: _coordinates(
                    10.0, 20.0, globe="http://www.wikidata.org/entity/Q405"
                )
            }
        )

        self.assertIsNone(geo["latitude"])
        self.assertIsNone(geo["longitude"])

    def test_out_of_range_coordinates_are_ignored(self):
        geo = bp._place_geo_from_claims({bp.P276: _coordinates(91.0, 2.0)})

        self.assertIsNone(geo["latitude"])

    def test_a_geonames_id_that_is_not_a_number_is_ignored(self):
        geo = bp._place_geo_from_claims({bp.P123: _geonames("2988507; x")})

        self.assertIsNone(geo["geonamesId"])

    def test_a_geonames_id_in_non_ascii_digits_is_ignored(self):
        geo = bp._place_geo_from_claims({bp.P123: _geonames("٢٩٨٨٥٠٧")})

        self.assertIsNone(geo["geonamesId"])

    def test_boolean_coordinates_are_ignored(self):
        geo = bp._place_geo_from_claims({bp.P276: _coordinates(True, 2.0)})

        self.assertIsNone(geo["latitude"])

    def test_a_deprecated_coordinates_statement_is_skipped(self):
        geo = bp._place_geo_from_claims(
            {
                bp.P276: _coordinates(10.0, 20.0, rank="deprecated")
                + _coordinates(48.85341, 2.3488)
            }
        )

        self.assertEqual(geo["latitude"], 48.85341)
        self.assertEqual(geo["longitude"], 2.3488)


class GetPlaceGeoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _serve(self, payload):
        response = SimpleNamespace(
            status_code=200, raise_for_status=lambda: None, json=lambda: payload
        )
        patcher = patch.object(bp, "_bib_request", return_value=response)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_the_claims_are_fetched_through_the_guarded_path(self):
        fetch = self._serve({"entities": {"Q27392": {"claims": {}}}})

        bp._get_place_geo("Q27392")

        args, kwargs = fetch.call_args
        self.assertTrue(args[1].startswith(bp.BIBLISSIMA_WIKIBASE + "?"))
        self.assertIn("ids=Q27392", args[1])
        self.assertIn("props=claims", args[1])
        self.assertTrue(kwargs["guarded"])
        self.assertEqual(kwargs["timeout"], bp.REQUEST_TIMEOUT)
        self.assertIs(args[0], bp._get_biblissima_session())

    def test_a_resolved_place_is_cached(self):
        fetch = self._serve(
            {
                "entities": {
                    "Q27392": {"claims": _claims("entity_paris_Q27392.json", "Q27392")}
                }
            }
        )

        self.assertEqual(bp._get_place_geo("Q27392"), PARIS_GEO)
        self.assertEqual(bp._get_place_geo("Q27392"), PARIS_GEO)
        self.assertEqual(fetch.call_count, 1)

    def test_a_failed_fetch_returns_none_and_is_not_cached(self):
        patcher = patch.object(
            bp, "_bib_request", side_effect=requests.exceptions.Timeout()
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        with self.assertLogs(LOGGER, level="WARNING"):
            self.assertIsNone(bp._get_place_geo("Q27392"))

        self.assertIsNone(
            cache.get(bp._BIBLISSIMA_PLACE_GEO_CACHE_KEY.format(qid="Q27392"))
        )

    def test_an_error_answer_returns_none_and_is_not_cached(self):
        self._serve({"error": {"code": "no-such-entity"}})

        with self.assertLogs(LOGGER, level="WARNING"):
            self.assertIsNone(bp._get_place_geo("Q27392"))

        self.assertIsNone(
            cache.get(bp._BIBLISSIMA_PLACE_GEO_CACHE_KEY.format(qid="Q27392"))
        )

    def test_a_malformed_qid_is_rejected_without_fetching(self):
        fetch = self._serve({})

        for bad in ("", None, "P123", "Q1|Q2", "Q27392&action=x"):
            with self.subTest(bad=bad):
                self.assertIsNone(bp._get_place_geo(bad))

        fetch.assert_not_called()
