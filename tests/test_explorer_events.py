"""The map's events in the corpus bundle (spec 2026-10-09 §2.1).

Usage:
    python manage.py test tests.test_explorer_events --settings="tests.test_settings"
"""

from tests.explorer_events_fixtures import (
    LEAD_WHITE,
    LOW,
    OWN,
    SMALT,
    VERMILION,
    EventsCase,
    collection,
    point,
)
from tests.explorer_fixtures import ACTIVE, DRAFT
from tests.test_explorer_service import AZURITE, GREEN, PART_BLUE, RED

OCHRE = "http://vocab/ochre"


class EventsTests(EventsCase):
    def uris(self, event):
        return {m["id"] for m in event["materials"]}

    def test_productions_carry_their_dates_places_and_the_materials_that_fall_to_them(
        self,
    ):
        bundle = self.bundle()
        [component] = self.events_of(bundle, "production", self.components["open"])
        self.assertEqual(
            component["id"],
            f"production:{self.components['open'].pk}:{self.places['lyon'].pk}",
        )
        self.assertEqual(
            component["date"], {"start": 1380, "end": 1395, "approximate": True}
        )
        self.assertEqual(
            (component["place"], component["placeSource"]),
            (str(self.places["lyon"].pk), "place"),
        )
        self.assertEqual(self.uris(component), {LEAD_WHITE})
        self.assertEqual(component["component"]["id"], str(self.components["open"].pk))
        [document] = self.events_of(bundle, "production", self.documents["open"])
        self.assertEqual(
            document["date"], {"start": 1401, "end": 1500, "approximate": True}
        )
        self.assertEqual(self.uris(document), {SMALT})
        self.assertCountEqual(
            document["analyses"],
            [
                str(self.analyses[k].pk)
                for k in ("open", "on_document", "draft", "bare")
            ],
        )

    def test_a_modification_carries_the_material_it_cites_at_an_attributed_parent_place(
        self,
    ):
        [event] = self.events_of(self.bundle(), "modification", self.modification)
        self.assertEqual(
            (event["place"], event["placeSource"]),
            (str(self.places["normandie"].pk), "parent"),
        )
        self.assertEqual(
            event["date"], {"start": 1420, "end": 1430, "approximate": True}
        )
        self.assertEqual(self.uris(event), {AZURITE})
        self.assertCountEqual(
            event["analyses"],
            [str(self.analyses["open"].pk), str(self.analyses["on_document"].pk)],
        )
        self.assertEqual(event["component"]["id"], str(self.components["open"].pk))

    def test_an_alteration_carries_the_observed_material_it_names_with_its_reliability(
        self,
    ):
        [event] = self.events_of(self.bundle(), "alteration", self.alteration)
        [material] = event["materials"]
        self.assertEqual(
            (material["id"], material["characterization"]),
            (VERMILION, str(self.materials["vermilion"].pk)),
        )
        self.assertIsNotNone(material["reliability"])
        self.assertEqual(event["analyses"], [str(self.analyses["open"].pk)])

    def test_analyses_and_samples_are_not_events(self):
        bundle = self.bundle()
        self.assertEqual(
            {e["type"] for e in bundle.events},
            {"production", "modification", "alteration"},
        )
        for model in ("analysis", "sample"):
            self.assertFalse(
                [e for e in bundle.events if e["carrier"]["model"] == model]
            )

    def test_own_geometry_comes_first_and_a_derived_copy_is_ignored(self):
        bundle = self.bundle()
        [own] = self.events_of(bundle, "production", self.documents["own"])
        self.assertEqual(own["placeSource"], "own")
        self.assertEqual(own["place"], f"own:{OWN[0]:.4f},{OWN[1]:.4f}")
        place = bundle.event_places[own["place"]]
        self.assertEqual(
            (place["parent"], place["lngLat"], place["name"]["value"]),
            (str(self.places["paris"].pk), list(OWN), "Paris"),
        )
        [derived] = self.events_of(bundle, "production", self.documents["derived"])
        self.assertEqual(
            (derived["place"], derived["placeSource"]),
            (str(self.places["lyon"].pk), "place"),
        )
        self.assertEqual(
            derived["date"], {"start": None, "end": None, "approximate": False}
        )

    def test_places_hold_names_kinds_authorities_ancestors_and_drafts(self):
        places = self.bundle().event_places
        normandie = places[str(self.places["normandie"].pk)]
        self.assertEqual(
            (normandie["geometryKind"], normandie["parent"]),
            ("area", str(self.places["france"].pk)),
        )
        self.assertGreater(normandie["extentKm"], 50)
        self.assertTrue(places[str(self.places["france"].pk)]["unpublished"])
        self.assertEqual(
            places[str(self.places["paris"].pk)]["authorities"], {"geonames": "2988507"}
        )

    def test_a_hidden_place_cuts_the_chain(self):
        self.embargo(self.places["normandie"])
        [event] = self.events_of(self.bundle(), "modification", self.modification)
        self.assertEqual(
            (event["place"], event["placeSource"]), (str(self.places["abbey"].pk), None)
        )

    def test_a_hidden_place_is_never_a_place(self):
        unmapped = self.documents["unmapped"]
        [event] = self.events_of(self.bundle(), "production", unmapped)
        self.assertEqual(event["place"], str(self.places["hidden"].pk))
        self.embargo(self.places["hidden"])
        [event] = self.events_of(self.bundle(), "production", unmapped)
        self.assertIsNone(event["place"])

    def test_a_hidden_modification_leaves_its_material_to_the_production(self):
        self.embargo(self.modification)
        bundle = self.bundle()
        self.assertEqual(self.events_of(bundle, "modification", self.modification), [])
        [component] = self.events_of(bundle, "production", self.components["open"])
        self.assertEqual(self.uris(component), {LEAD_WHITE, AZURITE})

    def test_a_hidden_document_has_no_event(self):
        self.embargo(self.documents["open"])
        self.assertFalse(
            [
                e
                for e in self.bundle().events
                if e["document"]["id"] == str(self.documents["open"].pk)
            ]
        )

    def test_a_document_without_analysis_has_no_event_but_keeps_its_history(self):
        bundle = self.bundle()
        self.assertFalse(
            [
                e
                for e in bundle.events
                if e["document"]["id"] == str(self.documents["unanalysed"].pk)
            ]
        )
        [line] = bundle.histories[str(self.documents["unanalysed"].pk)]
        self.assertEqual([p["name"]["value"] for p in line["places"]], ["Paris"])

    def test_a_history_holds_the_production_of_its_document_only(self):
        [line] = self.bundle().histories[str(self.documents["open"].pk)]
        self.assertEqual(
            (line["type"], line["carrier"]["model"]), ("production", "document")
        )
        self.assertEqual(
            line["date"],
            {"start": "1401-01", "end": "1500-12", "approximate": True},
        )

    def test_materials_info_and_terms(self):
        bundle = self.bundle()
        self.assertEqual(bundle.event_materials[VERMILION]["colours"], [])
        self.assertIn("cinnabar", bundle.material_terms[VERMILION])
        self.assertEqual(
            bundle.event_materials[VERMILION]["label"]["value"], "Vermilion"
        )

    def test_every_event_has_the_public_keys_only(self):
        from manuspectrum.views.explorer.events import PUBLIC_KEYS

        for event in self.bundle().events:
            self.assertEqual(tuple(event), PUBLIC_KEYS)


class BoundsMeetTests(EventsCase):
    def test_the_period_rule_on_bounds(self):
        from django.http import QueryDict
        from manuspectrum.views.explorer.service import bounds_meet, parse_filters

        overlap, _ = parse_filters(QueryDict("period=1420,1425"))
        within, _ = parse_filters(QueryDict("period=1400,1500&periodMatch=within"))
        undated, _ = parse_filters(QueryDict("period=1400,1500&undated=1"))
        self.assertTrue(bounds_meet((1420, 1430), overlap))
        self.assertFalse(bounds_meet((1380, 1395), overlap))
        self.assertTrue(bounds_meet((1401, 1500), within))
        self.assertFalse(bounds_meet((1380, 1430), within))
        self.assertFalse(bounds_meet(None, within))
        self.assertTrue(bounds_meet(None, undated))


class MaterialColourTests(EventsCase):
    """Vermilion is cited by three alterations whose characterizations are red, red and green."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ref = cls.reference_value
        cls.tile(cls.materials["vermilion"], "color_aspect", ref(RED, "Red", "Rouge"))
        cls.observed_in = {str(cls.materials["vermilion"].pk): [RED]}
        for colour, label in ((RED, "Red"), (GREEN, "Green")):
            found = cls.characterized(
                f"Vermilion, {label}",
                cls.components["open"],
                cls.analyses["open"],
                VERMILION,
                LOW,
            )
            cls.tile(found, "color_aspect", ref(colour, label, label))
            cls.observed_in[str(found.pk)] = [colour]
            alteration = cls.new_resource("alteration", f"Fading {label}")
            cls.tile(alteration, "object_altered", cls.refs(cls.documents["open"]))
            cls.tile_values(
                alteration,
                "alteration",
                alteration_process_start_date="1650-01-01",
                alteration_process_end_date="1660-12-31",
            )
            cls.tile(
                alteration,
                "occured_in_presence_of_material",
                ref(VERMILION, "Vermilion"),
            )

    def test_a_material_lists_its_observed_colours_most_cited_first(self):
        material = self.bundle().event_materials[VERMILION]
        self.assertEqual(material["colours"], [RED, GREEN])

    def test_a_material_without_colour_has_none(self):
        self.assertEqual(self.bundle().event_materials[LEAD_WHITE]["colours"], [])

    def test_each_event_material_carries_its_own_characterization_colours(self):
        payload = self.client.get("/en/api/explorer/events").json()
        found = {
            m["characterization"]: m["colours"]
            for e in payload["events"]
            for m in e["materials"]
            if m["id"] == VERMILION
        }
        self.assertEqual(found, self.observed_in)
        self.assertTrue(
            all(
                m["colours"] == []
                for e in payload["events"]
                for m in e["materials"]
                if m["id"] == LEAD_WHITE
            )
        )

    def test_the_colour_map_holds_the_colours_the_materials_use_with_label_and_swatch(
        self,
    ):
        bundle = self.bundle()
        used = {c for m in bundle.event_materials.values() for c in m["colours"]}
        self.assertEqual(set(bundle.event_colours), used)
        self.assertEqual(bundle.event_colours[RED]["label"]["value"], "Red")
        self.assertEqual(bundle.event_colours[RED]["uri"], RED)
        self.assertIn("swatch", bundle.event_colours[RED])


class MaterialOwnColourTests(EventsCase):
    """Lead white is uncoloured and observed on a Component whose colour is blue."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tile(
            cls.components["open"],
            "color_features",
            cls.reference_value(PART_BLUE, "Blue", "Bleu"),
        )

    def test_a_material_never_takes_the_colours_of_the_component_it_is_observed_on(
        self,
    ):
        bundle = self.bundle()
        self.assertEqual(bundle.event_materials[LEAD_WHITE]["colours"], [])
        self.assertIsNone(bundle.event_materials[LEAD_WHITE]["swatch"])
        self.assertNotIn(PART_BLUE, bundle.event_colours)

    def test_the_corpus_filter_still_matches_the_component_colour(self):
        from django.http import QueryDict
        from manuspectrum.views.explorer.events import kept_events

        bundle = self.bundle()
        events, *_ = kept_events(bundle, QueryDict(f"colour={PART_BLUE}"))
        [event] = [
            e
            for e in events
            if e["type"] == "production"
            and e["carrier"]["id"] == str(self.components["open"].pk)
        ]
        self.assertIn(LEAD_WHITE, {m["id"] for m in event["materials"]})
        self.assertEqual(bundle.event_materials[LEAD_WHITE]["colours"], [])

    def test_a_ticked_colour_reached_through_the_component_is_named_on_the_material(
        self,
    ):
        from django.http import QueryDict
        from manuspectrum.views.explorer.events import kept_events

        bundle = self.bundle()
        ticked, *_ = kept_events(bundle, QueryDict(f"colour={PART_BLUE},{RED}"))
        [event] = [
            e
            for e in ticked
            if e["type"] == "production"
            and e["carrier"]["id"] == str(self.components["open"].pk)
        ]
        [lead] = [m for m in event["materials"] if m["id"] == LEAD_WHITE]
        self.assertEqual(lead["componentColours"], [PART_BLUE])
        untouched, *_ = kept_events(bundle, QueryDict(""))
        self.assertTrue(
            all(not m["componentColours"] for e in untouched for m in e["materials"])
        )

    def test_a_ticked_colour_no_material_carries_is_named_in_the_colours(self):
        payload = self.client.get(
            f"/en/api/explorer/events?colour={PART_BLUE},http://vocab/unknown"
        ).json()
        self.assertEqual(payload["colours"][PART_BLUE]["label"]["value"], "Blue")
        self.assertEqual(payload["colours"][PART_BLUE]["uri"], PART_BLUE)
        self.assertNotIn("http://vocab/unknown", payload["colours"])


class CharacterizationFilterTests(EventsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ref = cls.reference_value
        cls.tile(cls.materials["lead"], "color_aspect", ref(RED, "Red", "Rouge"))
        cls.ochre = cls.characterized(
            "Ochre", cls.components["open"], cls.analyses["open"], OCHRE, LOW
        )
        cls.tile(cls.ochre, "color_aspect", ref(GREEN, "Green", "Vert"))

    def kept(self, query):
        from django.http import QueryDict
        from manuspectrum.views.explorer.events import kept_events

        events, *_ = kept_events(self.bundle(), QueryDict(query))
        return [
            e for e in events if e["carrier"]["id"] == str(self.components["open"].pk)
        ]

    def test_ticking_a_material_keeps_the_materials_found_beside_it(self):
        self.assertEqual(
            {m["id"] for m in self.kept("")[0]["materials"]}, {LEAD_WHITE, OCHRE}
        )
        [event] = self.kept(f"material={OCHRE}")
        self.assertEqual({m["id"] for m in event["materials"]}, {LEAD_WHITE, OCHRE})

    def test_ticking_a_colour_keeps_the_materials_found_beside_it(self):
        for query in (f"colour={RED}", f"material={OCHRE}&colour={GREEN}"):
            with self.subTest(query=query):
                [event] = self.kept(query)
                self.assertEqual(
                    {m["id"] for m in event["materials"]}, {LEAD_WHITE, OCHRE}
                )

    def test_a_colour_no_material_of_the_event_meets_drops_the_event(self):
        self.assertEqual(self.kept(f"material={OCHRE}&colour={RED}"), [])

    def matches(self, query):
        [event] = self.kept(query)
        return {m["id"]: m["matches"] for m in event["materials"]}

    def test_each_listed_material_says_whether_it_meets_every_filter(self):
        self.assertEqual(self.matches(""), {LEAD_WHITE: True, OCHRE: True})
        self.assertEqual(
            self.matches(f"colour={RED}"), {LEAD_WHITE: True, OCHRE: False}
        )
        self.assertEqual(
            self.matches(f"material={OCHRE}&colour={GREEN}"),
            {LEAD_WHITE: False, OCHRE: True},
        )

    def test_the_exports_keep_only_the_materials_that_meet_the_filters(self):
        import csv
        import json

        query = f"lang=en&colour={RED}"
        response = self.client.get(f"/api/explorer/events.csv?{query}")
        lines = b"".join(response.streaming_content).decode().splitlines()
        rows = list(csv.DictReader(l for l in lines if not l.startswith("#")))
        self.assertEqual({r["material"] for r in rows}, {LEAD_WHITE})
        response = self.client.get(f"/api/explorer/events.geojson?{query}")
        body = json.loads(b"".join(response.streaming_content))
        materials = [m for f in body["features"] for m in f["properties"]["materials"]]
        self.assertEqual({m["id"] for m in materials}, {LEAD_WHITE})
        self.assertFalse(any("matches" in m for m in materials))


class OwnPlaceTests(EventsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.alone = (3.1, 47.1)
        cls.shared = (3.2, 47.2)
        cls.carriers = {
            "drafts": [
                cls.carrier("Draft A", cls.alone),
                cls.carrier("Draft B", cls.alone),
            ],
            "mixed": [
                cls.carrier("Draft C", cls.shared),
                cls.carrier("Active D", cls.shared, ACTIVE),
            ],
        }

    @classmethod
    def carrier(cls, name, lng_lat, state=DRAFT):
        document = cls.new_resource("document", name, state=state)
        cls.tile_values(
            document,
            "document",
            date_start_of_production_time="1250-01-01",
            date_end_of_production_time="1260-12-31",
            literal_location_of_production=collection(point(lng_lat)),
        )
        analysis = cls.new_resource("analysis", f"X — {name}")
        cls.tile(analysis, "component_observed", cls.refs(document))
        return document

    def place(self, lng_lat):
        return self.bundle().event_places[f"own:{lng_lat[0]:.4f},{lng_lat[1]:.4f}"]

    def test_an_own_place_is_unpublished_only_when_every_carrier_merged_into_it_is(
        self,
    ):
        self.assertTrue(self.place(self.alone)["unpublished"])
        self.assertFalse(self.place(self.shared)["unpublished"])


class OwnPlaceNameTests(EventsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.near = (2.36, 48.87)
        cls.far = (-1.51, 48.64)
        for name, lng_lat in (("Ms Near", cls.near), ("Ms Far", cls.far)):
            cls.produced(name, cls.places["paris"], collection(point(lng_lat)), True)

    def place(self, lng_lat):
        return self.bundle().event_places[f"own:{lng_lat[0]:.4f},{lng_lat[1]:.4f}"]

    def test_an_own_point_within_the_linked_place_takes_its_name(self):
        place = self.place(self.near)
        self.assertEqual(place["name"]["value"], "Paris")
        self.assertEqual(place["parent"], str(self.places["paris"].pk))

    def test_an_own_point_far_from_the_linked_place_takes_the_carrier_name(self):
        place = self.place(self.far)
        self.assertEqual(place["name"]["value"], "Ms Far")
        self.assertEqual(place["parent"], str(self.places["paris"].pk))
