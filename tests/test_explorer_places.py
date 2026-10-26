"""Pure helpers of the map's places: geometry summary, derived copies, authorities.

Usage:
    python manage.py test tests.test_explorer_places --settings="tests.test_settings"
"""

from django.test import SimpleTestCase

from manuspectrum.views.explorer.places import (
    authorities_of,
    derived_only,
    geometry_summary,
    haversine_km,
)

C_SHAPE = [[0, 0], [3, 0], [3, 1], [1, 1], [1, 2], [3, 2], [3, 3], [0, 3], [0, 0]]


def fc(*geometries, properties=None):
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": g, "properties": properties or {}}
            for g in geometries
        ],
    }


class GeometrySummaryTests(SimpleTestCase):
    def test_a_point_is_read_as_stored_in_wgs84(self):
        found = geometry_summary(
            fc({"type": "Point", "coordinates": [2.3488, 48.8534]})
        )
        self.assertEqual(
            (found.lng_lat, found.kind, found.extent_km),
            ((2.3488, 48.8534), "point", None),
        )

    def test_a_polygon_is_an_area_at_a_label_point_inside_it_with_its_extent(self):
        found = geometry_summary(fc({"type": "Polygon", "coordinates": [C_SHAPE]}))
        self.assertEqual(found.kind, "area")
        self.assertEqual(found.lng_lat, (0.5, 1.5))
        self.assertAlmostEqual(
            found.extent_km, haversine_km((0, 0), (3, 3)) / 2, places=0
        )

    def test_a_multipolygon_is_labelled_in_its_largest_ring(self):
        small = [[[10, 10], [10.1, 10], [10.1, 10.1], [10, 10]]]
        large = [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
        self.assertEqual(
            geometry_summary(
                fc({"type": "MultiPolygon", "coordinates": [small, large]})
            ).lng_lat,
            (1.0, 1.0),
        )

    def test_a_line_is_summarised_at_its_first_point(self):
        found = geometry_summary(
            fc({"type": "LineString", "coordinates": [[1, 2], [3, 4]]})
        )
        self.assertEqual((found.lng_lat, found.kind), ((1.0, 2.0), "point"))

    def test_an_empty_or_malformed_collection_has_no_geometry(self):
        for value in (
            None,
            {},
            "x",
            {"features": []},
            {"features": [{"type": "Feature"}]},
            fc({"type": "Point", "coordinates": [500, 0]}),
            fc({"type": "Point", "coordinates": ["a", "b"]}),
            fc({"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}),
        ):
            with self.subTest(value=value):
                self.assertIsNone(geometry_summary(value))


class DerivedOnlyTests(SimpleTestCase):
    def test_only_a_collection_whose_every_feature_is_derived_is_derived(self):
        point = {"type": "Point", "coordinates": [1, 1]}
        self.assertTrue(
            derived_only(fc(point, properties={"msDerivedFrom": {"place": "p"}}))
        )
        self.assertFalse(derived_only(fc(point)))
        self.assertFalse(derived_only(fc()))


class AuthoritiesTests(SimpleTestCase):
    def test_geonames_and_wikidata_ids_are_read_off_their_urls_or_a_bare_q_id(self):
        self.assertEqual(
            authorities_of(["https://www.geonames.org/2988507/paris.html", "Q90"]),
            {"geonames": "2988507", "wikidata": "Q90"},
        )
        self.assertEqual(
            authorities_of(["https://www.wikidata.org/wiki/Q1"]), {"wikidata": "Q1"}
        )
        self.assertEqual(authorities_of(["Paris, ville", "", None]), {})


class HaversineTests(SimpleTestCase):
    def test_paris_london(self):
        self.assertAlmostEqual(
            haversine_km((2.3488, 48.8534), (-0.1276, 51.5072)), 343.5, delta=1.5
        )
