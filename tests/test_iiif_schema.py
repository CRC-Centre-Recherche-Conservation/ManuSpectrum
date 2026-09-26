"""The IIIF Presentation 3 schema harness the manifest tests validate against.

Usage:
    python manage.py test tests.test_iiif_schema --settings="tests.test_settings"
"""

from django.test import SimpleTestCase

from tests.iiif_schema import assert_valid_manifest

MINIMAL = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": "https://example.org/iiif/m",
    "type": "Manifest",
    "label": {"en": ["m"]},
    "items": [],
}


class SchemaHarnessTests(SimpleTestCase):
    def test_a_minimal_manifest_is_valid(self):
        assert_valid_manifest(self, MINIMAL)

    def test_a_manifest_without_label_is_invalid(self):
        broken = {k: v for k, v in MINIMAL.items() if k != "label"}
        with self.assertRaises(AssertionError):
            assert_valid_manifest(self, broken)
