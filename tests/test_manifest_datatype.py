"""
Unit tests for ManifestDataType.

Tests IIIF v2/v3 manifest validation and transformation using real IIIF examples.

Usage:
    python manage.py test manuspectrum.tests.test_manifest_datatype
"""

import uuid
from unittest.mock import MagicMock, Mock, patch, call

from django.test import TestCase
import requests


class ManifestTestData:
    """Real IIIF manifest examples for testing."""

    # Full IIIF Presentation API v3 manifest example
    VALID_V3 = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": "https://example.org/iiif/book1/manifest",
        "type": "Manifest",
        "label": {"en": ["Book 1"]},
        "metadata": [
            {"label": {"en": ["Author"]}, "value": {"none": ["Anne Author"]}},
            {
                "label": {"en": ["Published"]},
                "value": {"en": ["Paris, circa 1400"], "fr": ["Paris, environ 1400"]},
            },
            {
                "label": {"en": ["Notes"]},
                "value": {"en": ["Text of note 1", "Text of note 2"]},
            },
        ],
        "summary": {
            "en": ["Book 1, written be Anne Author, published in Paris around 1400."]
        },
        "thumbnail": [
            {
                "id": "https://example.org/iiif/book1/page1/full/80,100/0/default.jpg",
                "type": "Image",
                "format": "image/jpeg",
                "service": [
                    {
                        "id": "https://example.org/iiif/book1/page1",
                        "type": "ImageService3",
                        "profile": "level1",
                    }
                ],
            }
        ],
        "viewingDirection": "right-to-left",
        "behavior": ["paged"],
        "navDate": "1856-01-01T00:00:00Z",
        "rights": "https://creativecommons.org/licenses/by/4.0/",
        "requiredStatement": {
            "label": {"en": ["Attribution"]},
            "value": {"en": ["Provided by Example Organization"]},
        },
        "provider": [
            {
                "id": "https://example.org/about",
                "type": "Agent",
                "label": {"en": ["Example Organization"]},
                "homepage": [
                    {
                        "id": "https://example.org/",
                        "type": "Text",
                        "label": {"en": ["Example Organization Homepage"]},
                        "format": "text/html",
                    }
                ],
            }
        ],
        "items": [
            {
                "id": "https://example.org/iiif/book1/canvas/p1",
                "type": "Canvas",
                "label": {"none": ["p. 1"]},
                "height": 1000,
                "width": 750,
                "items": [
                    {
                        "id": "https://example.org/iiif/book1/page/p1/1",
                        "type": "AnnotationPage",
                        "items": [
                            {
                                "id": "https://example.org/iiif/book1/annotation/p0001-image",
                                "type": "Annotation",
                                "motivation": "painting",
                                "body": {
                                    "id": "https://example.org/iiif/book1/page1/full/max/0/default.jpg",
                                    "type": "Image",
                                    "format": "image/jpeg",
                                    "height": 2000,
                                    "width": 1500,
                                },
                                "target": "https://example.org/iiif/book1/canvas/p1",
                            }
                        ],
                    }
                ],
            },
            {
                "id": "https://example.org/iiif/book1/canvas/p2",
                "type": "Canvas",
                "label": {"none": ["p. 2"]},
                "height": 1000,
                "width": 750,
            },
        ],
        "structures": [
            {
                "id": "https://example.org/iiif/book1/range/r0",
                "type": "Range",
                "label": {"en": ["Table of Contents"]},
                "items": [
                    {
                        "id": "https://example.org/iiif/book1/range/r1",
                        "type": "Range",
                        "label": {"en": ["Introduction"]},
                    }
                ],
            }
        ],
    }

    # Full IIIF Presentation API v2 manifest example
    VALID_V2 = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "@id": "http://example.org/iiif/book1/manifest",
        "label": "Book 1",
        "metadata": [
            {"label": "Author", "value": "Anne Author"},
            {
                "label": "Published",
                "value": [
                    {"@value": "Paris, circa 1400", "@language": "en"},
                    {"@value": "Paris, environ 14eme siecle", "@language": "fr"},
                ],
            },
        ],
        "description": "A longer description of this example book. It should give some real information.",
        "navDate": "1856-01-01T00:00:00Z",
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution": "Provided by Example Organization",
        "service": {
            "@context": "http://example.org/ns/jsonld/context.json",
            "@id": "http://example.org/service/example",
            "profile": "http://example.org/docs/example-service.html",
        },
        "seeAlso": {
            "@id": "http://example.org/library/catalog/book1.marc",
            "format": "application/marc",
            "profile": "http://example.org/profiles/marc21",
        },
        "rendering": {
            "@id": "http://example.org/iiif/book1.pdf",
            "label": "Download as PDF",
            "format": "application/pdf",
        },
        "within": "http://example.org/collections/books/",
        "sequences": [
            {
                "@id": "http://example.org/iiif/book1/sequence/normal",
                "@type": "sc:Sequence",
                "label": "Current Page Order",
                "viewingDirection": "left-to-right",
                "viewingHint": "paged",
                "canvases": [
                    {
                        "@id": "http://example.org/iiif/book1/canvas/p1",
                        "@type": "sc:Canvas",
                        "label": "p. 1",
                        "height": 1000,
                        "width": 750,
                        "images": [
                            {
                                "@type": "oa:Annotation",
                                "motivation": "sc:painting",
                                "resource": {
                                    "@id": "http://example.org/iiif/book1/res/page1.jpg",
                                    "@type": "dctypes:Image",
                                    "format": "image/jpeg",
                                    "height": 2000,
                                    "width": 1500,
                                },
                                "on": "http://example.org/iiif/book1/canvas/p1",
                            }
                        ],
                    },
                    {
                        "@id": "http://example.org/iiif/book1/canvas/p2",
                        "@type": "sc:Canvas",
                        "label": "p. 2",
                        "height": 1000,
                        "width": 750,
                    },
                    {
                        "@id": "http://example.org/iiif/book1/canvas/p3",
                        "@type": "sc:Canvas",
                        "label": "p. 3",
                        "height": 1000,
                        "width": 750,
                    },
                ],
            }
        ],
        "structures": [
            {
                "@id": "http://example.org/iiif/book1/range/r1",
                "@type": "sc:Range",
                "label": "Introduction",
                "canvases": [
                    "http://example.org/iiif/book1/canvas/p1",
                    "http://example.org/iiif/book1/canvas/p2",
                    "http://example.org/iiif/book1/canvas/p3#xywh=0,0,750,300",
                ],
            }
        ],
    }

    # Invalid manifests for testing error cases
    INVALID_NO_CONTEXT = {"type": "Manifest", "label": {"en": ["No context manifest"]}}

    INVALID_WRONG_TYPE_V2 = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Collection",
        "@id": "http://example.org/collection",
    }

    INVALID_WRONG_TYPE_V3 = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "type": "Collection",
        "id": "https://example.org/collection",
    }

    # Minimal valid manifests
    MINIMAL_V2 = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "@id": "http://example.org/manifest",
    }

    MINIMAL_V3 = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "type": "Manifest",
        "id": "https://example.org/manifest",
    }


class TestIsIIIFManifest(TestCase):
    """Tests for the is_iiif_manifest static method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import (
                ManifestDataType,
                FailParsingManifestIIIF,
            )

            self.ManifestDataType = ManifestDataType
            self.FailParsingManifestIIIF = FailParsingManifestIIIF

    def test_valid_v3_manifest_returns_true(self):
        """A valid IIIF v3 manifest should return True."""
        result = self.ManifestDataType.is_iiif_manifest(ManifestTestData.VALID_V3)
        self.assertTrue(result)

    def test_valid_v2_manifest_returns_true(self):
        """A valid IIIF v2 manifest should return True."""
        result = self.ManifestDataType.is_iiif_manifest(ManifestTestData.VALID_V2)
        self.assertTrue(result)

    def test_minimal_v3_manifest_returns_true(self):
        """A minimal IIIF v3 manifest should return True."""
        result = self.ManifestDataType.is_iiif_manifest(ManifestTestData.MINIMAL_V3)
        self.assertTrue(result)

    def test_minimal_v2_manifest_returns_true(self):
        """A minimal IIIF v2 manifest should return True."""
        result = self.ManifestDataType.is_iiif_manifest(ManifestTestData.MINIMAL_V2)
        self.assertTrue(result)

    def test_non_dict_raises_exception(self):
        """A non-dict value should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest("not a dict")
        self.assertIn("not a dict", str(ctx.exception))

    def test_list_raises_exception(self):
        """A list value should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest([{"type": "Manifest"}])
        self.assertIn("not a dict", str(ctx.exception))

    def test_missing_context_raises_exception(self):
        """A manifest without valid @context should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest(ManifestTestData.INVALID_NO_CONTEXT)
        self.assertIn("no valid @context", str(ctx.exception))

    def test_wrong_type_v2_raises_exception(self):
        """A v2 manifest with wrong @type should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest(
                ManifestTestData.INVALID_WRONG_TYPE_V2
            )
        self.assertIn("invalid @type", str(ctx.exception))

    def test_wrong_type_v3_raises_exception(self):
        """A v3 manifest with wrong type should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest(
                ManifestTestData.INVALID_WRONG_TYPE_V3
            )
        self.assertIn("invalid type", str(ctx.exception))

    def test_none_raises_exception(self):
        """None should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF):
            self.ManifestDataType.is_iiif_manifest(None)

    def test_empty_dict_raises_exception(self):
        """An empty dict should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF):
            self.ManifestDataType.is_iiif_manifest({})

    def test_v2_missing_type_raises_exception(self):
        """A v2 manifest missing @type should raise FailParsingManifestIIIF."""
        manifest = {
            "@context": "http://iiif.io/api/presentation/2/context.json",
            "@id": "http://example.org/manifest",
        }
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest(manifest)
        self.assertIn("invalid @type", str(ctx.exception))

    def test_v3_missing_type_raises_exception(self):
        """A v3 manifest missing type should raise FailParsingManifestIIIF."""
        manifest = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": "https://example.org/manifest",
        }
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest(manifest)
        self.assertIn("invalid type", str(ctx.exception))


class TestExtractManifestLabel(TestCase):
    """Tests for manifest label extraction."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    def test_extract_label_v3_full_manifest(self):
        """Extract label from full v3 manifest."""
        result = self.datatype._extract_manifest_label(ManifestTestData.VALID_V3)
        self.assertEqual(result, "Book 1")

    def test_extract_label_v2_full_manifest(self):
        """Extract label from full v2 manifest (simple string)."""
        result = self.datatype._extract_manifest_label(ManifestTestData.VALID_V2)
        self.assertEqual(result, "Book 1")

    def test_extract_label_v3_dict_with_en(self):
        """Extract dict label with 'en' key (IIIF v3 style)."""
        manifest = {"label": {"en": ["English Label"], "fr": ["French Label"]}}
        result = self.datatype._extract_manifest_label(manifest)
        self.assertEqual(result, "English Label")

    def test_extract_label_v3_dict_with_none_key(self):
        """Extract dict label with 'none' key (language-independent)."""
        manifest = {"label": {"none": ["Universal Label"]}}
        result = self.datatype._extract_manifest_label(manifest)
        self.assertEqual(result, "Universal Label")

    def test_extract_label_v3_dict_without_en_falls_back(self):
        """Extract dict label without 'en' key, falls back to first available."""
        manifest = {"label": {"de": ["German Label"]}}
        result = self.datatype._extract_manifest_label(manifest)
        self.assertEqual(result, "German Label")

    def test_extract_label_v2_list_with_language(self):
        """Extract list label with @value/@language objects (IIIF v2 style)."""
        manifest = {
            "label": [
                {"@value": "English Title", "@language": "en"},
                {"@value": "Titre français", "@language": "fr"},
            ]
        }
        result = self.datatype._extract_manifest_label(manifest)
        self.assertEqual(result, "English Title")

    def test_extract_label_list_of_strings(self):
        """Extract list of plain strings."""
        manifest = {"label": ["First Label", "Second Label"]}
        result = self.datatype._extract_manifest_label(manifest)
        self.assertEqual(result, "First Label")

    def test_extract_label_from_none_returns_none(self):
        """Extracting from None manifest returns None."""
        result = self.datatype._extract_manifest_label(None)
        self.assertIsNone(result)

    def test_extract_label_missing_returns_none(self):
        """Extracting from manifest without label returns None."""
        result = self.datatype._extract_manifest_label({"id": "test"})
        self.assertIsNone(result)

    def test_extract_label_empty_list_returns_none(self):
        """Extracting from manifest with empty label list returns None."""
        manifest = {"label": []}
        result = self.datatype._extract_manifest_label(manifest)
        self.assertIsNone(result)

    def test_extract_label_empty_dict_returns_none(self):
        """Extracting from manifest with empty label dict returns None."""
        manifest = {"label": {}}
        result = self.datatype._extract_manifest_label(manifest)
        self.assertIsNone(result)


class TestExtractManifestDescription(TestCase):
    """Tests for manifest description extraction."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    def test_extract_description_v2_full_manifest(self):
        """Extract description from full v2 manifest."""
        result = self.datatype._extract_manifest_description(ManifestTestData.VALID_V2)
        self.assertEqual(
            result,
            "A longer description of this example book. It should give some real information.",
        )

    def test_extract_summary_v3_full_manifest(self):
        """Extract summary from full v3 manifest (v3 uses 'summary' not 'description')."""
        result = self.datatype._extract_manifest_description(ManifestTestData.VALID_V3)
        self.assertEqual(
            result, "Book 1, written be Anne Author, published in Paris around 1400."
        )

    def test_description_takes_precedence_over_summary(self):
        """When both exist, description should be used."""
        manifest = {
            "description": "Description text",
            "summary": {"en": ["Summary text"]},
        }
        result = self.datatype._extract_manifest_description(manifest)
        self.assertEqual(result, "Description text")

    def test_extract_summary_v3_dict(self):
        """Extract v3 summary dict with language keys."""
        manifest = {"summary": {"en": ["English summary"], "fr": ["French summary"]}}
        result = self.datatype._extract_manifest_description(manifest)
        self.assertEqual(result, "English summary")

    def test_extract_description_v2_list_with_language(self):
        """Extract list description with @value objects."""
        manifest = {
            "description": [{"@value": "English description", "@language": "en"}]
        }
        result = self.datatype._extract_manifest_description(manifest)
        self.assertEqual(result, "English description")

    def test_extract_description_none_returns_none(self):
        """Extracting from None manifest returns None."""
        result = self.datatype._extract_manifest_description(None)
        self.assertIsNone(result)

    def test_extract_description_missing_returns_none(self):
        """Extracting from manifest without description/summary returns None."""
        result = self.datatype._extract_manifest_description({"label": "Test"})
        self.assertIsNone(result)


class TestManifestValidation(TestCase):
    """Tests for the validate method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    def test_validate_none_returns_empty_errors(self):
        """Validating None should return no errors."""
        errors = self.datatype.validate(None)
        self.assertEqual(errors, [])

    def test_validate_empty_string_returns_empty_errors(self):
        """Validating empty string should return no errors."""
        errors = self.datatype.validate("")
        self.assertEqual(errors, [])

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_validate_existing_manifest_id(self, mock_manifest_model):
        """Validating an existing manifest UUID should succeed."""
        test_uuid = str(uuid.uuid4())
        mock_manifest_model.objects.get.return_value = MagicMock()

        errors = self.datatype.validate(test_uuid)
        self.assertEqual(errors, [])
        mock_manifest_model.objects.get.assert_called_once_with(globalid=test_uuid)

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_validate_nonexistent_manifest_id(self, mock_manifest_model):
        """Validating a non-existent manifest UUID should return an error."""
        test_uuid = str(uuid.uuid4())
        mock_manifest_model.DoesNotExist = Exception
        mock_manifest_model.objects.get.side_effect = mock_manifest_model.DoesNotExist(
            "Not found"
        )

        errors = self.datatype.validate(test_uuid)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["type"], "ERROR")
        self.assertIn("does not exist", str(errors[0]["message"]))

    def test_validate_invalid_url_format(self):
        """Validating an invalid URL should return an error."""
        errors = self.datatype.validate("not-a-valid-url")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["type"], "ERROR")

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_url_with_valid_v3_manifest(self, mock_get):
        """Validating a URL that returns a valid v3 manifest should succeed."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()

        mock_get.return_value = mock_response

        errors = self.datatype.validate("https://example.org/iiif/book1/manifest")
        self.assertEqual(errors, [])

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_url_with_valid_v2_manifest(self, mock_get):
        """Validating a URL that returns a valid v2 manifest should succeed."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V2
        mock_response.raise_for_status = MagicMock()

        mock_get.return_value = mock_response

        errors = self.datatype.validate("http://example.org/iiif/book1/manifest")
        self.assertEqual(errors, [])

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_does_not_create_manifest(self, mock_get):
        """Validating a URL should NOT create an IIIFManifest record (creation is in pre_tile_save)."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()

        mock_get.return_value = mock_response

        with patch(
            "manuspectrum.datatypes.manifest.IIIFManifest"
        ) as mock_manifest_model:
            self.datatype.validate("https://example.org/iiif/book1/manifest")
            mock_manifest_model.objects.create.assert_not_called()

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_url_timeout(self, mock_get):
        """Validating a URL that times out should return an error."""
        mock_get.side_effect = requests.Timeout()

        errors = self.datatype.validate("https://example.org/iiif/book1/manifest")
        self.assertEqual(len(errors), 1)
        self.assertIn("Timeout", str(errors[0]["message"]))

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_url_connection_error(self, mock_get):
        """Validating a URL with connection error should return an error."""
        mock_get.side_effect = requests.ConnectionError()

        errors = self.datatype.validate("https://example.org/iiif/book1/manifest")
        self.assertEqual(len(errors), 1)

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_url_invalid_manifest_no_context(self, mock_get):
        """Validating a URL that returns manifest without @context should error."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.INVALID_NO_CONTEXT
        mock_response.raise_for_status = MagicMock()

        mock_get.return_value = mock_response

        errors = self.datatype.validate("https://example.org/iiif/invalid/manifest")
        self.assertEqual(len(errors), 1)
        self.assertIn("Invalid IIIF manifest", str(errors[0]["message"]))

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_url_wrong_type_v2(self, mock_get):
        """Validating a URL that returns v2 Collection should error."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.INVALID_WRONG_TYPE_V2
        mock_response.raise_for_status = MagicMock()

        mock_get.return_value = mock_response

        errors = self.datatype.validate("http://example.org/collection")
        self.assertEqual(len(errors), 1)
        self.assertIn("Invalid IIIF manifest", str(errors[0]["message"]))

    def test_validate_dict_without_id_or_url_returns_error(self):
        """Validating a dict without manifest_id or manifest_url should error."""
        errors = self.datatype.validate({"invalid_key": "value"})
        self.assertEqual(len(errors), 1)
        self.assertIn("must have a URL or ID", str(errors[0]["message"]))

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_validate_dict_with_manifest_id(self, mock_manifest_model):
        """Validating a dict with manifest_id should check existence."""
        test_uuid = str(uuid.uuid4())
        mock_manifest_model.objects.get.return_value = MagicMock()

        errors = self.datatype.validate({"manifest_id": test_uuid})
        self.assertEqual(errors, [])

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_dict_with_manifest_url(self, mock_get):
        """Validating a dict with manifest_url should fetch and validate."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()

        mock_get.return_value = mock_response

        errors = self.datatype.validate(
            {"manifest_url": "https://example.org/iiif/book1/manifest"}
        )
        self.assertEqual(errors, [])

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_validate_local_path_passes_when_exists(self, mock_manifest_model):
        """Local path /manifest/{uuid} should pass if manifest exists by globalid."""
        mock_filter = MagicMock()
        mock_filter.exists.return_value = True
        mock_manifest_model.objects.filter.return_value = mock_filter

        errors = self.datatype.validate(
            "/manifest/ceaf19e3-e1c5-4638-af81-b79562d33787"
        )
        self.assertEqual(errors, [])
        mock_manifest_model.objects.filter.assert_called_once_with(
            globalid="ceaf19e3-e1c5-4638-af81-b79562d33787"
        )

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_validate_local_path_with_host_passes(self, mock_manifest_model):
        """Full local URL http://host/manifest/{uuid} should also validate by globalid."""
        mock_filter = MagicMock()
        mock_filter.exists.return_value = True
        mock_manifest_model.objects.filter.return_value = mock_filter

        errors = self.datatype.validate(
            "http://localhost:8000/manifest/ceaf19e3-e1c5-4638-af81-b79562d33787"
        )
        self.assertEqual(errors, [])
        mock_manifest_model.objects.filter.assert_called_once_with(
            globalid="ceaf19e3-e1c5-4638-af81-b79562d33787"
        )

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_validate_local_path_fails_when_not_found(self, mock_manifest_model):
        """Local path should fail if the manifest globalid is not in DB."""
        mock_filter = MagicMock()
        mock_filter.exists.return_value = False
        mock_manifest_model.objects.filter.return_value = mock_filter

        errors = self.datatype.validate(
            "/manifest/ceaf19e3-e1c5-4638-af81-b79562d33787"
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0]["message"].lower())

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_external_url_sends_headers(self, mock_get):
        """External URL validation should send proper headers."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()

        mock_get.return_value = mock_response

        url = "https://example.org/iiif/book1/manifest"
        errors = self.datatype.validate(url)
        self.assertEqual(errors, [])
        call_kwargs = mock_get.call_args
        self.assertIn("headers", call_kwargs[1])
        self.assertIn("User-Agent", call_kwargs[1]["headers"])


class TestTransformValueForTile(TestCase):
    """Tests for transform_value_for_tile method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    def test_transform_none_returns_none(self):
        """Transforming None should return None."""
        result = self.datatype.transform_value_for_tile(None)
        self.assertIsNone(result)

    def test_transform_empty_string_returns_none(self):
        """Transforming empty string should return None."""
        result = self.datatype.transform_value_for_tile("")
        self.assertIsNone(result)

    def test_transform_url_string(self):
        """Transforming a URL string should return normalized URL."""
        result = self.datatype.transform_value_for_tile(
            "https://example.org/iiif/book1/manifest/"
        )
        self.assertEqual(result, "https://example.org/iiif/book1/manifest")

    def test_transform_uuid_string(self):
        """Transforming a UUID string should return it normalized (unchanged)."""
        test_uuid = str(uuid.uuid4())
        result = self.datatype.transform_value_for_tile(test_uuid)
        self.assertEqual(result, test_uuid)

    def test_transform_dict_with_manifest_url(self):
        """Transforming a dict with manifest_url should return normalized URL."""
        result = self.datatype.transform_value_for_tile(
            {"manifest_url": "https://example.org/iiif/book1/manifest/"}
        )
        self.assertEqual(result, "https://example.org/iiif/book1/manifest")

    def test_transform_dict_without_url_returns_none(self):
        """Transforming a dict without manifest_url should return None."""
        result = self.datatype.transform_value_for_tile({"other_key": "value"})
        self.assertIsNone(result)


class TestGetDisplayValue(TestCase):
    """Tests for get_display_value method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_get_display_value_with_url(self, mock_manifest_model):
        """Display value should include label and URL from DB record."""
        mock_manifest = MagicMock()
        mock_manifest.label = "Book 1"
        mock_manifest.url = "/iiif/book1/manifest"
        mock_manifest_model.objects.get.return_value = mock_manifest
        mock_manifest_model.DoesNotExist = Exception

        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = MagicMock()
        tile.data = {str(node.nodeid): "https://example.org/iiif/book1/manifest"}

        result = self.datatype.get_display_value(tile, node)
        self.assertIn("Book 1", result)
        self.assertIn("/iiif/book1/manifest", result)
        # Verify lookup uses relative path extracted from full URL
        mock_manifest_model.objects.get.assert_called_once_with(
            url="/iiif/book1/manifest"
        )

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_get_display_value_without_url(self, mock_manifest_model):
        """Display value without URL on DB record should show label only."""
        mock_manifest = MagicMock()
        mock_manifest.label = "Book 1"
        mock_manifest.url = None
        mock_manifest_model.objects.get.return_value = mock_manifest
        mock_manifest_model.DoesNotExist = Exception

        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = MagicMock()
        tile.data = {str(node.nodeid): "https://example.org/iiif/book1/manifest"}

        result = self.datatype.get_display_value(tile, node)
        self.assertEqual(result, "Book 1")

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_get_display_value_manifest_not_found(self, mock_manifest_model):
        """Display value should fallback to raw URL when manifest not in DB."""
        mock_manifest_model.DoesNotExist = Exception
        mock_manifest_model.objects.get.side_effect = mock_manifest_model.DoesNotExist

        node = MagicMock()
        node.nodeid = uuid.uuid4()
        url = "https://example.org/iiif/book1/manifest"
        tile = MagicMock()
        tile.data = {str(node.nodeid): url}

        result = self.datatype.get_display_value(tile, node)
        self.assertEqual(result, url)

    def test_get_display_value_no_data_returns_none(self):
        """Display value with no tile data should return None."""
        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = MagicMock()
        tile.data = None

        result = self.datatype.get_display_value(tile, node)
        self.assertIsNone(result)

    def test_get_display_value_missing_node_returns_none(self):
        """Display value with missing node in tile data should return None."""
        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = MagicMock()
        tile.data = {"other_node": "value"}

        result = self.datatype.get_display_value(tile, node)
        self.assertIsNone(result)


class TestClean(TestCase):
    """Tests for the clean method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    def test_clean_empty_string_to_none(self):
        """Clean should convert empty string to None."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: ""}

        self.datatype.clean(tile, nodeid)
        self.assertIsNone(tile.data[nodeid])

    def test_clean_none_stays_none(self):
        """Clean should keep None as None."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: None}

        self.datatype.clean(tile, nodeid)
        self.assertIsNone(tile.data[nodeid])

    def test_clean_valid_value_unchanged(self):
        """Clean should not modify valid values."""
        nodeid = str(uuid.uuid4())
        test_uuid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: test_uuid}

        self.datatype.clean(tile, nodeid)
        self.assertEqual(tile.data[nodeid], test_uuid)


class TestURLRegex(TestCase):
    """Tests for URL regex validation."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.ManifestDataType = ManifestDataType

    def test_valid_https_url(self):
        """HTTPS URLs should match strict regex."""
        self.assertIsNotNone(
            self.ManifestDataType._URL_REGEX_STRICT.match(
                "https://example.org/iiif/book1/manifest"
            )
        )

    def test_unvalid_https_url(self):
        """Invalid HTTPS URLs should not match strict regex."""
        self.assertIsNone(
            self.ManifestDataType._URL_REGEX_STRICT.match("iiif/book1/manifest")
        )

    def test_strict_rejects_localhost(self):
        """Strict regex should NOT match localhost URLs."""
        self.assertIsNone(
            self.ManifestDataType._URL_REGEX_STRICT.match(
                "http://localhost:8000/manifest/abc"
            )
        )

    def test_dev_matches_localhost(self):
        """Dev regex should match localhost URLs."""
        self.assertIsNotNone(
            self.ManifestDataType._URL_REGEX_DEV.match(
                "http://localhost:8000/manifest/abc"
            )
        )

    def test_dev_matches_localhost_no_port(self):
        """Dev regex should match localhost without port."""
        self.assertIsNotNone(
            self.ManifestDataType._URL_REGEX_DEV.match("http://localhost/manifest/abc")
        )

    def test_dev_matches_ip_address(self):
        """Dev regex should match IP address URLs."""
        self.assertIsNotNone(
            self.ManifestDataType._URL_REGEX_DEV.match(
                "http://127.0.0.1:8000/manifest/abc"
            )
        )

    def test_dev_also_matches_domain(self):
        """Dev regex should also match regular domain URLs."""
        self.assertIsNotNone(
            self.ManifestDataType._URL_REGEX_DEV.match(
                "https://example.org/iiif/book1/manifest"
            )
        )

    @patch("manuspectrum.datatypes.manifest.django_settings")
    def test_get_url_regex_debug_true(self, mock_settings):
        """_get_url_regex should return dev regex when DEBUG=True."""
        mock_settings.DEBUG = True
        regex = self.ManifestDataType._get_url_regex()
        self.assertIs(regex, self.ManifestDataType._URL_REGEX_DEV)

    @patch("manuspectrum.datatypes.manifest.django_settings")
    def test_get_url_regex_debug_false(self, mock_settings):
        """_get_url_regex should return strict regex when DEBUG=False."""
        mock_settings.DEBUG = False
        regex = self.ManifestDataType._get_url_regex()
        self.assertIs(regex, self.ManifestDataType._URL_REGEX_STRICT)


class TestGetPrefLabel(TestCase):
    """Tests for get_pref_label class method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.ManifestDataType = ManifestDataType

    def test_get_pref_label(self):
        """Should return 'IIIF Manifest' as preferred label."""
        result = self.ManifestDataType.get_pref_label()
        self.assertEqual(result, "IIIF Manifest")


class TestTransformExportValues(TestCase):
    """Tests for transform_export_values method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    def test_transform_export_values_returns_value(self):
        """Should return value unchanged for export."""
        test_uuid = str(uuid.uuid4())
        result = self.datatype.transform_export_values(test_uuid)
        self.assertEqual(result, test_uuid)

    def test_transform_export_values_none(self):
        """Should return None unchanged."""
        result = self.datatype.transform_export_values(None)
        self.assertIsNone(result)


class TestNormalizeUrl(TestCase):
    """Tests for the _normalize_url static method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.ManifestDataType = ManifestDataType

    def test_strips_trailing_slash(self):
        result = self.ManifestDataType._normalize_url(
            "https://example.org/iiif/book1/manifest/"
        )
        self.assertEqual(result, "https://example.org/iiif/book1/manifest")

    def test_strips_fragment(self):
        result = self.ManifestDataType._normalize_url(
            "https://example.org/iiif/book1/manifest#section"
        )
        self.assertEqual(result, "https://example.org/iiif/book1/manifest")

    def test_strips_trailing_slash_and_fragment(self):
        result = self.ManifestDataType._normalize_url(
            "https://example.org/iiif/book1/manifest/#section"
        )
        self.assertEqual(result, "https://example.org/iiif/book1/manifest")

    def test_preserves_clean_url(self):
        url = "https://example.org/iiif/book1/manifest"
        result = self.ManifestDataType._normalize_url(url)
        self.assertEqual(result, url)

    def test_preserves_query_string(self):
        result = self.ManifestDataType._normalize_url(
            "https://example.org/iiif/manifest?version=2"
        )
        self.assertEqual(result, "https://example.org/iiif/manifest?version=2")

    def test_none_returns_none(self):
        result = self.ManifestDataType._normalize_url(None)
        self.assertIsNone(result)

    def test_empty_string_returns_empty(self):
        result = self.ManifestDataType._normalize_url("")
        self.assertEqual(result, "")

    def test_same_url_different_forms_normalize_equally(self):
        """URLs that differ only by trailing slash or fragment should normalize to the same value."""
        url1 = self.ManifestDataType._normalize_url(
            "https://example.org/iiif/book1/manifest"
        )
        url2 = self.ManifestDataType._normalize_url(
            "https://example.org/iiif/book1/manifest/"
        )
        url3 = self.ManifestDataType._normalize_url(
            "https://example.org/iiif/book1/manifest#top"
        )
        self.assertEqual(url1, url2)
        self.assertEqual(url2, url3)


class TestToRelativePath(TestCase):
    """Tests for the _to_relative_path static method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.ManifestDataType = ManifestDataType

    def test_full_url_returns_path(self):
        result = self.ManifestDataType._to_relative_path(
            "http://localhost:8000/manifest/abc-123"
        )
        self.assertEqual(result, "/manifest/abc-123")

    def test_https_url_returns_path(self):
        result = self.ManifestDataType._to_relative_path(
            "https://example.org/iiif/book1/manifest"
        )
        self.assertEqual(result, "/iiif/book1/manifest")

    def test_relative_path_unchanged(self):
        result = self.ManifestDataType._to_relative_path("/manifest/abc-123")
        self.assertEqual(result, "/manifest/abc-123")

    def test_none_returns_none(self):
        result = self.ManifestDataType._to_relative_path(None)
        self.assertIsNone(result)

    def test_empty_returns_empty(self):
        result = self.ManifestDataType._to_relative_path("")
        self.assertEqual(result, "")

    def test_strips_trailing_slash(self):
        result = self.ManifestDataType._to_relative_path(
            "http://localhost:8000/manifest/abc-123/"
        )
        self.assertEqual(result, "/manifest/abc-123")


class TestPreTileSave(TestCase):
    """Tests for the pre_tile_save method."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    def test_pre_tile_save_skips_none_value(self):
        """pre_tile_save should do nothing when value is None."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: None}

        self.datatype.pre_tile_save(tile, nodeid)
        self.assertIsNone(tile.data[nodeid])

    def test_pre_tile_save_keeps_existing_uuid(self):
        """pre_tile_save should not modify an existing UUID value."""
        nodeid = str(uuid.uuid4())
        test_uuid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: test_uuid}

        self.datatype.pre_tile_save(tile, nodeid)
        self.assertEqual(tile.data[nodeid], test_uuid)

    def test_pre_tile_save_skips_dict_value(self):
        """pre_tile_save should skip non-string values (dict)."""
        nodeid = str(uuid.uuid4())
        original_value = {"manifest_id": str(uuid.uuid4())}
        tile = MagicMock()
        tile.data = {nodeid: original_value}

        self.datatype.pre_tile_save(tile, nodeid)
        # Value should be untouched — pre_tile_save only handles strings
        self.assertEqual(tile.data[nodeid], original_value)

    @patch("manuspectrum.datatypes.manifest.requests.get")
    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_pre_tile_save_imports_external_manifest_as_local(
        self, mock_manifest_model, mock_get
    ):
        """pre_tile_save should import external manifest and store local path."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "https://example.org/iiif/book1/manifest"}

        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Both lookups fail (new external manifest)
        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        # Mock create to return a manifest with auto-generated globalid
        created_globalid = uuid.uuid4()
        mock_created = MagicMock()
        mock_created.globalid = created_globalid
        mock_created.url = f"/manifest/{created_globalid}"
        mock_manifest_model.objects.create.return_value = mock_created

        self.datatype.pre_tile_save(tile, nodeid)

        mock_manifest_model.objects.create.assert_called_once()
        create_kwargs = mock_manifest_model.objects.create.call_args[1]
        self.assertEqual(create_kwargs["label"], "Book 1")
        # tile.data should now be the local path
        self.assertEqual(tile.data[nodeid], f"/manifest/{created_globalid}")

    @patch("manuspectrum.datatypes.manifest.requests.get")
    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_pre_tile_save_reuses_already_imported_external(
        self, mock_manifest_model, mock_get
    ):
        """pre_tile_save should reuse existing record for already-imported external URL."""
        nodeid = str(uuid.uuid4())
        existing_globalid = uuid.uuid4()
        tile = MagicMock()
        tile.data = {
            nodeid: "https://gallica.bnf.fr/iiif/ark:/12148/btv1b105477296/manifest.json"
        }

        # Step 1: relative path lookup returns None
        # Step 2: full URL lookup returns existing manifest
        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_filter_found = MagicMock()
        mock_filter_found.first.return_value = MagicMock(
            globalid=existing_globalid,
            url="https://gallica.bnf.fr/iiif/ark:/12148/btv1b105477296/manifest.json",
        )
        mock_manifest_model.objects.filter.side_effect = [
            mock_filter_none,
            mock_filter_found,
        ]

        self.datatype.pre_tile_save(tile, nodeid)

        # Should NOT fetch or create (reuses existing)
        mock_get.assert_not_called()
        mock_manifest_model.objects.create.assert_not_called()
        # tile.data should be the local path from globalid
        self.assertEqual(tile.data[nodeid], f"/manifest/{existing_globalid}")

    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_pre_tile_save_dedup_local_manifest(self, mock_manifest_model):
        """When local manifest exists by relative path, should store its url."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "http://localhost:8000/manifest/abc-123"}

        # Relative path lookup succeeds
        mock_manifest = MagicMock()
        mock_manifest.url = "/manifest/abc-123"
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_manifest
        mock_manifest_model.objects.filter.return_value = mock_filter

        self.datatype.pre_tile_save(tile, nodeid)

        # Should NOT create (manifest already exists)
        mock_manifest_model.objects.create.assert_not_called()
        # tile.data should be the relative path from DB
        self.assertEqual(tile.data[nodeid], "/manifest/abc-123")
        # Verify lookup used relative path
        mock_manifest_model.objects.filter.assert_called_once_with(
            url="/manifest/abc-123"
        )


# ======================================================================
# SSRF Vulnerability Tests
# ======================================================================


class TestSSRF_RedirectBlocked(TestCase):
    """Verify that allow_redirects=False prevents redirect-based SSRF.

    An attacker provides a valid external URL (passes regex). Their server
    would return a 302 to an internal IP, but allow_redirects=False stops it.
    """

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_disables_redirects(self, mock_get):
        """validate() must call requests.get with allow_redirects=False."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_get.return_value = mock_response

        self.datatype.validate("https://evil.com/ssrf-redirect")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        self.assertIn("allow_redirects", call_kwargs)
        self.assertFalse(
            call_kwargs["allow_redirects"],
            "PROTECTION: validate() must disable redirects to prevent SSRF",
        )

    @patch("manuspectrum.datatypes.manifest.requests.get")
    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_pre_tile_save_disables_redirects(self, mock_manifest_model, mock_get):
        """pre_tile_save() must call requests.get with allow_redirects=False."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "https://evil.com/ssrf-redirect"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_get.return_value = mock_response

        self.datatype.pre_tile_save(tile, nodeid)

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        self.assertIn("allow_redirects", call_kwargs)
        self.assertFalse(
            call_kwargs["allow_redirects"],
            "PROTECTION: pre_tile_save() must disable redirects to prevent SSRF",
        )


class TestSSRF_PreTileSaveURLValidation(TestCase):
    """Verify that pre_tile_save() now validates URLs with the regex
    before fetching, blocking private IPs and invalid URLs.
    """

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    @patch("manuspectrum.datatypes.manifest.django_settings")
    @patch("manuspectrum.datatypes.manifest.requests.get")
    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_pre_tile_save_strict_regex_matches_private_ip(
        self, mock_manifest_model, mock_get, mock_settings
    ):
        """Strict regex matches IPs like 192.168.1.1 (dots in char class).

        The regex alone does not block private IPs — but allow_redirects=False
        prevents redirect-based SSRF through these IPs.
        """
        mock_settings.DEBUG = False
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "http://192.168.1.1/admin"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        self.datatype.pre_tile_save(tile, nodeid)

        # Strict regex matches IPs — request is made but without redirects
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        self.assertFalse(call_kwargs["allow_redirects"])

    @patch("manuspectrum.datatypes.manifest.django_settings")
    @patch("manuspectrum.datatypes.manifest.requests.get")
    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_pre_tile_save_strict_regex_matches_cloud_metadata(
        self, mock_manifest_model, mock_get, mock_settings
    ):
        """Strict regex matches 169.254.169.254 (dots in char class).

        The regex alone does not block cloud metadata — but allow_redirects=False
        prevents redirect-based SSRF. Full IP blocking requires url_validator.
        """
        mock_settings.DEBUG = False
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "http://169.254.169.254/latest/meta-data/"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        self.datatype.pre_tile_save(tile, nodeid)

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        self.assertFalse(call_kwargs["allow_redirects"])

    @patch("manuspectrum.datatypes.manifest.django_settings")
    @patch("manuspectrum.datatypes.manifest.requests.get")
    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_pre_tile_save_blocks_localhost_in_prod(
        self, mock_manifest_model, mock_get, mock_settings
    ):
        """pre_tile_save() must reject localhost URLs in production."""
        mock_settings.DEBUG = False
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "http://localhost:6379/"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        self.datatype.pre_tile_save(tile, nodeid)

        mock_get.assert_not_called()

    @patch("manuspectrum.datatypes.manifest.requests.get")
    @patch("manuspectrum.datatypes.manifest.IIIFManifest")
    def test_pre_tile_save_allows_valid_external_url(
        self, mock_manifest_model, mock_get
    ):
        """pre_tile_save() must still allow valid external URLs."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "https://example.org/iiif/manifest"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_get.return_value = mock_response

        self.datatype.pre_tile_save(tile, nodeid)

        mock_get.assert_called_once()


class TestSSRF_DevModePrivateIPs(TestCase):
    """Prove that DEBUG=True allows private IPs through the regex in validate().

    When DEBUG=True, _URL_REGEX_DEV matches any IP address including
    internal networks, cloud metadata, and loopback.
    """

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.ManifestDataType = ManifestDataType
            self.datatype = ManifestDataType()

    def test_dev_regex_allows_aws_metadata_ip(self):
        """DEV regex matches cloud metadata IP 169.254.169.254."""
        match = self.ManifestDataType._URL_REGEX_DEV.match(
            "http://169.254.169.254/latest/meta-data/"
        )
        self.assertIsNotNone(
            match,
            "SSRF CONFIRMED: dev regex allows cloud metadata endpoint",
        )

    def test_dev_regex_allows_internal_network(self):
        """DEV regex matches internal 10.x network."""
        match = self.ManifestDataType._URL_REGEX_DEV.match(
            "http://10.0.0.1:8080/internal-api"
        )
        self.assertIsNotNone(
            match,
            "SSRF CONFIRMED: dev regex allows internal network IPs",
        )

    def test_dev_regex_allows_docker_network(self):
        """DEV regex matches Docker bridge network 172.17.x."""
        match = self.ManifestDataType._URL_REGEX_DEV.match("http://172.17.0.2:5432/")
        self.assertIsNotNone(
            match,
            "SSRF CONFIRMED: dev regex allows Docker internal IPs",
        )

    @patch("manuspectrum.datatypes.manifest.django_settings")
    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_fetches_metadata_in_debug_mode(self, mock_get, mock_settings):
        """SSRF: validate() in DEBUG mode fetches cloud metadata directly."""
        mock_settings.DEBUG = True

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        self.datatype.validate("http://169.254.169.254/latest/meta-data/")

        mock_get.assert_called_once()
        actual_url = mock_get.call_args[0][0]
        self.assertIn(
            "169.254.169.254",
            actual_url,
            "SSRF CONFIRMED: validate in DEBUG mode directly fetches "
            "cloud metadata — no IP blocking",
        )


class TestSSRF_StrictRegexBypassViaRedirect(TestCase):
    """Prove the strict regex can be bypassed via redirect chains.

    Even in production (DEBUG=False), an attacker can:
    1. Provide https://evil.com/redirect (passes strict regex)
    2. evil.com returns 302 → http://169.254.169.254/...
    3. requests.get() follows the redirect
    """

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.ManifestDataType = ManifestDataType
            self.datatype = ManifestDataType()

    def test_strict_regex_accepts_attacker_domain(self):
        """Attacker-controlled domain passes the strict regex."""
        match = self.ManifestDataType._URL_REGEX_STRICT.match(
            "https://evil.com/redirect-to-metadata"
        )
        self.assertIsNotNone(
            match,
            "Attacker domain passes strict regex — redirect SSRF is possible",
        )

    @patch("manuspectrum.datatypes.manifest.django_settings")
    @patch("manuspectrum.datatypes.manifest.requests.get")
    def test_validate_strict_mode_blocks_redirects(self, mock_get, mock_settings):
        """In production (strict regex), redirects are disabled."""
        mock_settings.DEBUG = False

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_get.return_value = mock_response

        self.datatype.validate("https://evil.com/redirect-to-metadata")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        self.assertIn("allow_redirects", call_kwargs)
        self.assertFalse(
            call_kwargs["allow_redirects"],
            "PROTECTION: strict mode must block redirects to prevent SSRF bounce",
        )
