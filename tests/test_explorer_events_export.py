"""The map's exports: CSV and GeoJSON of the kept events with their uncertainty fields.

Usage:
    python manage.py test tests.test_explorer_events_export --settings="tests.test_settings"
"""

import csv
import json

from tests.explorer_events_fixtures import VERMILION, EventsCase
from tests.test_explorer_service import RED

from manuspectrum.views.explorer.events_export import HEADER


def streamed(response):
    return b"".join(response.streaming_content)


class EventsExportTests(EventsCase):
    def csv(self, query=""):
        response = self.client.get(
            f"/api/explorer/events.csv?lang=en{query}", HTTP_ACCEPT_ENCODING="gzip"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertFalse(response.has_header("Content-Encoding"))
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        lines = b"".join(response.streaming_content).decode().splitlines()
        return [l for l in lines if l.startswith("#")], list(
            csv.DictReader(l for l in lines if not l.startswith("#"))
        )

    def test_one_row_per_event_and_material_with_the_uncertainty_fields_and_a_citation(
        self,
    ):
        comments, rows = self.csv()
        self.assertEqual(tuple(rows[0]), HEADER)
        events = self.client.get("/en/api/explorer/events").json()["events"]
        self.assertEqual(len(rows), sum(max(1, len(e["materials"])) for e in events))
        modification = next(r for r in rows if r["type"] == "modification")
        self.assertEqual(
            (
                modification["place_source"],
                modification["approximate"],
                modification["date_start"],
                modification["date_end"],
            ),
            ("parent", "true", "1420", "1430"),
        )
        self.assertTrue(any("[Dataset]" in c for c in comments))

    def test_filters_and_event_types_narrow_the_export_like_the_route(self):
        _, rows = self.csv("&eventType=alteration")
        self.assertEqual({r["type"] for r in rows}, {"alteration"})

    def test_without_an_event_type_the_export_keeps_the_material_events_like_the_map(
        self,
    ):
        _, rows = self.csv()
        self.assertEqual(
            {r["type"] for r in rows}, {"production", "modification", "alteration"}
        )

    def test_curator_text_is_neutralised(self):
        formula = self.new_resource("place", "=HYPERLINK(1)")
        self.tile(self.alteration, "alteration_took_place_at_place", self.refs(formula))
        _, rows = self.csv("&eventType=alteration")
        self.assertIn("'=HYPERLINK(1)", {r["place_name"] for r in rows})

    def test_an_unknown_language_is_a_bad_request(self):
        self.assertEqual(
            self.client.get("/api/explorer/events.csv?lang=xx").status_code, 400
        )
        self.assertEqual(
            self.client.get("/api/explorer/events.geojson?lang=xx").status_code, 400
        )

    def test_the_geojson_holds_one_feature_per_event_and_a_null_geometry_when_unmapped(
        self,
    ):
        response = self.client.get(
            "/api/explorer/events.geojson?lang=en&eventType=sampling,production"
        )
        self.assertEqual(
            (response.status_code, response["Cache-Control"]),
            (200, "private, no-store"),
        )
        body = json.loads(streamed(response))
        self.assertEqual(body["type"], "FeatureCollection")
        sampling = next(
            f for f in body["features"] if f["properties"]["type"] == "sampling"
        )
        self.assertIsNone(sampling["geometry"])
        own = next(
            f
            for f in body["features"]
            if (f["properties"]["place"] or {}).get("source") == "own"
        )
        self.assertEqual(own["geometry"]["type"], "Point")
        self.assertIn("citation", body)

    def test_the_geojson_streams_one_compact_collection_in_chunks(self):
        import orjson
        from unittest.mock import patch

        with patch("manuspectrum.views.explorer.events_export.ROWS_PER_CHUNK", 2):
            response = self.client.get(
                "/api/explorer/events.geojson?lang=en&eventType=analysis,sampling,production",
                HTTP_ACCEPT_ENCODING="gzip",
            )
            chunks = list(response.streaming_content)

        self.assertTrue(response.streaming)
        self.assertFalse(response.has_header("Content-Encoding"))
        self.assertGreater(len(chunks), 3)
        body = b"".join(chunks)
        self.assertEqual(body, orjson.dumps(json.loads(body)))
        collection = json.loads(body)
        self.assertEqual(list(collection)[-1], "features")
        self.assertGreater(len(collection["features"]), 4)

    def test_the_exports_never_carry_a_territories_grid(self):
        self.assertNotIn(
            b"territor",
            streamed(self.client.get("/api/explorer/events.geojson?lang=en")).lower(),
        )


class EventsExportColourTests(EventsCase):
    csv = EventsExportTests.csv

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tile(
            cls.materials["vermilion"],
            "color_aspect",
            cls.reference_value(RED, "Red", "Rouge"),
        )

    def test_the_csv_column_carries_the_colour_labels_and_the_geojson_their_uris(self):
        _, rows = self.csv("&eventType=alteration")
        [row] = [r for r in rows if r["material"] == VERMILION]
        self.assertEqual(row["material_colours"], "Red")
        body = json.loads(
            streamed(
                self.client.get(
                    "/api/explorer/events.geojson?lang=en&eventType=alteration"
                )
            )
        )
        [material] = [
            m
            for f in body["features"]
            for m in f["properties"]["materials"]
            if m["id"] == VERMILION
        ]
        self.assertEqual(material["colours"], [RED])
