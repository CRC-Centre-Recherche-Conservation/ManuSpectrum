"""The licence catalogue, its stored shape, and its delivery to the browser.

The licence stamped on stored files is covered by ``test_repair_file_metadata``.

Usage:
    python manage.py test tests.test_file_licenses --settings="tests.test_settings"
"""

import html as html_module
import json
import re

from django.contrib.auth.models import AnonymousUser
from django.template import engines
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import translation

from manuspectrum.constants.licenses import (
    CUSTOM_LICENSE_ID,
    DEFAULT_LICENSE_ID,
    LICENSES,
    catalogue_json,
    default_license,
    effective_license,
    iiif_rights,
    stored_license,
)


class CatalogueTests(SimpleTestCase):
    def test_ids_are_unique(self):
        ids = [entry["id"] for entry in LICENSES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_catalogue_licence_links_to_an_https_text(self):
        for entry in LICENSES:
            if entry["id"] == CUSTOM_LICENSE_ID:
                continue
            with self.subTest(entry["id"]):
                self.assertTrue(entry["url"].startswith("https://"))

    def test_default_and_custom_entries_exist(self):
        ids = {entry["id"] for entry in LICENSES}
        self.assertIn(DEFAULT_LICENSE_ID, ids)
        self.assertIn(CUSTOM_LICENSE_ID, ids)
        self.assertEqual(DEFAULT_LICENSE_ID, "CC-BY-SA-4.0")

    def test_default_license_is_the_stored_shape(self):
        self.assertEqual(
            default_license(),
            {
                "id": "CC-BY-SA-4.0",
                "url": "https://creativecommons.org/licenses/by-sa/4.0/",
            },
        )

    def test_labels_follow_the_active_language(self):
        other = next(e for e in LICENSES if e["id"] == CUSTOM_LICENSE_ID)
        with translation.override("fr"):
            self.assertEqual(str(other["label"]), "Autre licence…")


class StoredLicenseTests(SimpleTestCase):
    def test_a_catalogue_id_gives_the_stored_shape(self):
        self.assertEqual(
            stored_license("CC0-1.0"),
            {
                "id": "CC0-1.0",
                "url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )

    def test_the_default_is_the_stored_shape_of_the_default_id(self):
        self.assertEqual(default_license(), stored_license(DEFAULT_LICENSE_ID))

    def test_the_custom_entry_and_unknown_ids_are_refused(self):
        for value in (CUSTOM_LICENSE_ID, "GPL-3.0", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    stored_license(value)


class IiifRightsTests(SimpleTestCase):
    def test_iiif_rights_uses_http_for_a_creative_commons_licence(self):
        licence = effective_license({"license": {"id": "CC-BY-4.0"}}, "en")
        self.assertEqual(
            iiif_rights(licence), "http://creativecommons.org/licenses/by/4.0/"
        )

    def test_iiif_rights_uses_http_for_rightsstatements(self):
        licence = effective_license(
            {
                "license": {
                    "id": "LicenseRef-custom",
                    "url": "https://rightsstatements.org/vocab/InC/1.0/",
                    "label": "In copyright",
                }
            },
            "en",
        )
        self.assertEqual(
            iiif_rights(licence), "http://rightsstatements.org/vocab/InC/1.0/"
        )

    def test_iiif_rights_is_none_outside_the_registries(self):
        licence = effective_license({"license": {"id": "etalab-2.0"}}, "en")
        self.assertIsNone(iiif_rights(licence))

    def test_iiif_rights_is_none_for_a_custom_licence_without_url(self):
        licence = effective_license(
            {"license": {"id": "LicenseRef-custom", "label": "Mine"}}, "en"
        )
        self.assertIsNone(iiif_rights(licence))


class CatalogueDeliveryTests(SimpleTestCase):
    def test_catalogue_json_carries_default_custom_and_every_licence(self):
        payload = json.loads(catalogue_json())
        self.assertEqual(payload["default"], DEFAULT_LICENSE_ID)
        self.assertEqual(payload["custom"], CUSTOM_LICENSE_ID)
        self.assertEqual(
            [entry["id"] for entry in payload["licenses"]],
            [entry["id"] for entry in LICENSES],
        )

    def test_the_tag_escapes_the_json_for_an_attribute(self):
        template = engines["django"].from_string(
            "{% load file_licenses %}<div a='{% license_catalogue_json %}'></div>"
        )
        with translation.override("fr"):
            html = template.render({})
        value = re.search(r"a='([^']*)'", html).group(1)
        self.assertNotIn('"', value)
        payload = json.loads(html_module.unescape(value))
        self.assertIn("Autre licence…", [e["label"] for e in payload["licenses"]])


class JavascriptTemplateTests(TestCase):
    def test_javascript_htm_exposes_the_catalogue_to_arches_translations(self):
        request = RequestFactory().get("/fr/")
        request.user = AnonymousUser()
        with translation.override("fr"):
            html = render_to_string("javascript.htm", {}, request=request)
        match = re.search(r"license-catalogue='([^']*)'", html)
        self.assertIsNotNone(match)
        payload = json.loads(html_module.unescape(match.group(1)))
        self.assertEqual(payload["default"], DEFAULT_LICENSE_ID)
        self.assertIn("Autre licence…", [e["label"] for e in payload["licenses"]])
