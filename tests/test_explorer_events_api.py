"""HTTP contract of the map's events route.

Usage:
    python manage.py test tests.test_explorer_events_api --settings="tests.test_settings"
"""

from unittest import mock

from tests.explorer_contract import assert_shape
from tests.explorer_events_fixtures import VERMILION, EventsCase

from manuspectrum.views.explorer import service as explorer_service

URL = "/en/api/explorer/events"
ALL_TYPES = (
    "?eventType=production&eventType=modification&eventType=alteration"
    "&eventType=analysis&eventType=sampling"
)


class EventsRouteTests(EventsCase):
    def get(self, query="", **headers):
        return self.client.get(f"{URL}{query}", **headers)

    def types(self, payload):
        return {e["type"] for e in payload["events"]}

    def test_the_visitor_gets_the_events_with_the_contract_shapes(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, no-cache")
        payload = response.json()
        assert_shape(self, payload, "EventsResponse")
        for event in payload["events"]:
            assert_shape(self, event, "MapEvent")
            for material in event["materials"]:
                assert_shape(self, material, "EventMaterial")
        for place in payload["places"].values():
            assert_shape(self, place, "MapPlace")
        for material in payload["materials"].values():
            assert_shape(self, material, "MapMaterial")
        for colour in payload["colours"].values():
            assert_shape(self, colour, "MapColour")
        self.assertEqual(
            set(payload["colours"]),
            {c for m in payload["materials"].values() for c in m["colours"]},
        )
        self.assertEqual(
            set(payload["analysisNames"]),
            {a for e in payload["events"] for a in e["analyses"]},
        )
        self.assertEqual(
            self.types(payload), {"production", "modification", "alteration"}
        )
        everything = self.get(
            "?eventType=production&eventType=modification&eventType=alteration"
            "&eventType=analysis&eventType=sampling"
        ).json()
        self.assertEqual(
            self.types(everything),
            {"production", "modification", "alteration", "analysis", "sampling"},
        )

    def test_analysis_and_sampling_events_come_only_when_asked(self):
        self.assertFalse(self.types(self.get().json()) & {"analysis", "sampling"})
        asked = self.get("?eventType=analysis&eventType=sampling").json()
        self.assertEqual(self.types(asked), {"analysis", "sampling"})

    def test_analysis_names_are_those_of_the_returned_events_only(self):
        for query in ("", "?eventType=analysis", "?eventType=modification"):
            payload = self.get(query).json()
            self.assertEqual(
                set(payload["analysisNames"]),
                {a for e in payload["events"] for a in e["analyses"]},
            )

    def test_analysis_techniques_are_the_bundle_marks_of_the_returned_analyses(self):
        bundle = self.bundle()
        for query in ("", ALL_TYPES, "?eventType=modification"):
            payload = self.get(query).json()
            cited = {a for e in payload["events"] for a in e["analyses"]}
            self.assertEqual(
                payload["analysisTechniques"],
                {
                    a: bundle.marks[bundle.by_id[a]["technique"]["uri"]]
                    for a in cited
                    if bundle.by_id[a]["technique"]
                },
            )
            for mark in payload["analysisTechniques"].values():
                assert_shape(self, mark, "TechniqueMark")
        self.assertTrue(self.get(ALL_TYPES).json()["analysisTechniques"])

    def test_the_default_and_the_explicit_material_types_share_one_etag(self):
        explicit = self.get(
            "?eventType=alteration&eventType=production&eventType=modification"
        )
        self.assertEqual(self.get()["ETag"], explicit["ETag"])

    def test_a_held_etag_answers_304_without_building_the_bundle(self):
        etag = self.get("?eventType=modification")["ETag"]
        with (
            mock.patch.object(
                explorer_service, "build_bundle", side_effect=AssertionError
            ),
            mock.patch.object(
                explorer_service.explorer_memo, "remember", side_effect=AssertionError
            ),
        ):
            again = self.get("?eventType=modification", HTTP_IF_NONE_MATCH=etag)
        self.assertEqual((again.status_code, again["ETag"]), (304, etag))

    def test_event_types_narrow_the_events_and_enter_the_etag(self):
        plain = self.get()
        narrowed = self.get("?eventType=modification&eventType=alteration")
        self.assertEqual(self.types(narrowed.json()), {"modification", "alteration"})
        self.assertNotEqual(plain["ETag"], narrowed["ETag"])

    def test_an_unknown_event_type_is_ignored_with_the_same_body_and_etag(self):
        plain, odd = self.get(), self.get("?eventType=party")
        self.assertEqual((odd.content, odd["ETag"]), (plain.content, plain["ETag"]))

    def test_the_material_filter_keeps_the_object_events_that_carry_it(self):
        payload = self.get(f"?material={VERMILION}").json()
        self.assertEqual(
            {
                e["type"]
                for e in payload["events"]
                if e["type"] in ("production", "modification", "alteration")
            },
            {"alteration"},
        )

    def test_the_period_bears_on_each_event_s_own_dates(self):
        url = "?period=1420,1425&eventType=production&eventType=modification"
        ids = {e["carrier"]["id"] for e in self.get(url).json()["events"]}
        self.assertIn(str(self.modification.pk), ids)
        self.assertIn(str(self.documents["open"].pk), ids)
        self.assertNotIn(str(self.components["open"].pk), ids)
        within = {
            e["carrier"]["id"]
            for e in self.get("?period=1400,1500&periodMatch=within").json()["events"]
        }
        self.assertIn(str(self.documents["open"].pk), within)
        self.assertNotIn(str(self.components["open"].pk), within)

    def test_undated_keeps_the_undated_events(self):
        ids = {
            e["carrier"]["id"]
            for e in self.get("?period=1000,1100&undated=1").json()["events"]
        }
        self.assertIn(str(self.documents["derived"].pk), ids)
        ids = {
            e["carrier"]["id"] for e in self.get("?period=1000,1100").json()["events"]
        }
        self.assertNotIn(str(self.documents["derived"].pk), ids)

    def test_unplaced_counts_the_events_without_a_mapped_place(self):
        payload = self.get(ALL_TYPES).json()
        expected = sum(
            1
            for e in payload["events"]
            if not e["place"] or payload["places"][e["place"]]["lngLat"] is None
        )
        self.assertEqual(payload["unplaced"], expected)
        self.assertGreaterEqual(expected, 1)

    def test_the_places_hold_the_ancestors_of_the_places_used(self):
        places = self.get().json()["places"]
        self.assertTrue(places[str(self.places["france"].pk)]["unpublished"])

    def test_a_signed_in_reader_gets_the_visitor_s_events_privately(self):
        plain = self.get()
        self.client.force_login(self.editor)
        mine = self.get()
        self.assertEqual(mine["Cache-Control"], "private, no-store")
        self.assertEqual(mine.json(), plain.json())

    def test_a_gzipped_answer_carries_a_weak_etag_that_revalidates(self):
        response = self.get(HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(response["Content-Encoding"], "gzip")
        self.assertTrue(response["ETag"].startswith('W/"'))
        again = self.get(
            HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=response["ETag"]
        )
        self.assertEqual(again.status_code, 304)


class HistoryAndFindTests(EventsCase):
    def test_the_document_payload_history_comes_from_the_events(self):
        from manuspectrum.views.explorer.service import document_payload

        history = document_payload(self.documents["open"].pk, self.anonymous, "en")[
            "history"
        ]
        for line in history:
            assert_shape(self, line, "HistoryLine")
        self.assertEqual(history[0]["carrier"]["model"], "document")
        self.assertIn("modification", {line["type"] for line in history})

    def test_the_material_search_finds_an_alternative_label(self):
        values = self.client.get(
            "/en/api/explorer/facet/material?find=cinnabar"
        ).json()["values"]
        self.assertIn(VERMILION, [v["id"] for v in values])
