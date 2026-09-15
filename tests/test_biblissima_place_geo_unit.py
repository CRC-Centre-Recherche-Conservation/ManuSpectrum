"""GeoNames data of Places: Wikibase resolution, creation, link enrichment.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_place_geo_unit \\
        --settings="tests.test_settings" --noinput
"""

import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import TestCase

from manuspectrum.views import biblissima_proxy as bp
from tests.test_biblissima_write_transaction_unit import (
    PATCH_TILEMODEL,
    WriteTransactionHarness,
)

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


class PlaceDependencyGeoTests(WriteTransactionHarness):
    def setUp(self):
        super().setUp()
        self.tile_model = self._start(patch(PATCH_TILEMODEL))
        self.tile_model.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        self.place_geo = self._start(
            patch.object(bp, "_get_place_geo", return_value=dict(PARIS_GEO))
        )

    def _create(self, resource_type="Place", **data):
        return self.view.post(
            self._request(
                {
                    "resourceType": resource_type,
                    "biblissimaData": {"label": "Paris (France)", **data},
                }
            )
        )

    def _tiles(self):
        return {
            call.kwargs["nodegroup_id"]: call.kwargs["data"]
            for call in self.tile_model.call_args_list
        }

    def _flushed_nodegroups(self):
        (flushed,) = [
            call.args[0]
            for call in self.mock_run_hook.call_args_list
            if call.args[3] == "post_tile_save"
        ]
        return [tile.nodegroup_id for tile in flushed]

    def test_a_place_with_a_qid_gets_its_geonames_identifier_and_point(self):
        response = self._create(biblissimaQid="Q27392")

        self.assertEqual(response.status_code, 200)
        tiles = self._tiles()
        self.assertEqual(
            tiles[bp.PLACE_IDENTIFIER_NG][bp.PLACE_IDENTIFIER_VALUE]["fr"]["value"],
            "https://www.geonames.org/2988507/",
        )
        collection = tiles[bp.PLACE_LITERAL_LOCATION_NG][bp.PLACE_LITERAL_LOCATION_NODE]
        self.assertEqual(collection["type"], "FeatureCollection")
        feature = collection["features"][0]
        self.assertEqual(
            feature["geometry"], {"type": "Point", "coordinates": [2.3488, 48.85341]}
        )
        self.assertEqual(
            feature["properties"], {"nodeId": bp.PLACE_LITERAL_LOCATION_NODE}
        )
        self.place_geo.assert_called_once_with("Q27392")

    def test_the_geonames_tiles_are_staged_before_the_transaction_opens(self):
        self._create(biblissimaQid="Q27392")

        opened = self.events.index("atomic:enter")
        self.assertEqual(self.events[:opened].count(("validate", False)), 3)

    def test_a_place_without_coordinates_gets_only_the_identifier(self):
        self.place_geo.return_value = {
            "geonamesId": "2988507",
            "latitude": None,
            "longitude": None,
        }

        self._create(biblissimaQid="Q27392")

        self.assertIn(bp.PLACE_IDENTIFIER_NG, self._tiles())
        self.assertNotIn(bp.PLACE_LITERAL_LOCATION_NG, self._tiles())

    def test_a_place_without_a_qid_asks_nothing_and_gets_only_its_name(self):
        self._create()

        self.place_geo.assert_not_called()
        self.assertEqual(list(self._tiles()), [bp.PLACE_NAME_NG])

    def test_an_unreachable_wikibase_still_creates_the_place(self):
        self.place_geo.return_value = None

        response = self._create(biblissimaQid="Q27392")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self._tiles()), [bp.PLACE_NAME_NG])

    def test_geonames_tiles_refused_by_validation_are_dropped_and_the_place_created(
        self,
    ):
        from arches.app.models.tile import TileValidationError

        calls = []

        def validate(tiles, nodes_by_id, factory):
            calls.append(len(tiles))
            if len(calls) >= 2:
                raise TileValidationError("Geometry Out Of Bounds")

        self._start(
            patch.object(
                bp.BiblissimaCreateResourceView, "_validate_tiles", side_effect=validate
            )
        )

        with self.assertLogs(LOGGER, level="WARNING"):
            response = self._create(biblissimaQid="Q27392")

        self.assertEqual(response.status_code, 200)
        flushed = [
            call.args[0]
            for call in self.mock_run_hook.call_args_list
            if call.args[3] == "post_tile_save"
        ]
        self.assertEqual(len(flushed[0]), 1)

    def test_a_group_ignores_a_biblissima_qid(self):
        self._create(resource_type="Group", biblissimaQid="Q32811")

        self.place_geo.assert_not_called()

    def test_a_point_refused_by_validation_keeps_the_identifier(self):
        from arches.app.models.tile import TileValidationError

        calls = []

        def validate(tiles, nodes_by_id, factory):
            calls.append(len(tiles))
            if len(calls) == 3:
                raise TileValidationError("Geometry Out Of Bounds")

        self._start(
            patch.object(
                bp.BiblissimaCreateResourceView, "_validate_tiles", side_effect=validate
            )
        )

        with self.assertLogs(LOGGER, level="WARNING") as logs:
            response = self._create(biblissimaQid="Q27392")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._flushed_nodegroups(), [bp.PLACE_NAME_NG, bp.PLACE_IDENTIFIER_NG]
        )
        self.assertIn("location", logs.output[0])
        self.assertIn("Q27392", logs.output[0])

    def test_an_unresolvable_geonames_source_drops_only_the_identifier(self):
        def concept_list(concept_ids):
            if bp.CONCEPT_SOURCE_GEONAMES in concept_ids:
                raise LookupError(bp.CONCEPT_SOURCE_GEONAMES)
            return []

        self.view._concept_list = concept_list

        with self.assertLogs(LOGGER, level="WARNING") as logs:
            response = self._create(biblissimaQid="Q27392")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._flushed_nodegroups(), [bp.PLACE_NAME_NG, bp.PLACE_LITERAL_LOCATION_NG]
        )
        self.assertIn("identifier", logs.output[0])


class PlaceLiteralLocationDatatypeTests(TestCase):
    def test_the_arches_datatype_accepts_the_point_and_keeps_its_uuid_feature_id(
        self,
    ):
        from arches.app.datatypes.datatypes import DataTypeFactory

        view = bp.BiblissimaCreateResourceView()
        view._tile_buffer = []
        view._place_geo_tiles(
            "dddddddd-dddd-dddd-dddd-dddddddddddd", PARIS_GEO, ("location",)
        )
        (tile,) = view._tile_buffer
        value = tile.data[bp.PLACE_LITERAL_LOCATION_NODE]
        feature_id = value["features"][0]["id"]
        datatype = DataTypeFactory().get_instance("geojson-feature-collection")

        errors = datatype.validate(
            value,
            node=SimpleNamespace(
                nodeid=bp.PLACE_LITERAL_LOCATION_NODE,
                datatype="geojson-feature-collection",
                config={},
            ),
        )
        datatype.pre_tile_save(tile, bp.PLACE_LITERAL_LOCATION_NODE)

        self.assertEqual([e for e in errors if e["type"] == "ERROR"], [])
        self.assertEqual(feature_id, str(uuid.UUID(feature_id)))
        self.assertEqual(
            tile.data[bp.PLACE_LITERAL_LOCATION_NODE]["features"][0]["id"], feature_id
        )
