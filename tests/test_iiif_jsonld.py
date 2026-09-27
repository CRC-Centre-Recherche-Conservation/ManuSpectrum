"""The xy-reading JSON-LD context (C5): its terms, their expansion, and its routes.

Usage:
    python manage.py test tests.test_iiif_jsonld --settings=tests.test_settings
"""

import json

from django.test import RequestFactory, SimpleTestCase, TestCase

from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.iiif import ids, v2, xy_reading
from manuspectrum.iiif.pages import with_context
from manuspectrum.views.iiif.context import XYReadingDocView
from tests import iiif_jsonld
from tests.test_iiif_xy_reading import SCHEMA, raw_file

NS = ids.xy_context().removesuffix(".jsonld") + "#"
PREFIXES = {"@version", "ms_xy", "csvw", "prov", "xsd"}


def body(reading):
    """A Dataset body under our context; ``type``/``id`` stand in for the Presentation 3 aliases."""
    return {
        "@context": [ids.xy_context(), {"type": "@type", "id": "@id"}],
        "id": "https://ms.example/iiif/data/f/series.csv",
        "type": "Dataset",
        "xyReading": reading,
    }


class ContextTests(SimpleTestCase):
    def test_the_context_is_json_ld_1_1_and_only_defines_xy_reading_at_top_level(self):
        context = xy_reading.context_document()["@context"]

        self.assertEqual(context["@version"], 1.1)
        self.assertEqual(set(context) - PREFIXES, {"xyReading"})
        self.assertEqual(context["ms_xy"], NS)
        self.assertIn("@context", context["xyReading"])

    def test_no_presentation_3_term_is_redefined(self):
        ours = xy_reading.context_document()["@context"]
        theirs = iiif_jsonld.presentation_3_terms()

        for term in set(ours) & set(theirs) - {"@version"}:
            with self.subTest(term=term):
                self.assertEqual(ours[term], theirs[term])

    def test_xy_reading_and_its_keys_expand_to_the_extension_namespace(self):
        reading = xy_reading.xy_reading(raw_file(), XY_PRESETS["fors"]["config"])

        (node,) = iiif_jsonld.expand(body(reading))

        (extension,) = node[NS + "xyReading"]
        self.assertEqual(extension["@type"], [NS + "XYReading"])
        self.assertIn(NS + "column", extension)
        self.assertIn(NS + "xAxis", extension)
        self.assertIn("http://www.w3.org/ns/csvw#dialect", extension)
        (derived,) = extension["http://www.w3.org/ns/prov#wasDerivedFrom"]
        (raw,) = derived[NS + "xyReading"]
        (correction,) = raw[NS + "correction"][0]["@list"]
        self.assertEqual(
            correction[NS + "epsilon"],
            [{"@value": 1e-12, "@type": "http://www.w3.org/2001/XMLSchema#double"}],
        )

    def test_role_values_expand_to_vocabulary_iris(self):
        reading = xy_reading.xy_reading(raw_file(), XY_PRESETS["fors"]["config"])

        (node,) = iiif_jsonld.expand(body(reading))

        columns = node[NS + "xyReading"][0][NS + "column"][0]["@list"]
        self.assertEqual(
            [c[NS + "role"] for c in columns],
            [[{"@id": NS + "x"}], [{"@id": NS + "yLeft"}]],
        )

    def test_the_schema_is_draft_7(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(schema["$schema"], "http://json-schema.org/draft-07/schema#")


OA = "http://www.w3.org/ns/oa#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
PROV = "http://www.w3.org/ns/prov#wasDerivedFrom"


def annotation():
    """A v3 annotation holding a Dataset body with its ``xyReading`` and a concept body."""
    reading = xy_reading.xy_reading(raw_file(), XY_PRESETS["fors"]["config"])
    return with_context(
        {
            "id": ids.annotation("a1", "f1"),
            "type": "Annotation",
            "motivation": "supplementing",
            "body": [
                {
                    "id": ids.data_series("f"),
                    "type": "Dataset",
                    "format": "text/csv",
                    "xyReading": reading,
                },
                {
                    "type": "SpecificResource",
                    "purpose": "classifying",
                    "source": {
                        "id": "http://vocab.getty.edu/aat/300013526",
                        "label": {"en": ["vermilion"]},
                    },
                },
            ],
            "target": "https://ms.example/canvas/1",
        }
    )


class DocumentExpansionTests(SimpleTestCase):
    def assert_reading_survives(self, extension):
        self.assertEqual(extension["@type"], [NS + "XYReading"])
        (axis,) = extension[NS + "xAxis"]
        self.assertIn({"@value": "Wavelength (nm)"}, axis[RDFS_LABEL])
        (derived,) = extension[PROV]
        self.assertEqual(derived["@id"], ids.data_raw(raw_file().id))
        self.assertEqual(derived["@type"], ["http://purl.org/dc/dcmitype/Dataset"])
        self.assertIn(
            {"@value": "S.csv, raw file", "@language": "en"}, derived[RDFS_LABEL]
        )

    def test_a_v3_annotation_expands_under_ours_and_presentation_3(self):
        document = annotation()
        self.assertEqual(
            document["@context"], [ids.xy_context(), iiif_jsonld.PRESENTATION_3]
        )

        (node,) = iiif_jsonld.expand_presentation(document)

        dataset = next(b for b in node[OA + "hasBody"] if NS + "xyReading" in b)
        (extension,) = dataset[NS + "xyReading"]
        self.assert_reading_survives(extension)

    def test_a_v2_annotation_expands_under_ours_and_presentation_2(self):
        document = v2.annotation(annotation())
        self.assertEqual(
            document["@context"], [ids.xy_context(), iiif_jsonld.PRESENTATION_2]
        )

        (node,) = iiif_jsonld.expand_v2(document)

        resources = node["http://www.w3.org/ns/oa#hasBody"]
        dataset = next(r for r in resources if NS + "xyReading" in r)
        (extension,) = dataset[NS + "xyReading"]
        self.assert_reading_survives(extension)
        concept = next(r for r in resources if OA + "hasPurpose" in r)
        self.assertEqual(concept[OA + "hasPurpose"], [{"@id": OA + "classifying"}])


class RouteTests(TestCase):
    def test_the_context_is_served_as_ld_json_with_cors_and_a_long_cache(self):
        response = self.client.get("/iiif/context/xy-reading/1.jsonld")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/ld+json")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertEqual(response["Cache-Control"], "public, max-age=86400")
        self.assertEqual(response.json(), xy_reading.context_document())

    def test_the_schema_is_served_verbatim(self):
        response = self.client.get("/iiif/context/xy-reading/1/schema.json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/schema+json")
        self.assertEqual(response.content, SCHEMA.read_bytes())
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_the_documentation_page_renders_in_english_and_french(self):
        english = self.client.get(
            "/iiif/context/xy-reading/1", HTTP_ACCEPT_LANGUAGE="en"
        )
        french = self.client.get(
            "/iiif/context/xy-reading/1", HTTP_ACCEPT_LANGUAGE="fr"
        )

        for response, language in ((english, "en"), (french, "fr")):
            with self.subTest(language=language):
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Type"].startswith("text/html"))
                self.assertIn(f'<html lang="{language}"', response.content.decode())
                self.assertIn("accept-language", response["Vary"].lower())
                self.assertIn("cookie", response["Vary"].lower())
                self.assertIn(ids.xy_schema(), response.content.decode())
        self.assertNotEqual(english.content, french.content)

    def test_the_documentation_page_explains_iiif_auth_and_its_limits(self):
        english = self.client.get(
            "/iiif/context/xy-reading/1", HTTP_ACCEPT_LANGUAGE="en"
        ).content.decode()
        french = self.client.get(
            "/iiif/context/xy-reading/1", HTTP_ACCEPT_LANGUAGE="fr"
        ).content.decode()

        for url in (ids.auth_login(), ids.auth_token(1), ids.auth_token(2)):
            with self.subTest(url=url):
                self.assertIn(url, english)
        self.assertIn(ids.auth_logout(), english)
        for text in ("HTTPS", "Safari", "Firefox", "SameSite=Strict"):
            with self.subTest(text=text):
                self.assertIn(text, english)
        self.assertIn('id="auth-limits"', english)
        self.assertIn("Limites connues", french)
        self.assertIn("Données restreintes", french)

    def test_the_documentation_page_varies_on_the_language_cookie(self):
        request = RequestFactory().get("/iiif/context/xy-reading/1")

        response = XYReadingDocView.as_view()(request)

        self.assertIn("cookie", response["Vary"].lower())
        self.assertIn("accept-language", response["Vary"].lower())

    def test_the_documentation_page_names_the_auth_2_context_position(self):
        page = self.client.get(
            "/iiif/context/xy-reading/1", HTTP_ACCEPT_LANGUAGE="en"
        ).content.decode()

        self.assertIn("http://iiif.io/api/auth/2/context.json", page)

    def test_the_namespace_names_the_documentation_page(self):
        self.assertEqual(NS, ids.xy_doc() + "#")
        page = self.client.get("/iiif/context/xy-reading/1").content.decode()
        for anchor in ("xyReading", "XYReading", "column", "role", "correction"):
            with self.subTest(anchor=anchor):
                self.assertIn(f'id="{anchor}"', page)
