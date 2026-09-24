"""GeoNames data of Places: Wikibase resolution, creation, link enrichment.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_place_geo_unit \\
        --settings="tests.test_settings" --noinput
"""

import json
import os
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import TestCase

from arches.app.models.models import (
    GraphModel,
    Language,
    NodeGroup,
    ResourceInstance,
    TileModel,
)
from arches_controlled_lists.models import List, ListItem, ListItemValue

from manuspectrum.views import biblissima_proxy as bp
from tests.test_biblissima_write_transaction_unit import (
    PATCH_TILEMODEL,
    WriteTransactionHarness,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "biblissima")
LOGGER = "manuspectrum.views.biblissima_proxy"
PARIS_GEO = {"geonamesId": "2988507", "latitude": 48.85341, "longitude": 2.3488}
View = bp.BiblissimaCreateResourceView
USER = SimpleNamespace(id=7, username="editor", first_name="", last_name="", email="")


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
            status_code=200,
            headers={},
            raise_for_status=lambda: None,
            json=lambda: payload,
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


class MissingPlaceGeoPartsDatabaseTests(TestCase):
    """The presence query, against tiles the import itself writes.

    The identifier check is a JSONB containment on the reference value the
    controlled-lists library serialises; these tests build that value through
    the real ``ListItem`` so a change of shape in the library is caught here.
    A test run never loads the package: the Place graph, the two nodegroups
    and the two list items are created below.
    """

    LIFECYCLE_ID = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"
    OTHER_SOURCE = "0a4c3d2e-5f6a-4b7c-8d9e-0f1a2b3c4d5e"

    @classmethod
    def setUpTestData(cls):
        cls.graph = GraphModel.objects.create(
            graphid=bp.PLACE_GRAPH_ID,
            name="Place",
            isresource=True,
            is_active=True,
            slug="place-geo-parts-tests",
            resource_instance_lifecycle_id=cls.LIFECYCLE_ID,
        )
        NodeGroup.objects.create(nodegroupid=bp.PLACE_IDENTIFIER_NG, cardinality="n")
        NodeGroup.objects.create(
            nodegroupid=bp.PLACE_LITERAL_LOCATION_NG, cardinality="1"
        )
        Language.objects.get_or_create(
            code="en",
            defaults={"name": "en", "default_direction": "ltr", "scope": "system"},
        )
        sources = List.objects.create(id=uuid.uuid4(), name="Source")
        for sortorder, (item_id, label) in enumerate(
            (
                (bp.CONCEPT_SOURCE_GEONAMES, "Geonames"),
                (bp.CONCEPT_RECORD_ID, "Record identifier"),
                (cls.OTHER_SOURCE, "Another source"),
            )
        ):
            item = ListItem.objects.create(
                id=item_id,
                uri=f"https://example.org/{item_id}",
                list=sources,
                sortorder=sortorder,
            )
            ListItemValue.objects.create(
                id=uuid.uuid4(),
                list_item=item,
                valuetype_id="prefLabel",
                language_id="en",
                value=label,
            )

    def setUp(self):
        self.rid = str(ResourceInstance.objects.create(graph=self.graph).pk)
        self.view = View()
        self.view._tile_buffer = []

    def _write(self, parts):
        self.view._place_geo_tiles(self.rid, PARIS_GEO, parts)
        TileModel.objects.bulk_create(self.view._tile_buffer)
        self.view._tile_buffer = []

    def test_a_place_without_tiles_lacks_both_parts(self):
        self.assertEqual(
            View._missing_place_geo_parts(self.rid), ["identifier", "location"]
        )

    def test_the_identifier_the_import_writes_counts_as_present(self):
        self._write(("identifier",))

        self.assertEqual(View._missing_place_geo_parts(self.rid), ["location"])

    def test_the_location_the_import_writes_counts_as_present(self):
        self._write(("location",))

        self.assertEqual(View._missing_place_geo_parts(self.rid), ["identifier"])

    def test_a_place_with_both_parts_lacks_nothing(self):
        self._write(("identifier", "location"))

        self.assertEqual(View._missing_place_geo_parts(self.rid), [])

    def test_an_identifier_from_another_source_does_not_count(self):
        self.view._create_tile(
            bp.PLACE_IDENTIFIER_NG,
            self.rid,
            {
                bp.PLACE_IDENTIFIER_VALUE: self.view._i18n_string("VIAF 123"),
                bp.PLACE_IDENTIFIER_SOURCE: self.view._concept_list(
                    [self.OTHER_SOURCE]
                ),
                bp.PLACE_IDENTIFIER_TYPE: self.view._concept_list(
                    [bp.CONCEPT_RECORD_ID]
                ),
            },
        )
        TileModel.objects.bulk_create(self.view._tile_buffer)

        self.assertEqual(
            View._missing_place_geo_parts(self.rid), ["identifier", "location"]
        )

    def test_another_place_s_tiles_do_not_count(self):
        other = str(ResourceInstance.objects.create(graph=self.graph).pk)
        self.view._place_geo_tiles(other, PARIS_GEO, ("identifier", "location"))
        TileModel.objects.bulk_create(self.view._tile_buffer)

        self.assertEqual(
            View._missing_place_geo_parts(self.rid), ["identifier", "location"]
        )


class ExistingPlaceGeoTests(TestCase):
    def setUp(self):
        self.events = []
        self.in_transaction = False
        self.rid = str(uuid.uuid4())

        @contextmanager
        def recording_atomic(*args, **kwargs):
            self.events.append("atomic:enter")
            self.in_transaction = True
            try:
                yield
            finally:
                self.in_transaction = False
                self.events.append("atomic:exit")

        self._start(patch("django.db.transaction.atomic", new=recording_atomic))
        self._start(patch("arches.app.datatypes.datatypes.DataTypeFactory"))
        self.resource_cls = self._start(patch("arches.app.models.resource.Resource"))
        self.get_graph = self.resource_cls.return_value.get_serialized_graph
        self.get_graph.return_value = {"nodes": []}
        self.ri = self._start(
            patch("manuspectrum.views.biblissima_proxy.ResourceInstance")
        )
        self.ri.objects.filter.return_value.exists.return_value = True
        locked = self.ri.objects.select_for_update.return_value.filter.return_value
        locked.values_list.side_effect = lambda *a, **k: (
            self.events.append(("lock", self.in_transaction)) or [self.rid]
        )
        self.place_geo = self._start(
            patch.object(bp, "_get_place_geo", return_value=dict(PARIS_GEO))
        )
        self.missing = self._start(patch.object(View, "_missing_place_geo_parts"))
        self._start(
            patch.object(
                View,
                "_stage_tiles",
                side_effect=lambda *a: self.events.append(
                    ("stage", self.in_transaction)
                ),
            )
        )
        self.indexing = self._start(patch.object(View, "_defer_indexing"))
        self.flushed = []
        self.flushed_tiles = []

        def flush(view, resource, user, transaction_id):
            self.events.append(("flush", self.in_transaction))
            self.flushed.append([t._mspectrum_place_part for t in view._tile_buffer])
            self.flushed_tiles.extend(view._tile_buffer)

        self.flush = self._start(
            patch.object(View, "_flush_tile_buffer", autospec=True, side_effect=flush)
        )
        self.view = View()
        self.view._concept_list = lambda concept_ids: []

    def _start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def test_only_the_missing_part_is_added(self):
        self.missing.side_effect = [["location"], ["location"]]

        added = self.view._enrich_existing_place(self.rid, "Q27392", USER)

        self.assertEqual(added, ["location"])
        self.assertEqual(self.flushed, [["location"]])
        self.indexing.assert_called_once_with(resource_ids=[self.rid])

    def test_a_place_that_has_both_parts_is_left_untouched(self):
        self.missing.return_value = []

        self.assertEqual(self.view._enrich_existing_place(self.rid, "Q27392", USER), [])

        self.place_geo.assert_not_called()
        self.assertNotIn("atomic:enter", self.events)

    def test_a_part_added_meanwhile_is_not_added_twice(self):
        self.missing.side_effect = [["identifier", "location"], ["location"]]

        added = self.view._enrich_existing_place(self.rid, "Q27392", USER)

        self.assertEqual(added, ["location"])
        self.assertEqual(self.flushed, [["location"]])

    def test_staging_runs_before_the_transaction_and_the_lock_inside_it(self):
        self.missing.side_effect = [["identifier", "location"]] * 2

        self.view._enrich_existing_place(self.rid, "Q27392", USER)

        self.assertEqual(
            [e for e in self.events if isinstance(e, tuple)],
            [("stage", False), ("stage", False), ("lock", True), ("flush", True)],
        )

    def test_a_malformed_qid_is_rejected_without_any_query(self):
        for qid in (None, 42, "P123", "Q1|Q2"):
            with self.subTest(qid=qid):
                self.assertEqual(
                    self.view._enrich_existing_place(self.rid, qid, USER), []
                )

        self.ri.objects.filter.assert_not_called()
        self.missing.assert_not_called()
        self.place_geo.assert_not_called()

    def test_an_unreachable_wikibase_adds_nothing_and_loads_no_graph(self):
        self.missing.return_value = ["identifier", "location"]
        self.place_geo.return_value = None

        self.assertEqual(self.view._enrich_existing_place(self.rid, "Q27392", USER), [])

        self.assertNotIn("atomic:enter", self.events)
        self.flush.assert_not_called()
        self.get_graph.assert_not_called()

    def test_a_place_missing_only_its_location_without_wikibase_coordinates_is_left_untouched(
        self,
    ):
        self.missing.return_value = ["location"]
        self.place_geo.return_value = {
            "geonamesId": "2988507",
            "latitude": None,
            "longitude": None,
        }

        self.assertEqual(self.view._enrich_existing_place(self.rid, "Q27392", USER), [])

        self.assertNotIn("atomic:enter", self.events)
        self.flush.assert_not_called()
        self.get_graph.assert_not_called()

    def test_only_the_missing_parts_wikibase_has_a_value_for_are_staged(self):
        self.missing.side_effect = [["identifier", "location"]] * 2
        self.place_geo.return_value = {
            "geonamesId": "2988507",
            "latitude": 48.85341,
            "longitude": None,
        }

        added = self.view._enrich_existing_place(self.rid, "Q27392", USER)

        self.assertEqual(added, ["identifier"])
        self.assertEqual(
            [e for e in self.events if isinstance(e, tuple)],
            [("stage", False), ("lock", True), ("flush", True)],
        )

    def test_a_resource_that_is_not_a_place_is_left_untouched(self):
        self.ri.objects.filter.return_value.exists.return_value = False

        self.assertEqual(self.view._enrich_existing_place(self.rid, "Q27392", USER), [])

        self.missing.assert_not_called()
        self.place_geo.assert_not_called()

    def test_a_failed_write_adds_nothing_and_does_not_raise(self):
        self.missing.side_effect = [["location"], ["location"]]
        self.flush.side_effect = RuntimeError("tiles check violated")

        with self.assertLogs(LOGGER, level="WARNING"):
            added = self.view._enrich_existing_place(self.rid, "Q27392", USER)

        self.assertEqual(added, [])
        self.indexing.assert_not_called()

    def test_an_added_tile_follows_the_highest_sortorder_of_its_card_or_starts_at_0(
        self,
    ):
        self.missing.side_effect = [["identifier", "location"]] * 2
        existing = {bp.PLACE_IDENTIFIER_NG: [0, 2]}

        def tiles_of(**kwargs):
            def aggregate(*args):
                self.events.append(("sortorder", self.in_transaction))
                sortorders = existing.get(str(kwargs["nodegroup_id"]), [])
                return {"sortorder__max": max(sortorders, default=None)}

            return SimpleNamespace(aggregate=aggregate)

        tiles = self._start(patch.object(bp.TileModel, "objects"))
        tiles.filter.side_effect = tiles_of

        self.view._enrich_existing_place(self.rid, "Q27392", USER)

        self.assertEqual(
            {t._mspectrum_place_part: t.sortorder for t in self.flushed_tiles},
            {"identifier": 3, "location": 0},
        )
        self.assertEqual(
            [e for e in self.events if isinstance(e, tuple)],
            [
                ("stage", False),
                ("stage", False),
                ("lock", True),
                ("sortorder", True),
                ("sortorder", True),
                ("flush", True),
            ],
        )


class AddAltNameEnrichesPlacesTests(TestCase):
    def setUp(self):
        self.rid = str(uuid.uuid4())
        for patcher in (
            patch.object(View, "_defer_indexing"),
            patch.object(View, "_concept_list", return_value=[]),
            patch.object(View, "_attribute_tile_save"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        tile_patcher = patch("manuspectrum.views.biblissima_proxy.Tile")
        self.tile = tile_patcher.start()
        self.addCleanup(tile_patcher.stop)
        self.tile.objects.filter.return_value = []
        enrich_patcher = patch.object(
            View, "_enrich_existing_place", return_value=["identifier"]
        )
        self.enrich = enrich_patcher.start()
        self.addCleanup(enrich_patcher.stop)

    def _post(self, graph_id, **extra):
        body = {"resourceId": self.rid, "graphId": graph_id, "label": "Paris (France)"}
        body.update(extra)
        request = SimpleNamespace(body=json.dumps(body).encode("utf-8"), user=USER)
        return bp.BiblissimaAddAltNameView().post(request)

    def test_a_linked_place_is_enriched_with_its_qid(self):
        response = self._post(bp.PLACE_GRAPH_ID, biblissimaQid="Q27392")

        self.assertEqual(response.status_code, 200)
        self.enrich.assert_called_once_with(self.rid, "Q27392", USER)
        self.assertEqual(json.loads(response.content)["placeGeo"], ["identifier"])

    def test_a_place_whose_name_is_already_present_is_still_enriched(self):
        self.tile.objects.filter.return_value = [
            SimpleNamespace(
                data={bp.PLACE_NAME_LABEL: {"fr": {"value": "Paris (France)"}}}
            )
        ]

        response = self._post(bp.PLACE_GRAPH_ID, biblissimaQid="Q27392")

        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "already_exists")
        self.assertEqual(payload["placeGeo"], ["identifier"])
        self.enrich.assert_called_once_with(self.rid, "Q27392", USER)

    def test_a_person_is_not_enriched(self):
        self._post(bp.PERSON_GRAPH_ID, biblissimaQid="Q1")

        self.enrich.assert_not_called()

    def test_a_place_without_qid_is_not_enriched(self):
        self._post(bp.PLACE_GRAPH_ID)

        self.enrich.assert_not_called()
