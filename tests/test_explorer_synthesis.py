"""``GET /{lang}/api/explorer/synthesis?ids=``: the Compare tools' synthesis of a Selection.

Usage:
    python manage.py test tests.test_explorer_synthesis --settings="tests.test_settings"
"""

import copy
from unittest import mock
from uuid import NAMESPACE_URL, uuid5

from django.test import override_settings

from arches_controlled_lists.models import List, ListItem

from tests.explorer_contract import assert_shape
from tests.explorer_fixtures import (
    CANVAS,
    CANVAS_3,
    FETCH,
    MANIFEST,
    SOURCE_MANIFEST,
    IIIFCase,
)

XRF, FORS = "http://vocab/pxrf", "http://vocab/fors"
AZURITE, CHALK, BLUE = (
    "http://vocab/azurite",
    "http://vocab/chalk",
    "http://vocab/blue",
)
HIGHLY, RELIABLE = "http://vocab/highly-reliable", "http://vocab/reliable"
MAJOR, TRACE = "http://vocab/major", "http://vocab/trace"
COPPER, LEAD = "http://vocab/copper", "http://vocab/lead"
MANIFEST_2 = "https://example.org/iiif/ms211/manifest"
CANVAS_B = "https://example.org/iiif/ms211/canvas/f1r"
SOURCE_2 = {
    **copy.deepcopy(SOURCE_MANIFEST),
    "id": MANIFEST_2,
    "items": [
        {
            "id": CANVAS_B,
            "type": "Canvas",
            "label": {"none": ["f. 1r"]},
            "width": 4000,
            "height": 5000,
        }
    ],
}
POINT = {"type": "Point", "coordinates": [10, -20]}


def item_id(uri):
    return str(uuid5(NAMESPACE_URL, uri))


class SynthesisCase(IIIFCase):
    """The IIIFCase corpus with techniques and two identified materials citing its analyses.

    ``characterization`` (Azurite, blue, reliable; Cu major) cites ``open``
    and ``on_document`` and is placed by its own zone on f. 3r; ``second``
    (Azurite, blue, highly reliable; Cu trace, Pb without symbol) cites
    ``on_document`` only and places nothing; ``chalk`` (no colour, no
    certainty) cites ``draft`` and observes the open Document.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for name, uris in (
            ("confidence", (HIGHLY, RELIABLE)),
            ("level", (MAJOR, TRACE)),
        ):
            vocab = List.objects.create(name=name)
            for order, uri in enumerate(uris):
                ListItem.objects.create(
                    id=item_id(uri), list=vocab, uri=uri, sortorder=order
                )
        ref = cls.reference_value
        for key, uri in (("open", XRF), ("on_document", FORS), ("draft", XRF)):
            cls.tile(cls.analyses[key], "analysis_technique_used", ref(uri, f"T {uri}"))
        cls.tile(
            cls.analyses["embargoed"], "analysis_technique_used", ref(XRF, "T xrf")
        )
        cls.second = cls.new_resource("characterization", "Azurite, second")
        cls.chalk = cls.new_resource("characterization", "Chalk")
        cls.tile(cls.second, "evidence_analyses", cls.refs(cls.analyses["on_document"]))
        cls.tile(cls.second, "object_observed", cls.refs(cls.documents["open"]))
        cls.tile(cls.chalk, "object_observed", cls.refs(cls.documents["open"]))
        cls.tile(cls.chalk, "evidence_analyses", cls.refs(cls.analyses["draft"]))
        copper = ref(COPPER, "Copper", "Cuivre", alt="Cu")
        cls.describe(cls.characterization, AZURITE, RELIABLE, BLUE, [(copper, MAJOR)])
        cls.describe(
            cls.second,
            AZURITE,
            HIGHLY,
            BLUE,
            [(copper, TRACE), (ref(LEAD, "Lead", "Plomb"), TRACE)],
        )
        cls.describe(cls.chalk, CHALK, None, None, [])
        cls.tile(
            cls.characterization,
            "location_of_characterization",
            cls.annotation_value(CANVAS_3, POINT),
        )

    @classmethod
    def describe(cls, characterization, material, confidence, colour, elements):
        ref = cls.reference_value
        values = {"identified_material": ref(material, material.rsplit("/", 1)[1])}
        if confidence:
            values["material_confidence"] = ref(confidence, confidence)
        cls.tile_values(characterization, "characterization", **values)
        if colour:
            cls.tile(characterization, "color_aspect", ref(colour, "Blue", "Bleu"))
        for value, level in elements:
            cls.tile_values(
                characterization,
                "characterization",
                detected_elements=value,
                element_level=ref(level, level),
            )

    def get(self, keys, **headers):
        return self.client.get(
            "/en/api/explorer/synthesis", {"ids": ",".join(keys)}, **headers
        )

    def payload(self, keys):
        response = self.get(keys)
        self.assertEqual(response.status_code, 200, keys)
        return response.json()

    def an(self, key):
        return f"an:{self.analyses[key].pk}:-"


class SynthesisShapeTests(SynthesisCase):
    def test_the_payload_follows_the_contract(self):
        payload = self.payload([self.an("open"), self.an("on_document")])

        assert_shape(self, payload, "SynthesisResponse")
        for row in payload["coverage"]:
            assert_shape(self, row, "SynthesisCoverage")
        for technique in payload["techniques"]:
            assert_shape(self, technique, "Technique")
        for pair in payload["pairs"]:
            assert_shape(self, pair, "SynthesisPair")
            for element in pair["elements"]:
                assert_shape(self, element, "SynthesisElementRef")
        for element in payload["elements"]:
            assert_shape(self, element, "SynthesisElement")
        self.assertTrue(payload["coverage"] and payload["pairs"])


class CoverageTests(SynthesisCase):
    def test_counts_analyses_per_canvas_and_technique_on_placed_canvases_only(self):
        payload = self.payload(
            [self.an("open"), self.an("on_document"), self.an("draft")]
        )

        self.assertEqual(
            payload["coverage"],
            [
                {
                    "canvas": CANVAS,
                    "label": "f. 1v",
                    "counts": {item_id(XRF): 2, item_id(FORS): 1},
                },
                {"canvas": CANVAS_3, "label": "f. 3r", "counts": {item_id(FORS): 1}},
            ],
        )
        self.assertEqual(
            [t["id"] for t in payload["techniques"]], [item_id(FORS), item_id(XRF)]
        )
        self.assertEqual(payload["unpublishedCount"], 1)

    def test_a_file_key_counts_its_analysis_once(self):
        key = f"af:{self.analyses['open'].pk}:11111111-1111-4111-8111-111111111111"

        payload = self.payload([key, self.an("open")])

        self.assertEqual(payload["coverage"][0]["counts"], {item_id(XRF): 1})

    def test_a_canvas_carrying_only_an_identified_material_is_not_a_row(self):
        payload = self.payload([f"ch:{self.characterization.pk}:-"])

        self.assertEqual((payload["coverage"], payload["techniques"]), ([], []))
        self.assertEqual(payload["pairs"][0]["canvases"], [CANVAS_3])

    @override_settings(EXPLORER_MANIFEST_MAX_CANVASES=1)
    def test_the_manifest_canvas_bound_does_not_limit_the_synthesis(self):
        payload = self.payload([self.an("on_document")])

        self.assertEqual([r["canvas"] for r in payload["coverage"]], [CANVAS, CANVAS_3])

    def test_canvases_of_several_documents_are_named_with_their_document(self):
        self.tile(self.documents["embargoed"], "facsimiles", MANIFEST_2)
        self.zone(
            self.analyses["embargoed"],
            [("0a0a0a0a-0000-4000-8000-00000000000b", CANVAS_B, POINT)],
        )
        sources = {MANIFEST: SOURCE_MANIFEST, MANIFEST_2: SOURCE_2}

        with mock.patch(FETCH, side_effect=sources.get):
            payload = self.payload([self.an("open"), self.an("embargoed")])

        self.assertEqual(
            [(r["canvas"], r["label"]) for r in payload["coverage"]],
            [(CANVAS_B, "Ms 211 — f. 1r"), (CANVAS, "Ms 59 — f. 1v")],
        )


class PairsAndElementsTests(SynthesisCase):
    def test_materials_citing_a_selected_analysis_count_without_their_key(self):
        payload = self.payload([self.an("open")])

        self.assertEqual(len(payload["pairs"]), 1)
        pair = payload["pairs"][0]
        self.assertEqual(
            (pair["colour"]["uri"], pair["material"]["uri"], pair["count"]),
            (BLUE, AZURITE, 1),
        )
        self.assertEqual(pair["canvases"], [CANVAS_3])
        self.assertEqual(
            (pair["confidenceBest"]["uri"], pair["confidenceBest"]["rank"]),
            (RELIABLE, 1),
        )
        self.assertEqual(
            [(e["uri"], e["symbol"]) for e in pair["elements"]], [(COPPER, "Cu")]
        )
        self.assertEqual(
            [(e["symbol"], e["level"]["uri"], e["count"]) for e in payload["elements"]],
            [("Cu", MAJOR, 1)],
        )

    def test_one_pair_gathers_its_materials_with_the_best_confidence_and_level(self):
        payload = self.payload([self.an("open"), self.an("on_document")])

        pair = payload["pairs"][0]
        self.assertEqual(len(payload["pairs"]), 1)
        self.assertEqual(pair["count"], 2)
        self.assertEqual(pair["confidenceBest"]["uri"], HIGHLY)
        self.assertEqual(pair["canvases"], [CANVAS_3])
        self.assertEqual(
            [(e["uri"], e["symbol"]) for e in pair["elements"]],
            [(COPPER, "Cu"), (LEAD, None)],
        )
        self.assertEqual(
            [(e["symbol"], e["level"]["uri"], e["count"]) for e in payload["elements"]],
            [("Cu", MAJOR, 2)],
        )

    def test_a_material_without_colour_or_confidence_pairs_with_null(self):
        payload = self.payload([f"ch:{self.chalk.pk}:-"])

        self.assertEqual(
            [
                (p["colour"], p["material"]["uri"], p["confidenceBest"], p["count"])
                for p in payload["pairs"]
            ],
            [(None, CHALK, None, 1)],
        )
        self.assertEqual(payload["elements"], [])


class SynthesisPermissionTests(SynthesisCase):
    def test_a_hidden_identified_material_contributes_nothing(self):
        self.embargo(self.characterization)

        payload = self.payload([self.an("open"), f"ch:{self.chalk.pk}:-"])

        self.assertEqual([p["material"]["uri"] for p in payload["pairs"]], [CHALK])
        self.assertNotIn("Cu", str(payload["elements"]))

    def test_a_hidden_analysis_contributes_nothing_and_alone_answers_404(self):
        self.embargo(self.analyses["on_document"])

        payload = self.payload([self.an("open"), self.an("on_document")])
        alone = self.get([self.an("on_document")])

        self.assertEqual(
            payload["coverage"],
            [{"canvas": CANVAS, "label": "f. 1v", "counts": {item_id(XRF): 1}}],
        )
        self.assertEqual(payload["pairs"][0]["count"], 1)
        self.assertEqual((alone.status_code, alone.content), (404, b""))

    def test_a_signed_in_reader_gets_the_visitor_view_of_a_restricted_nodegroup(self):
        nodegroup = self.nodes[("characterization", "identified_material")].nodegroup_id
        self.restrict_nodegroup(nodegroup, self.editor)
        self.client.force_login(self.editor)

        payload = self.payload([self.an("open")])

        self.assertEqual(payload["pairs"], [])
        self.assertEqual(payload["elements"][0]["symbol"], "Cu")


class SynthesisRouteTests(SynthesisCase):
    def test_the_visitor_gets_a_public_answer_revalidated_with_a_304(self):
        response = self.get([self.an("open")])
        again = self.get([self.an("open")], HTTP_IF_NONE_MATCH=response["ETag"])

        self.assertEqual(response["Cache-Control"], "public, no-cache")
        self.assertEqual(again.status_code, 304)

    def test_a_signed_in_reader_gets_a_private_answer_without_etag(self):
        self.client.force_login(self.editor)

        response = self.get([self.an("open")])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", response)

    def test_more_than_thirty_keys_no_key_or_a_malformed_key_is_a_bodyless_400(self):
        keys = [f"ch:{i:08d}-0000-4000-8000-000000000000:-" for i in range(31)]

        for response in (
            self.get(keys),
            self.client.get("/en/api/explorer/synthesis"),
            self.get(["nonsense"]),
            self.client.get(
                "/en/api/explorer/synthesis", {"document": self.documents["open"].pk}
            ),
        ):
            self.assertEqual((response.status_code, response.content), (400, b""))

    def test_a_selection_with_nothing_visible_is_a_bodyless_404(self):
        response = self.get(["an:00000000-0000-4000-8000-00000000000a:-"])

        self.assertEqual((response.status_code, response.content), (404, b""))
        self.assertEqual(response["Cache-Control"], "private, no-store")
