"""Shapes of the v3 annotation documents, against the pinned IIIF schema and the language-map rules.

Usage:
    python manage.py test tests.test_iiif_shapes --settings=tests.test_settings
"""

from django.test import Client

from arches.app.models.models import ResourceInstance

from manuspectrum.iiif import ids
from tests.explorer_fixtures import FEATURES, IIIFCase
from tests.iiif_schema import assert_valid_iiif

LANGUAGE_MAP_KEYS = ("label", "summary")


def language_maps(node, path=""):
    """``(path, value)`` of every ``label``/``summary`` and every metadata label/value in *node*."""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from language_maps(item, f"{path}/{i}")
    elif isinstance(node, dict):
        for key, value in node.items():
            if key in LANGUAGE_MAP_KEYS or (
                key == "value" and "label" in node and "type" not in node
            ):
                yield f"{path}/{key}", value
            if key != "value" or not isinstance(value, dict):
                yield from language_maps(value, f"{path}/{key}")


def all_values(node, key):
    if isinstance(node, list):
        for item in node:
            yield from all_values(item, key)
    elif isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from all_values(v, key)


class ShapeCase(IIIFCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        analysis = cls.analyses["open"]
        cls.tile(
            analysis,
            "analysis_technique_used",
            cls.reference_value(
                "http://vocab.getty.edu/aat/300379594",
                "X-ray fluorescence",
                "Fluorescence X",
            )
            + cls.reference_value(
                "http://vocab.getty.edu/aat/300054238", "Raman", "Raman (fr)"
            ),
        )
        cls.second_operator = cls.new_resource("person", "Heu, S.")
        cls.tile(
            analysis,
            "performed_by_actor",
            cls.refs(cls.operator, cls.second_operator),
        )
        cls.tile(
            analysis,
            "dataset_url",
            {"url": "https://doi.org/10.12763/ABCDEF", "url_label": "HEU (2024)"},
        )
        cls.tile_values(
            analysis,
            "analysis",
            analysis_start_date="2024-03-12",
            analysis_end_date="2024-03-14",
        )

    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.file_id = self.stored_file(
            self.analyses["open"], "X01_f1v.csv", b"x,y\n1,2\n3,4\n"
        )
        self.raw_id = self.stored_file(
            self.analyses["open"], "X01_f1v.mca", b"\x00\x01"
        )

    def page(self, n=1):
        doc = self.documents["open"].pk
        return self.visitor.get(f"/iiif/v3/annotation-collection/{doc}/page-{n}").json()

    def annotation_of(self, key, page=None):
        wanted = ids.annotation(self.analyses[key].pk, FEATURES[key])
        return next(a for a in (page or self.page())["items"] if a["id"] == wanted)


class SchemaTests(ShapeCase):
    def test_the_v3_page_is_valid(self):
        for n in (1, 2, 3):
            with self.subTest(n=n):
                assert_valid_iiif(self, self.page(n))

    def test_the_v3_collection_has_no_items_and_is_valid(self):
        doc = self.documents["open"].pk
        collection = self.visitor.get(f"/iiif/v3/annotation-collection/{doc}").json()

        self.assertNotIn("items", collection)
        assert_valid_iiif(self, collection)

    def test_a_single_annotation_is_valid(self):
        for key in ("open", "on_document_3", "draft"):
            analysis = key.split("_3")[0]
            response = self.visitor.get(
                f"/iiif/v3/annotation/{self.analyses[analysis].pk}/{FEATURES[key]}"
            )
            with self.subTest(key=key):
                self.assertEqual(response.status_code, 200)
                assert_valid_iiif(self, response.json())

    def test_part_of_is_an_array_and_next_prev_are_references(self):
        page = self.page(2)

        self.assertIsInstance(page["partOf"], list)
        self.assertEqual(page["partOf"][0]["type"], "AnnotationCollection")
        for key in ("next", "prev"):
            self.assertEqual(set(page[key]), {"id", "type"})
            self.assertEqual(page[key]["type"], "AnnotationPage")


class LanguageTests(ShapeCase):
    def test_every_label_and_metadata_value_is_a_language_map(self):
        for path, value in language_maps(self.page()):
            with self.subTest(path=path):
                self.assertIsInstance(value, dict)
                for key, texts in value.items():
                    self.assertIsInstance(texts, list)
                    self.assertTrue(all(isinstance(t, str) for t in texts))

    def test_interface_labels_carry_every_configured_language(self):
        page = self.page()
        metadata = self.annotation_of("open", page)["metadata"]

        self.assertEqual(set(page["label"]), {"en", "fr"})
        self.assertIn(
            {"en": ["Operators"], "fr": ["Opérateurs"]}, [m["label"] for m in metadata]
        )

    def test_no_text_is_tagged_with_a_language_it_was_not_stored_in(self):
        ResourceInstance.objects.filter(pk=self.analyses["open"].pk).update(
            descriptors={"fr": {"name": "X01 — f. 1v (fr)"}, "en": {"name": ""}}
        )

        annotation = self.annotation_of("open")

        self.assertEqual(annotation["label"], {"fr": ["X01 — f. 1v (fr)"]})

    def test_names_without_descriptors_keep_the_languages_of_their_tile(self):
        self.assertEqual(self.annotation_of("open")["label"], {"en": ["X01 — f. 1v"]})

    def test_multi_valued_metadata_is_one_string_per_language(self):
        metadata = {
            m["label"]["en"][0]: m["value"]
            for m in self.annotation_of("open")["metadata"]
        }

        self.assertEqual(
            metadata["Technique"],
            {"en": ["X-ray fluorescence, Raman"], "fr": ["Fluorescence X, Raman (fr)"]},
        )
        self.assertEqual(metadata["Operators"], {"none": ["Robinet, L., Heu, S."]})
        self.assertEqual(metadata["Dates"], {"none": ["2024-03-12 – 2024-03-14"]})
        self.assertEqual(metadata["Project"], {"none": ["EMMA"]})
        self.assertEqual(metadata["Component"], {"en": ["f. 1v — initial"]})
        self.assertEqual(metadata["Document"], {"en": ["Ms 59"]})

    def test_a_draft_analysis_says_so(self):
        status = [
            m
            for m in self.annotation_of("draft")["metadata"]
            if m["label"]["en"] == ["Status"]
        ]

        self.assertEqual(len(status), 1)
        self.assertEqual(set(status[0]["value"]), {"en", "fr"})
        self.assertEqual(status[0]["value"]["en"], ["Draft"])
        self.assertNotIn(
            ["Status"],
            [m["label"]["en"] for m in self.annotation_of("open")["metadata"]],
        )


class LinkTests(ShapeCase):
    def test_the_doi_see_also_has_a_string_id(self):
        see_also = self.annotation_of("open")["seeAlso"]
        doi = next(link for link in see_also if "doi.org" in link["id"])

        self.assertEqual(
            doi,
            {
                "id": "https://doi.org/10.12763/ABCDEF",
                "type": "Text",
                "format": "text/html",
                "label": {"none": ["HEU (2024)"]},
            },
        )

    def test_the_report_is_the_first_see_also(self):
        report = self.annotation_of("open")["seeAlso"][0]

        self.assertEqual(report["id"], ids.report(self.analyses["open"].pk))
        self.assertEqual(report["format"], "text/html")

    def test_every_file_is_a_body_with_its_true_format(self):
        bodies = {b["id"]: b for b in self.annotation_of("open")["body"]}

        self.assertEqual(bodies[ids.data_raw(self.file_id)]["format"], "text/csv")
        self.assertEqual(
            bodies[ids.data_raw(self.raw_id)]["format"], "application/octet-stream"
        )
        self.assertEqual(
            bodies[ids.data_raw(self.file_id)]["label"]["en"], ["X01_f1v.csv, raw file"]
        )

    def test_the_raw_files_are_in_see_also(self):
        see_also = [link["id"] for link in self.annotation_of("open")["seeAlso"]]

        self.assertIn(ids.data_raw(self.file_id), see_also)
        self.assertIn(ids.data_raw(self.raw_id), see_also)

    def test_no_format_is_text_txt_or_empty(self):
        for fmt in all_values(self.page(), "format"):
            with self.subTest(fmt=fmt):
                self.assertTrue(fmt)
                self.assertNotEqual(fmt, "text/txt")

    def test_a_licence_outside_the_registries_is_a_required_statement(self):
        custom = self.stored_file(
            self.analyses["open"],
            "notes.txt",
            b"n",
            licence={"id": "LicenseRef-custom", "label": "All rights reserved"},
        )
        body = next(
            b
            for b in self.annotation_of("open")["body"]
            if b["id"] == ids.data_raw(custom)
        )

        self.assertNotIn("rights", body)
        self.assertEqual(
            body["requiredStatement"]["value"], {"none": ["All rights reserved"]}
        )
        self.assertEqual(body["format"], "text/plain")

    def test_a_registry_licence_is_rights(self):
        body = next(
            b
            for b in self.annotation_of("open")["body"]
            if b["id"] == ids.data_raw(self.file_id)
        )

        self.assertTrue(body["rights"].startswith("http://creativecommons.org/"))
