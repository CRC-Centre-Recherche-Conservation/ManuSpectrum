"""
Unit tests for ManifestDataType.

Tests IIIF v2/v3 manifest validation and transformation using real IIIF examples.

Usage:
    python manage.py test manuspectrum.tests.test_manifest_datatype
"""
import uuid
from unittest.mock import MagicMock, Mock, patch

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
            {
                "label": {"en": ["Author"]},
                "value": {"none": ["Anne Author"]}
            },
            {
                "label": {"en": ["Published"]},
                "value": {
                    "en": ["Paris, circa 1400"],
                    "fr": ["Paris, environ 1400"]
                }
            },
            {
                "label": {"en": ["Notes"]},
                "value": {
                    "en": ["Text of note 1", "Text of note 2"]
                }
            }
        ],
        "summary": {"en": ["Book 1, written be Anne Author, published in Paris around 1400."]},
        "thumbnail": [
            {
                "id": "https://example.org/iiif/book1/page1/full/80,100/0/default.jpg",
                "type": "Image",
                "format": "image/jpeg",
                "service": [
                    {
                        "id": "https://example.org/iiif/book1/page1",
                        "type": "ImageService3",
                        "profile": "level1"
                    }
                ]
            }
        ],
        "viewingDirection": "right-to-left",
        "behavior": ["paged"],
        "navDate": "1856-01-01T00:00:00Z",
        "rights": "https://creativecommons.org/licenses/by/4.0/",
        "requiredStatement": {
            "label": {"en": ["Attribution"]},
            "value": {"en": ["Provided by Example Organization"]}
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
                        "format": "text/html"
                    }
                ]
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
                                    "width": 1500
                                },
                                "target": "https://example.org/iiif/book1/canvas/p1"
                            }
                        ]
                    }
                ]
            },
            {
                "id": "https://example.org/iiif/book1/canvas/p2",
                "type": "Canvas",
                "label": {"none": ["p. 2"]},
                "height": 1000,
                "width": 750
            }
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
                        "label": {"en": ["Introduction"]}
                    }
                ]
            }
        ]
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
                    {"@value": "Paris, environ 14eme siecle", "@language": "fr"}
                ]
            }
        ],
        "description": "A longer description of this example book. It should give some real information.",
        "navDate": "1856-01-01T00:00:00Z",
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution": "Provided by Example Organization",
        "service": {
            "@context": "http://example.org/ns/jsonld/context.json",
            "@id": "http://example.org/service/example",
            "profile": "http://example.org/docs/example-service.html"
        },
        "seeAlso": {
            "@id": "http://example.org/library/catalog/book1.marc",
            "format": "application/marc",
            "profile": "http://example.org/profiles/marc21"
        },
        "rendering": {
            "@id": "http://example.org/iiif/book1.pdf",
            "label": "Download as PDF",
            "format": "application/pdf"
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
                                    "width": 1500
                                },
                                "on": "http://example.org/iiif/book1/canvas/p1"
                            }
                        ]
                    },
                    {
                        "@id": "http://example.org/iiif/book1/canvas/p2",
                        "@type": "sc:Canvas",
                        "label": "p. 2",
                        "height": 1000,
                        "width": 750
                    },
                    {
                        "@id": "http://example.org/iiif/book1/canvas/p3",
                        "@type": "sc:Canvas",
                        "label": "p. 3",
                        "height": 1000,
                        "width": 750
                    }
                ]
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
                    "http://example.org/iiif/book1/canvas/p3#xywh=0,0,750,300"
                ]
            }
        ]
    }

    # Invalid manifests for testing error cases
    INVALID_NO_CONTEXT = {
        "type": "Manifest",
        "label": {"en": ["No context manifest"]}
    }

    INVALID_WRONG_TYPE_V2 = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Collection",
        "@id": "http://example.org/collection"
    }

    INVALID_WRONG_TYPE_V3 = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "type": "Collection",
        "id": "https://example.org/collection"
    }

    # Minimal valid manifests
    MINIMAL_V2 = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "@id": "http://example.org/manifest"
    }

    MINIMAL_V3 = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "type": "Manifest",
        "id": "https://example.org/manifest"
    }


class TestIsIIIFManifest(TestCase):
    """Tests for the is_iiif_manifest static method."""

    def setUp(self):
        with patch('arches.app.models.models.Widget') as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import (
                ManifestDataType,
                FailParsingManifestIIIF
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
            self.ManifestDataType.is_iiif_manifest(ManifestTestData.INVALID_WRONG_TYPE_V2)
        self.assertIn("invalid @type", str(ctx.exception))

    def test_wrong_type_v3_raises_exception(self):
        """A v3 manifest with wrong type should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest(ManifestTestData.INVALID_WRONG_TYPE_V3)
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
            "@id": "http://example.org/manifest"
        }
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest(manifest)
        self.assertIn("invalid @type", str(ctx.exception))

    def test_v3_missing_type_raises_exception(self):
        """A v3 manifest missing type should raise FailParsingManifestIIIF."""
        manifest = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": "https://example.org/manifest"
        }
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.ManifestDataType.is_iiif_manifest(manifest)
        self.assertIn("invalid type", str(ctx.exception))


class TestExtractManifestLabel(TestCase):
    """Tests for manifest label extraction."""

    def setUp(self):
        with patch('arches.app.models.models.Widget') as mock_widget:
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
                {"@value": "Titre français", "@language": "fr"}
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
        with patch('arches.app.models.models.Widget') as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType
            self.datatype = ManifestDataType()

    def test_extract_description_v2_full_manifest(self):
        """Extract description from full v2 manifest."""
        result = self.datatype._extract_manifest_description(ManifestTestData.VALID_V2)
        self.assertEqual(
            result,
            "A longer description of this example book. It should give some real information."
        )

    def test_extract_summary_v3_full_manifest(self):
        """Extract summary from full v3 manifest (v3 uses 'summary' not 'description')."""
        result = self.datatype._extract_manifest_description(ManifestTestData.VALID_V3)
        self.assertEqual(
            result,
            "Book 1, written be Anne Author, published in Paris around 1400."
        )

    def test_description_takes_precedence_over_summary(self):
        """When both exist, description should be used."""
        manifest = {
            "description": "Description text",
            "summary": {"en": ["Summary text"]}
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
            "description": [
                {"@value": "English description", "@language": "en"}
            ]
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
        with patch('arches.app.models.models.Widget') as mock_widget:
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

    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_validate_existing_manifest_id(self, mock_manifest_model):
        """Validating an existing manifest UUID should succeed."""
        test_uuid = str(uuid.uuid4())
        mock_manifest_model.objects.get.return_value = MagicMock()

        errors = self.datatype.validate(test_uuid)
        self.assertEqual(errors, [])
        mock_manifest_model.objects.get.assert_called_once_with(id=test_uuid)

    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_validate_nonexistent_manifest_id(self, mock_manifest_model):
        """Validating a non-existent manifest UUID should return an error."""
        test_uuid = str(uuid.uuid4())
        # Setup DoesNotExist as a real exception class before using as side_effect
        mock_manifest_model.DoesNotExist = Exception
        mock_manifest_model.objects.get.side_effect = mock_manifest_model.DoesNotExist("Not found")

        errors = self.datatype.validate(test_uuid)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['type'], 'ERROR')
        self.assertIn('does not exist', str(errors[0]['message']))

    def test_validate_invalid_url_format(self):
        """Validating an invalid URL should return an error."""
        errors = self.datatype.validate("not-a-valid-url")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['type'], 'ERROR')

    @patch('manuspectrum.datatypes.manifest.requests.get')
    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_validate_url_with_valid_v3_manifest(self, mock_manifest_model, mock_get):
        """Validating a URL that returns a valid v3 manifest should succeed."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        mock_manifest_model.objects.get_or_create.return_value = (MagicMock(), True)

        errors = self.datatype.validate("https://example.org/iiif/book1/manifest")
        self.assertEqual(errors, [])

    @patch('manuspectrum.datatypes.manifest.requests.get')
    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_validate_url_with_valid_v2_manifest(self, mock_manifest_model, mock_get):
        """Validating a URL that returns a valid v2 manifest should succeed."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V2
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        mock_manifest_model.objects.get_or_create.return_value = (MagicMock(), True)

        errors = self.datatype.validate("http://example.org/iiif/book1/manifest")
        self.assertEqual(errors, [])

    @patch('manuspectrum.datatypes.manifest.requests.get')
    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_validate_url_creates_manifest_record(self, mock_manifest_model, mock_get):
        """Validating a URL should create IIIFManifest record with extracted data."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        mock_manifest_model.objects.get_or_create.return_value = (MagicMock(), True)

        self.datatype.validate("https://example.org/iiif/book1/manifest")

        mock_manifest_model.objects.get_or_create.assert_called_once()
        call_kwargs = mock_manifest_model.objects.get_or_create.call_args
        defaults = call_kwargs[1]['defaults']
        self.assertEqual(defaults['label'], "Book 1")

    @patch('manuspectrum.datatypes.manifest.requests.get')
    def test_validate_url_timeout(self, mock_get):
        """Validating a URL that times out should return an error."""
        mock_get.side_effect = requests.Timeout()

        errors = self.datatype.validate("https://example.org/iiif/book1/manifest")
        self.assertEqual(len(errors), 1)
        self.assertIn('Timeout', str(errors[0]['message']))

    @patch('manuspectrum.datatypes.manifest.requests.get')
    def test_validate_url_connection_error(self, mock_get):
        """Validating a URL with connection error should return an error."""
        mock_get.side_effect = requests.ConnectionError()

        errors = self.datatype.validate("https://example.org/iiif/book1/manifest")
        self.assertEqual(len(errors), 1)

    @patch('manuspectrum.datatypes.manifest.requests.get')
    def test_validate_url_invalid_manifest_no_context(self, mock_get):
        """Validating a URL that returns manifest without @context should error."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.INVALID_NO_CONTEXT
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        errors = self.datatype.validate("https://example.org/iiif/invalid/manifest")
        self.assertEqual(len(errors), 1)
        self.assertIn('Invalid IIIF manifest', str(errors[0]['message']))

    @patch('manuspectrum.datatypes.manifest.requests.get')
    def test_validate_url_wrong_type_v2(self, mock_get):
        """Validating a URL that returns v2 Collection should error."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.INVALID_WRONG_TYPE_V2
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        errors = self.datatype.validate("http://example.org/collection")
        self.assertEqual(len(errors), 1)
        self.assertIn('Invalid IIIF manifest', str(errors[0]['message']))

    def test_validate_dict_without_id_or_url_returns_error(self):
        """Validating a dict without manifest_id or manifest_url should error."""
        errors = self.datatype.validate({"invalid_key": "value"})
        self.assertEqual(len(errors), 1)
        self.assertIn('must have a URL or ID', str(errors[0]['message']))

    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_validate_dict_with_manifest_id(self, mock_manifest_model):
        """Validating a dict with manifest_id should check existence."""
        test_uuid = str(uuid.uuid4())
        mock_manifest_model.objects.get.return_value = MagicMock()

        errors = self.datatype.validate({"manifest_id": test_uuid})
        self.assertEqual(errors, [])

    @patch('manuspectrum.datatypes.manifest.requests.get')
    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_validate_dict_with_manifest_url(self, mock_manifest_model, mock_get):
        """Validating a dict with manifest_url should fetch and validate."""
        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        mock_manifest_model.objects.get_or_create.return_value = (MagicMock(), True)

        errors = self.datatype.validate(
            {"manifest_url": "https://example.org/iiif/book1/manifest"}
        )
        self.assertEqual(errors, [])


class TestTransformValueForTile(TestCase):
    """Tests for transform_value_for_tile method."""

    def setUp(self):
        with patch('arches.app.models.models.Widget') as mock_widget:
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

    def test_transform_valid_uuid_string(self):
        """Transforming a valid UUID string should return it unchanged."""
        test_uuid = str(uuid.uuid4())
        result = self.datatype.transform_value_for_tile(test_uuid)
        self.assertEqual(result, test_uuid)

    def test_transform_dict_with_manifest_id(self):
        """Transforming a dict with manifest_id should return the UUID."""
        test_uuid = str(uuid.uuid4())
        result = self.datatype.transform_value_for_tile({"manifest_id": test_uuid})
        self.assertEqual(result, test_uuid)

    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_transform_dict_with_manifest_url(self, mock_manifest_model):
        """Transforming a dict with manifest_url should lookup and return UUID."""
        test_uuid = uuid.uuid4()
        mock_manifest = MagicMock()
        mock_manifest.id = test_uuid
        mock_manifest_model.objects.get.return_value = mock_manifest

        result = self.datatype.transform_value_for_tile(
            {"manifest_url": "https://example.org/iiif/book1/manifest"}
        )
        self.assertEqual(result, str(test_uuid))

    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_transform_url_string(self, mock_manifest_model):
        """Transforming a URL string should lookup and return UUID."""
        test_uuid = uuid.uuid4()
        mock_manifest = MagicMock()
        mock_manifest.id = test_uuid
        mock_manifest_model.objects.get.return_value = mock_manifest

        result = self.datatype.transform_value_for_tile(
            "https://example.org/iiif/book1/manifest"
        )
        self.assertEqual(result, str(test_uuid))

    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_transform_nonexistent_url_returns_none(self, mock_manifest_model):
        """Transforming a URL that doesn't exist should return None."""
        # Setup DoesNotExist as a real exception class before using as side_effect
        mock_manifest_model.DoesNotExist = Exception
        mock_manifest_model.objects.get.side_effect = mock_manifest_model.DoesNotExist("Not found")

        result = self.datatype.transform_value_for_tile(
            "https://example.org/iiif/unknown/manifest"
        )
        self.assertIsNone(result)


class TestGetDisplayValue(TestCase):
    """Tests for get_display_value method."""

    def setUp(self):
        with patch('arches.app.models.models.Widget') as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType
            self.datatype = ManifestDataType()

    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_get_display_value_with_url(self, mock_manifest_model):
        """Display value should include label and URL."""
        mock_manifest = MagicMock()
        mock_manifest.label = "Book 1"
        mock_manifest.url = "https://example.org/iiif/book1/manifest"
        mock_manifest_model.objects.get.return_value = mock_manifest

        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = MagicMock()
        tile.data = {str(node.nodeid): str(uuid.uuid4())}

        result = self.datatype.get_display_value(tile, node)
        self.assertIn("Book 1", result)
        self.assertIn("https://example.org/iiif/book1/manifest", result)

    @patch('manuspectrum.datatypes.manifest.IIIFManifest')
    def test_get_display_value_without_url(self, mock_manifest_model):
        """Display value without URL should show label only."""
        mock_manifest = MagicMock()
        mock_manifest.label = "Book 1"
        mock_manifest.url = None
        mock_manifest_model.objects.get.return_value = mock_manifest

        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = MagicMock()
        tile.data = {str(node.nodeid): str(uuid.uuid4())}

        result = self.datatype.get_display_value(tile, node)
        self.assertEqual(result, "Book 1")

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
        with patch('arches.app.models.models.Widget') as mock_widget:
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
        with patch('arches.app.models.models.Widget') as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType
            self.ManifestDataType = ManifestDataType

    def test_valid_https_url(self):
        """HTTPS URLs should match."""
        self.assertIsNotNone(
            self.ManifestDataType.URL_REGEX.match(
                "https://example.org/iiif/book1/manifest"
            )
        )

    def test_unvalid_https_url(self):
        """Unvalid HTTPS URLs should not match."""
        self.assertIsNone(
            self.ManifestDataType.URL_REGEX.match(
                "iiif/book1/manifest"
            )
        )



class TestGetPrefLabel(TestCase):
    """Tests for get_pref_label class method."""

    def setUp(self):
        with patch('arches.app.models.models.Widget') as mock_widget:
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
        with patch('arches.app.models.models.Widget') as mock_widget:
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