"""The map's exports: CSV and GeoJSON of the kept events with their uncertainty fields.

Usage:
    python manage.py test tests.test_explorer_events_export --settings="tests.test_settings"
"""

import csv
import json
import os
import re
from types import SimpleNamespace

from django.http import QueryDict
from django.test import SimpleTestCase

from tests.explorer_events_fixtures import (
    HIGH,
    LEAD_WHITE,
    LOW,
    SMALT,
    VERMILION,
    EventsCase,
)
from tests.test_explorer_service import RED

from manuspectrum.views.explorer.events_export import (
    HEADER,
    _labelled,
    _query_text,
    display_switches,
    shown_events,
)

ORPIMENT = "http://vocab/orpiment"
SWITCHES = os.path.join(
    os.path.dirname(__file__), "fixtures", "explorer", "map-switches.json"
)


def streamed(response):
    return b"".join(response.streaming_content)


class EventsExportTests(EventsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.term_list(
            "characterization",
            "material_confidence",
            [
                (HIGH, None, {"en": "Highly reliable"}),
                (LOW, None, {"en": "Uncertain"}),
            ],
        )
        cls.characterized(
            "Orpiment", cls.components["open"], cls.analyses["open"], ORPIMENT, LOW
        )

    def filename(self, query=""):
        response = self.client.get(f"/api/explorer/events.csv?lang=en{query}")
        return re.search(r'filename="([^"]+)"', response["Content-Disposition"])[1]

    def filters_line(self, comments):
        [line] = [c for c in comments if c.startswith("# Filters:")]
        return line

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

    def low_level(self):
        events = self.client.get("/en/api/explorer/events").json()["events"]
        return next(
            m["reliability"]
            for e in events
            for m in e["materials"]
            if m["id"] == VERMILION
        )

    def test_approximate_hide_drops_the_circa_events_and_absent_keeps_all(self):
        _, every = self.csv()
        self.assertIn("true", {r["approximate"] for r in every})
        comments, rows = self.csv("&approximate=hide")
        self.assertEqual({r["approximate"] for r in rows}, {"false"})
        self.assertLess(len(rows), len(every))
        self.assertTrue(any("approximate=hide" in c for c in comments))
        _, other = self.csv("&approximate=show")
        self.assertEqual(len(other), len(every))

    def test_hide_level_drops_those_materials_and_the_events_left_without(self):
        _, every = self.csv()
        low = self.low_level()
        comments, rows = self.csv(f"&hideLevel={low}")
        self.assertIn(VERMILION, {r["material"] for r in every})
        self.assertNotIn(VERMILION, {r["material"] for r in rows})
        self.assertIn(LEAD_WHITE, {r["material"] for r in rows})
        alteration = {r["event"] for r in every if r["type"] == "alteration"}
        bare = {r["event"] for r in every if not r["material"]}
        self.assertTrue(alteration)
        self.assertTrue(bare)
        self.assertFalse(alteration & {r["event"] for r in rows})
        self.assertLessEqual(bare, {r["event"] for r in rows})
        self.assertTrue(any(f"hideLevel=Uncertain <{low}>" in c for c in comments))
        self.assertEqual(self.csv("&hideLevel=not-a-level")[1], every)

    def test_an_event_whose_matching_materials_are_all_hidden_leaves_every_product(
        self,
    ):
        query = f"&material={ORPIMENT}&hideLevel={self.low_level()}"
        _, before = self.csv(f"&material={ORPIMENT}")
        self.assertEqual(
            {(r["type"], r["component"]) for r in before},
            {("production", str(self.components["open"].pk))},
        )
        comments, rows = self.csv(query)
        body = json.loads(
            streamed(self.client.get(f"/api/explorer/events.geojson?lang=en{query}"))
        )
        self.assertEqual(rows, [])
        self.assertEqual(body["features"], [])
        self.assertIsNone(body["citation"])
        self.assertFalse(any(c.startswith("# Cite as") for c in comments))

    def test_an_unknown_level_and_a_shown_approximate_reach_neither_the_filters_line_nor_the_filename(
        self,
    ):
        plain_comments, _ = self.csv()
        for query in ("&hideLevel=not-a-level", "&approximate=show"):
            comments, _ = self.csv(query)
            self.assertEqual(
                self.filters_line(comments), self.filters_line(plain_comments), query
            )
            self.assertEqual(self.filename(query), self.filename(), query)
        low = self.low_level()
        comments, _ = self.csv(f"&hideLevel={low},zzz")
        self.assertNotIn("zzz", self.filters_line(comments))
        self.assertEqual(
            self.filename(f"&hideLevel={low},zzz"), self.filename(f"&hideLevel={low}")
        )

    def test_the_geojson_follows_both_switches(self):
        low = self.low_level()
        plain = json.loads(
            streamed(self.client.get("/api/explorer/events.geojson?lang=en"))
        )
        cut = json.loads(
            streamed(
                self.client.get(
                    f"/api/explorer/events.geojson?lang=en&approximate=hide&hideLevel={low}"
                )
            )
        )
        self.assertLess(len(cut["features"]), len(plain["features"]))
        self.assertFalse(
            any(f["properties"]["date"]["approximate"] for f in cut["features"])
        )
        self.assertNotIn(
            low,
            {
                m["reliability"]
                for f in cut["features"]
                for m in f["properties"]["materials"]
            },
        )
        self.assertIn("approximate=hide", cut["filters"])

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
            "/api/explorer/events.geojson?lang=en&eventType=production"
        )
        self.assertEqual(
            (response.status_code, response["Cache-Control"]),
            (200, "private, no-store"),
        )
        body = json.loads(streamed(response))
        self.assertEqual(body["type"], "FeatureCollection")
        self.assertTrue(any(f["geometry"] is None for f in body["features"]))
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
                "/api/explorer/events.geojson?lang=en&eventType=production",
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

    def test_the_geojson_materials_carry_no_query_flags(self):
        body = json.loads(
            streamed(
                self.client.get(f"/api/explorer/events.geojson?lang=en&colour={RED}")
            )
        )
        materials = [m for f in body["features"] for m in f["properties"]["materials"]]
        self.assertTrue(materials)
        for material in materials:
            self.assertNotIn("matches", material)
            self.assertNotIn("componentColours", material)


class EventsExportHierarchyTests(EventsCase):
    csv = EventsExportTests.csv
    PIGMENT = "http://vocab/pigment"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.term_list(
            "characterization",
            "identified_material",
            [
                (cls.PIGMENT, None, {"en": "Pigment", "fr": "Pigment (fr)"}),
                (VERMILION, cls.PIGMENT, {"en": "Vermilion"}),
                (LEAD_WHITE, cls.PIGMENT, {"en": "Lead white"}),
            ],
        )

    def test_the_events_export_applies_the_parent_rule(self):
        _, rows = self.csv(f"&material={self.PIGMENT}")

        self.assertEqual({r["material"] for r in rows}, {VERMILION, LEAD_WHITE})
        self.assertNotIn(SMALT, {r["material"] for r in rows})

    def test_the_csv_header_says_a_filter_term_keeps_its_narrower_terms_in_both_languages(
        self,
    ):
        for lang, sentence in (
            ("en", "A filter term also keeps its narrower terms."),
            ("fr", "Un terme de filtre retient aussi ses termes plus précis."),
        ):
            response = self.client.get(f"/api/explorer/events.csv?lang={lang}")
            comments = [
                l for l in streamed(response).decode().splitlines() if l.startswith("#")
            ]

            self.assertIn(f"# {sentence}", comments, lang)

    def test_the_filters_line_names_each_value_by_label_and_uri(self):
        comments, _ = self.csv(f"&material={self.PIGMENT}&material=http://vocab/zzz")
        [line] = [c for c in comments if c.startswith("# Filters:")]

        self.assertIn(f"Pigment <{self.PIGMENT}>", line)
        self.assertIn("http://vocab/zzz", line)
        self.assertNotIn("<http://vocab/zzz>", line)

    def test_the_filters_line_uses_the_export_language(self):
        response = self.client.get(
            f"/api/explorer/events.csv?lang=fr&material={self.PIGMENT}"
        )
        [line] = [
            l
            for l in streamed(response).decode().splitlines()
            if l.startswith("# Filtres")
        ]

        self.assertIn(f"Pigment (fr) <{self.PIGMENT}>", line)

    def test_the_filters_line_labels_reference_values_only_and_reads_the_colour_alias(
        self,
    ):
        bundle = SimpleNamespace(
            labels={
                "year": {"1450": {"value": "1450"}},
                "colour": {RED: {"value": "Red"}},
            }
        )

        self.assertEqual(
            _labelled(bundle, f"colour={RED}&partColour={RED}&year=1450"),
            f"colour=Red <{RED}>&partColour=Red <{RED}>&year=1450",
        )


class DisplaySwitchesTests(SimpleTestCase):
    def test_the_export_and_the_map_apply_the_same_switches(self):
        with open(SWITCHES, encoding="utf-8") as handle:
            fixture = json.load(handle)
        for case in fixture["cases"]:
            shown = shown_events(
                fixture["events"],
                case["hideApproximate"],
                set(case["hiddenLevels"]),
            )
            self.assertEqual(
                [
                    {"id": e["id"], "materials": [m["id"] for m in e["materials"]]}
                    for e in shown
                ],
                case["expected"],
                case["name"],
            )

    def test_only_the_levels_of_the_scale_are_read(self):
        query = QueryDict("hideLevel=a, zzz&hideLevel=b&approximate=show")
        self.assertEqual(display_switches(query, {"a", "b"}), (False, {"a", "b"}))
        self.assertEqual(
            display_switches(QueryDict("approximate=hide"), set()), (True, set())
        )

    def test_the_query_text_writes_the_switches_only_as_they_act(self):
        query = QueryDict("q=lead&lang=fr&hideLevel=zzz&approximate=show")
        self.assertEqual(_query_text(query, False, set()), "q=lead")
        self.assertEqual(
            _query_text(query, True, {"b", "a"}),
            "approximate=hide&hideLevel=a&hideLevel=b&q=lead",
        )

    def test_the_filters_line_strips_the_level_ids(self):
        bundle = SimpleNamespace(
            labels={},
            certainty={
                "levels": [
                    {"id": "a", "label": {"value": "Sure"}},
                    {"id": "b", "label": {"value": "Unsure"}},
                ]
            },
        )
        self.assertEqual(
            _labelled(bundle, "hideLevel=a, b"), "hideLevel=Sure <a>, Unsure <b>"
        )
