"""
Unit tests for ManifestDataType.

Tests IIIF v2/v3 manifest validation and transformation using real IIIF examples.

Usage:
    python manage.py test manuspectrum.tests.test_manifest_datatype
"""

import socket
import uuid
from unittest.mock import MagicMock, Mock, patch, call

from django.test import TestCase, override_settings
from django.utils import translation
import requests

from manuspectrum.utils.http import UnsafeURLError


def resolves_publicly():
    """Patch the guard's resolver so a test URL is reachable without DNS.

    The guard runs on every import path now, so a test whose subject is the
    import — not the guard — has to say where its host resolves. Tests that
    ARE about the guard use literal addresses and leave the resolver alone.
    """
    return patch(
        "manuspectrum.utils.http.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


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
    """Tests for manifest_registry.is_iiif_manifest."""

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.utils import manifest_registry

            self.registry = manifest_registry
            self.FailParsingManifestIIIF = manifest_registry.FailParsingManifestIIIF

    def test_valid_v3_manifest_returns_true(self):
        """A valid IIIF v3 manifest should return True."""
        result = self.registry.is_iiif_manifest(ManifestTestData.VALID_V3)
        self.assertTrue(result)

    def test_valid_v2_manifest_returns_true(self):
        """A valid IIIF v2 manifest should return True."""
        result = self.registry.is_iiif_manifest(ManifestTestData.VALID_V2)
        self.assertTrue(result)

    def test_minimal_v3_manifest_returns_true(self):
        """A minimal IIIF v3 manifest should return True."""
        result = self.registry.is_iiif_manifest(ManifestTestData.MINIMAL_V3)
        self.assertTrue(result)

    def test_minimal_v2_manifest_returns_true(self):
        """A minimal IIIF v2 manifest should return True."""
        result = self.registry.is_iiif_manifest(ManifestTestData.MINIMAL_V2)
        self.assertTrue(result)

    def test_non_dict_raises_exception(self):
        """A non-dict value should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.registry.is_iiif_manifest("not a dict")
        self.assertIn("not a dict", str(ctx.exception))

    def test_list_raises_exception(self):
        """A list value should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.registry.is_iiif_manifest([{"type": "Manifest"}])
        self.assertIn("not a dict", str(ctx.exception))

    def test_missing_context_raises_exception(self):
        """A manifest without valid @context should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.registry.is_iiif_manifest(ManifestTestData.INVALID_NO_CONTEXT)
        self.assertIn("no valid @context", str(ctx.exception))

    def test_wrong_type_v2_raises_exception(self):
        """A v2 manifest with wrong @type should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.registry.is_iiif_manifest(ManifestTestData.INVALID_WRONG_TYPE_V2)
        self.assertIn("invalid @type", str(ctx.exception))

    def test_wrong_type_v3_raises_exception(self):
        """A v3 manifest with wrong type should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.registry.is_iiif_manifest(ManifestTestData.INVALID_WRONG_TYPE_V3)
        self.assertIn("invalid type", str(ctx.exception))

    def test_none_raises_exception(self):
        """None should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF):
            self.registry.is_iiif_manifest(None)

    def test_empty_dict_raises_exception(self):
        """An empty dict should raise FailParsingManifestIIIF."""
        with self.assertRaises(self.FailParsingManifestIIIF):
            self.registry.is_iiif_manifest({})

    def test_v2_missing_type_raises_exception(self):
        """A v2 manifest missing @type should raise FailParsingManifestIIIF."""
        manifest = {
            "@context": "http://iiif.io/api/presentation/2/context.json",
            "@id": "http://example.org/manifest",
        }
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.registry.is_iiif_manifest(manifest)
        self.assertIn("invalid @type", str(ctx.exception))

    def test_v3_missing_type_raises_exception(self):
        """A v3 manifest missing type should raise FailParsingManifestIIIF."""
        manifest = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": "https://example.org/manifest",
        }
        with self.assertRaises(self.FailParsingManifestIIIF) as ctx:
            self.registry.is_iiif_manifest(manifest)
        self.assertIn("invalid type", str(ctx.exception))


class TestExtractManifestLabel(TestCase):
    """Tests for manifest label extraction."""

    def setUp(self):
        from manuspectrum.utils import manifest_registry

        self.registry = manifest_registry

    def test_extract_label_v3_full_manifest(self):
        """Extract label from full v3 manifest."""
        result = self.registry.extract_label(ManifestTestData.VALID_V3)
        self.assertEqual(result, "Book 1")

    def test_extract_label_v2_full_manifest(self):
        """Extract label from full v2 manifest (simple string)."""
        result = self.registry.extract_label(ManifestTestData.VALID_V2)
        self.assertEqual(result, "Book 1")

    def test_extract_label_v3_dict_with_en(self):
        """Extract dict label with 'en' key (IIIF v3 style)."""
        manifest = {"label": {"en": ["English Label"], "fr": ["French Label"]}}
        result = self.registry.extract_label(manifest)
        self.assertEqual(result, "English Label")

    def test_extract_label_v3_dict_with_none_key(self):
        """Extract dict label with 'none' key (language-independent)."""
        manifest = {"label": {"none": ["Universal Label"]}}
        result = self.registry.extract_label(manifest)
        self.assertEqual(result, "Universal Label")

    def test_extract_label_v3_dict_without_en_falls_back(self):
        """Extract dict label without 'en' key, falls back to first available."""
        manifest = {"label": {"de": ["German Label"]}}
        result = self.registry.extract_label(manifest)
        self.assertEqual(result, "German Label")

    def test_extract_label_v2_list_with_language(self):
        """Extract list label with @value/@language objects (IIIF v2 style)."""
        manifest = {
            "label": [
                {"@value": "English Title", "@language": "en"},
                {"@value": "Titre français", "@language": "fr"},
            ]
        }
        result = self.registry.extract_label(manifest)
        self.assertEqual(result, "English Title")

    def test_extract_label_list_of_strings(self):
        """Extract list of plain strings."""
        manifest = {"label": ["First Label", "Second Label"]}
        result = self.registry.extract_label(manifest)
        self.assertEqual(result, "First Label")

    def test_extract_label_from_none_returns_none(self):
        """Extracting from None manifest returns None."""
        result = self.registry.extract_label(None)
        self.assertIsNone(result)

    def test_extract_label_missing_returns_none(self):
        """Extracting from manifest without label returns None."""
        result = self.registry.extract_label({"id": "test"})
        self.assertIsNone(result)

    def test_extract_label_empty_list_returns_none(self):
        """Extracting from manifest with empty label list returns None."""
        manifest = {"label": []}
        result = self.registry.extract_label(manifest)
        self.assertIsNone(result)

    def test_extract_label_empty_dict_returns_none(self):
        """Extracting from manifest with empty label dict returns None."""
        manifest = {"label": {}}
        result = self.registry.extract_label(manifest)
        self.assertIsNone(result)


class TestExtractManifestDescription(TestCase):
    """Tests for manifest description extraction."""

    def setUp(self):
        from manuspectrum.utils import manifest_registry

        self.registry = manifest_registry

    def test_extract_description_v2_full_manifest(self):
        """Extract description from full v2 manifest."""
        result = self.registry.extract_description(ManifestTestData.VALID_V2)
        self.assertEqual(
            result,
            "A longer description of this example book. It should give some real information.",
        )

    def test_extract_summary_v3_full_manifest(self):
        """Extract summary from full v3 manifest (v3 uses 'summary' not 'description')."""
        result = self.registry.extract_description(ManifestTestData.VALID_V3)
        self.assertEqual(
            result, "Book 1, written be Anne Author, published in Paris around 1400."
        )

    def test_description_takes_precedence_over_summary(self):
        """When both exist, description should be used."""
        manifest = {
            "description": "Description text",
            "summary": {"en": ["Summary text"]},
        }
        result = self.registry.extract_description(manifest)
        self.assertEqual(result, "Description text")

    def test_extract_summary_v3_dict(self):
        """Extract v3 summary dict with language keys."""
        manifest = {"summary": {"en": ["English summary"], "fr": ["French summary"]}}
        result = self.registry.extract_description(manifest)
        self.assertEqual(result, "English summary")

    def test_extract_description_v2_list_with_language(self):
        """Extract list description with @value objects."""
        manifest = {
            "description": [{"@value": "English description", "@language": "en"}]
        }
        result = self.registry.extract_description(manifest)
        self.assertEqual(result, "English description")

    def test_extract_description_none_returns_none(self):
        """Extracting from None manifest returns None."""
        result = self.registry.extract_description(None)
        self.assertIsNone(result)

    def test_extract_description_missing_returns_none(self):
        """Extracting from manifest without description/summary returns None."""
        result = self.registry.extract_description({"label": "Test"})
        self.assertIsNone(result)


class TestManifestValidation(TestCase):
    """Tests for the validate method."""

    def setUp(self):
        # These assert on English message text. The datatype is called
        # directly, outside a request, so it inherits whatever language the
        # last client call activated — LocaleMiddleware activates and never
        # deactivates, and every page URL now carries a language.
        translation.activate("en")
        self.addCleanup(translation.deactivate)

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

    def test_validate_external_url_is_format_only(self):
        """validate() of an external URL is a pure FORMAT check — no network.

        IIIF compliance + reachability are checked in pre_tile_save (the
        side-effecting lifecycle hook), so validate() must not fetch.
        """
        errors = self.datatype.validate("https://example.org/iiif/book1/manifest")
        self.assertEqual(errors, [])

    def test_validate_external_url_bad_format_errors(self):
        """A malformed URL is rejected by the cheap format gate."""
        errors = self.datatype.validate("not a url")
        self.assertEqual(len(errors), 1)
        self.assertIn("Invalid URL format", str(errors[0]["message"]))

    def test_validate_does_not_create_manifest(self):
        """validate() must NOT create an IIIFManifest (creation is in pre_tile_save)."""
        with patch(
            "manuspectrum.datatypes.manifest.IIIFManifest"
        ) as mock_manifest_model:
            self.datatype.validate("https://example.org/iiif/book1/manifest")
            mock_manifest_model.objects.create.assert_not_called()

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

    def test_validate_dict_with_manifest_url(self):
        """Validating a dict with a well-formed manifest_url passes (format only)."""
        errors = self.datatype.validate(
            {"manifest_url": "https://example.org/iiif/book1/manifest"}
        )
        self.assertEqual(errors, [])

    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_validate_local_path_passes_when_exists(self, mock_manifest_model):
        """Local path /manifest/{uuid} should pass if manifest exists by globalid."""
        mock_manifest_model.objects.filter.return_value.first.return_value = MagicMock()

        errors = self.datatype.validate(
            "/manifest/ceaf19e3-e1c5-4638-af81-b79562d33787"
        )
        self.assertEqual(errors, [])
        mock_manifest_model.objects.filter.assert_called_once_with(
            globalid="ceaf19e3-e1c5-4638-af81-b79562d33787"
        )

    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_validate_local_path_with_host_passes(self, mock_manifest_model):
        """Full local URL http://host/manifest/{uuid} should also validate by globalid."""
        mock_manifest_model.objects.filter.return_value.first.return_value = MagicMock()

        errors = self.datatype.validate(
            "http://localhost:8000/manifest/ceaf19e3-e1c5-4638-af81-b79562d33787"
        )
        self.assertEqual(errors, [])
        mock_manifest_model.objects.filter.assert_called_once_with(
            globalid="ceaf19e3-e1c5-4638-af81-b79562d33787"
        )

    @override_settings(
        PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/",
        ALLOWED_HOSTS=["manuspectrum.example", "internal.example"],
    )
    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_validate_allowed_host_route_resolves_by_globalid(
        self, mock_manifest_model
    ):
        mock_manifest_model.objects.filter.return_value.first.return_value = None

        errors = self.datatype.validate(
            "http://internal.example:8000/iiif/manifest/ceaf19e3-e1c5-4638-af81-b79562d33787"
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0]["message"].lower())
        mock_manifest_model.objects.filter.assert_called_once_with(
            globalid="ceaf19e3-e1c5-4638-af81-b79562d33787"
        )

    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_validate_local_path_fails_when_not_found(self, mock_manifest_model):
        """Local path should fail if the manifest globalid is not in DB."""
        mock_manifest_model.objects.filter.return_value.first.return_value = None

        errors = self.datatype.validate(
            "/manifest/ceaf19e3-e1c5-4638-af81-b79562d33787"
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0]["message"].lower())


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

    def display(self, value):
        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = MagicMock()
        tile.data = {str(node.nodeid): value}
        return self.datatype.get_display_value(tile, node)

    def stored(self, label, url=None):
        from arches.app.models.models import IIIFManifest

        globalid = uuid.uuid4()
        return IIIFManifest.objects.create(
            globalid=globalid,
            label=label,
            url=url or f"/manifest/{globalid}",
            manifest={},
        )

    def test_an_imported_manifest_shows_its_publisher_url(self):
        original = "https://emmsm.unicaen.fr/manifests/Avranches_BM_59.json"
        row = self.stored("Avranches 59", original)

        self.assertEqual(
            self.display(f"/manifest/{row.globalid}"),
            f"Avranches 59 ({original})",
        )

    def test_a_manifest_created_here_shows_its_public_iiif_url(self):
        from manuspectrum.iiif import ids

        row = self.stored("Imaging")

        self.assertEqual(
            self.display(f"/manifest/{row.globalid}"),
            f"Imaging ({ids.stored_manifest(row.globalid)})",
        )

    def test_an_absolute_local_url_is_resolved_by_globalid(self):
        from django.conf import settings

        original = "https://example.org/iiif/book1/manifest"
        row = self.stored("Book 1", original)

        self.assertEqual(
            self.display(f"{settings.PUBLIC_SERVER_ADDRESS}manifest/{row.globalid}"),
            f"Book 1 ({original})",
        )

    def test_a_raw_external_url_with_a_row_shows_the_row(self):
        url = "https://example.org/iiif/book1/manifest"
        self.stored("Book 1", url)

        self.assertEqual(self.display(url), f"Book 1 ({url})")

    def test_an_unknown_value_is_shown_as_is(self):
        url = "https://example.org/iiif/unknown/manifest"
        self.assertEqual(self.display(url), url)
        missing = f"/manifest/{uuid.uuid4()}"
        self.assertEqual(self.display(missing), missing)

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

    def test_get_display_value_with_dict_tile(self):
        """Search export passes tiles as dicts (ES _source), not Tile objects."""
        original = "https://example.org/iiif/book1/manifest"
        row = self.stored("Book 1", original)
        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = {
            "data": {str(node.nodeid): f"/manifest/{row.globalid}"},
            "provisionaledits": None,
        }

        self.assertEqual(
            self.datatype.get_display_value(tile, node), f"Book 1 ({original})"
        )

    def test_get_display_value_dict_tile_missing_node_returns_none(self):
        """Dict tile without the node in its data should return None."""
        node = MagicMock()
        node.nodeid = uuid.uuid4()
        tile = {"data": {"other_node": "value"}, "provisionaledits": None}

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


class TestURLFormatGate(TestCase):
    """The cheap, network-free URL FORMAT gate (URLValidator).

    Host / private-IP / SSRF policy is NOT here — it lives in
    manuspectrum.utils.http.assert_url_is_safe (see tests/test_http.py).
    """

    def setUp(self):
        from manuspectrum.utils import manifest_registry

        self.manifest = manifest_registry

    def _ok(self, url):
        from django.core.exceptions import ValidationError

        try:
            self.manifest.check_url_format(url)
            return True
        except ValidationError:
            return False

    def test_accepts_valid_https(self):
        self.assertTrue(self._ok("https://example.org/iiif/book1/manifest"))

    def test_accepts_localhost(self):
        # Permissive about hosts on purpose; host policy is the guard's job.
        self.assertTrue(self._ok("http://localhost:8000/manifest/abc"))

    def test_rejects_non_url(self):
        self.assertFalse(self._ok("iiif/book1/manifest"))

    def test_rejects_non_http_scheme(self):
        self.assertFalse(self._ok("ftp://example.org/x"))

    def test_rejects_trailing_garbage(self):
        # URLValidator is anchored, unlike the old start-anchored .match().
        self.assertFalse(self._ok("https://example.org/x with space"))


class TestLocalManifestMatch(TestCase):
    """Host-aware detection of local manifest references (``manifest_registry.local_row``)."""

    UUID = "ceaf19e3-e1c5-4638-af81-b79562d33787"

    def is_local(self, url):
        from manuspectrum.utils.manifest_registry import local_row

        return local_row(url)[0]

    def test_relative_path_is_local(self):
        self.assertTrue(self.is_local(f"/manifest/{self.UUID}"))

    @override_settings(PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/")
    def test_canonical_host_is_local(self):
        self.assertTrue(
            self.is_local(f"https://manuspectrum.example/manifest/{self.UUID}")
        )

    @override_settings(PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/")
    def test_foreign_host_is_not_local(self):
        self.assertFalse(self.is_local(f"http://evil.com/manifest/{self.UUID}"))

    @override_settings(PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/")
    def test_userinfo_trick_does_not_bypass(self):
        self.assertFalse(
            self.is_local(f"https://manuspectrum.example@evil.com/manifest/{self.UUID}")
        )

    def test_non_manifest_url_is_not_local(self):
        self.assertFalse(self.is_local("https://example.org/iiif/manifest"))

    def test_relative_iiif_route_is_local(self):
        self.assertTrue(self.is_local(f"/iiif/manifest/{self.UUID}"))

    @override_settings(PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/")
    def test_iiif_route_on_canonical_host_is_local(self):
        self.assertTrue(
            self.is_local(f"https://manuspectrum.example/iiif/manifest/{self.UUID}")
        )

    @override_settings(PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/")
    def test_iiif_route_on_foreign_host_is_not_local(self):
        self.assertFalse(self.is_local(f"https://evil.com/iiif/manifest/{self.UUID}"))


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

    def test_foreign_host_url_unchanged(self):
        # A non-canonical host is NOT collapsed to a relative path; it stays
        # absolute so it is treated as external.
        result = self.ManifestDataType._to_relative_path(
            "https://example.org/iiif/book1/manifest"
        )
        self.assertEqual(result, "https://example.org/iiif/book1/manifest")

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

    @patch("manuspectrum.utils.manifest_registry.fetch_iiif_manifest")
    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_pre_tile_save_imports_external_manifest_as_local(
        self, mock_manifest_model, mock_fetch
    ):
        """pre_tile_save should import external manifest and store local path."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "https://example.org/iiif/book1/manifest"}

        mock_response = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_response.raise_for_status = MagicMock()
        mock_fetch.return_value = mock_response

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

        with resolves_publicly():
            self.datatype.pre_tile_save(tile, nodeid)

        mock_manifest_model.objects.create.assert_called_once()
        create_kwargs = mock_manifest_model.objects.create.call_args[1]
        self.assertEqual(create_kwargs["label"], "Book 1")
        self.assertEqual(tile.data[nodeid], f"/manifest/{created_globalid}")


@override_settings(PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/")
class TestLocalReferenceToStoredManifest(TestCase):
    """A URL the IIIF output publishes resolves to the stored row, never fetched.

    The IIIF output names a stored manifest /iiif/manifest/{uuid} (imaging
    Manifest bodies, target partOf/within). A curator who pastes that URL
    into a manifest widget must get the existing IIIFManifest back: fetching
    it from our own site would import a duplicate. The canonical host is a
    public name here (it resolves publicly in production), so without the
    local resolution the datatype would go on to fetch it.
    """

    def setUp(self):
        translation.activate("en")
        self.addCleanup(translation.deactivate)
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()
        from arches.app.models.models import IIIFManifest
        from manuspectrum.iiif import ids

        self.IIIFManifest = IIIFManifest
        self.ids = ids
        # Created with Arches' Image Service Manager: its url is the local path.
        globalid = uuid.uuid4()
        self.created = IIIFManifest.objects.create(
            globalid=globalid,
            url=f"/manifest/{globalid}",
            label="Imaging",
            manifest=ManifestTestData.VALID_V3,
        )
        # Imported from another site: its url is the publisher's URL, while
        # tiles (and so the IIIF output) name it by its globalid.
        self.imported = IIIFManifest.objects.create(
            globalid=uuid.uuid4(),
            url="https://example.org/iiif/book1/manifest",
            label="Book 1",
            manifest=ManifestTestData.VALID_V3,
        )

        # Were the URL fetched, it would answer the stored JSON, as our own
        # site does: the datatype would then import it as a new manifest.
        resolver = resolves_publicly()
        resolver.start()
        self.addCleanup(resolver.stop)
        response = MagicMock()
        response.json.return_value = ManifestTestData.VALID_V3
        fetcher = patch(
            "manuspectrum.utils.manifest_registry.fetch_iiif_manifest",
            return_value=response,
        )
        self.fetch = fetcher.start()
        self.addCleanup(fetcher.stop)

    def _pre_tile_save(self, value):
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: value}
        self.datatype.pre_tile_save(tile, nodeid)
        return tile.data[nodeid]

    def _assert_resolves(self, value, manifest):
        before = self.IIIFManifest.objects.count()
        stored = self._pre_tile_save(value)
        self.fetch.assert_not_called()
        self.assertEqual(self.IIIFManifest.objects.count(), before)
        self.assertEqual(stored, f"/manifest/{manifest.globalid}")

    def test_the_published_url_resolves_to_the_stored_manifest(self):
        url = self.ids.stored_manifest(self.created.globalid)
        self.assertTrue(url.startswith("https://manuspectrum.example/iiif/manifest/"))
        self._assert_resolves(url, self.created)

    def test_the_relative_route_resolves_to_the_stored_manifest(self):
        self._assert_resolves(f"/iiif/manifest/{self.created.globalid}", self.created)

    def test_an_imported_manifest_named_by_the_route_is_not_imported_again(self):
        self._assert_resolves(
            self.ids.stored_manifest(self.imported.globalid), self.imported
        )

    def test_every_local_form_resolves_by_globalid(self):
        # The row's url is no key: an imported manifest keeps its
        # publisher's URL there, while its tiles store /manifest/{globalid}.
        for value, manifest in (
            (f"/manifest/{self.imported.globalid}", self.imported),
            (f"/en/manifest/{self.created.globalid}", self.created),
            (
                f"https://manuspectrum.example/fr/manifest/{self.imported.globalid}",
                self.imported,
            ),
        ):
            with self.subTest(value=value):
                self._assert_resolves(value, manifest)

    def test_an_unknown_manifest_on_the_route_is_an_error_not_a_fetch(self):
        from manuspectrum.datatypes.manifest import FailParsingManifestIIIF

        before = self.IIIFManifest.objects.count()
        with self.assertRaisesMessage(FailParsingManifestIIIF, "Manifest not found"):
            self._pre_tile_save(self.ids.stored_manifest(uuid.uuid4()))
        self.fetch.assert_not_called()
        self.assertEqual(self.IIIFManifest.objects.count(), before)

    def test_validate_accepts_the_relative_route(self):
        self.assertEqual(
            self.datatype.validate(f"/iiif/manifest/{self.created.globalid}"), []
        )

    def test_validate_reports_an_unknown_manifest_on_the_route(self):
        errors = self.datatype.validate(self.ids.stored_manifest(uuid.uuid4()))
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", str(errors[0]["message"]).lower())


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

    @patch("manuspectrum.utils.manifest_registry.fetch_iiif_manifest")
    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_pre_tile_save_uses_resilient_fetch(self, mock_manifest_model, mock_fetch):
        """pre_tile_save() fetches external manifests via the resilient helper.

        allow_redirects=False (the redirect-SSRF guard) is enforced inside
        fetch_iiif_manifest — asserted in tests/test_http.py.
        """
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "https://evil.com/ssrf-redirect"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = ManifestTestData.VALID_V3
        mock_fetch.return_value = mock_response

        with resolves_publicly():
            self.datatype.pre_tile_save(tile, nodeid)

        mock_fetch.assert_called_once_with("https://evil.com/ssrf-redirect")


class TestSSRF_PreTileSaveURLValidation(TestCase):
    """Verify that pre_tile_save() now validates URLs with the regex
    before fetching, blocking private IPs and invalid URLs.
    """

    def setUp(self):
        with patch("arches.app.models.models.Widget") as mock_widget:
            mock_widget.objects.get.return_value = MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

            self.datatype = ManifestDataType()

    @override_settings(SSRF_ALLOW_PRIVATE=False)
    @patch("manuspectrum.utils.manifest_registry.fetch_iiif_manifest")
    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_pre_tile_save_blocks_private_ip(self, mock_manifest_model, mock_fetch):
        """The SSRF guard blocks private IPs (e.g. 192.168.1.1).

        The strict regex matches dotted IPs, but assert_url_is_safe() resolves
        the host and rejects the non-public address before any fetch happens.
        """
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "http://192.168.1.1/admin"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        # SSRF guard rejects the private IP → pre_tile_save raises (rollback),
        # and no outbound request is made.
        with self.assertRaises(UnsafeURLError):
            self.datatype.pre_tile_save(tile, nodeid)
        mock_fetch.assert_not_called()

    @override_settings(SSRF_ALLOW_PRIVATE=False)
    @patch("manuspectrum.utils.manifest_registry.fetch_iiif_manifest")
    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_pre_tile_save_blocks_cloud_metadata(self, mock_manifest_model, mock_fetch):
        """The SSRF guard blocks the cloud-metadata endpoint.

        169.254.169.254 passes the strict regex (dots in char class) but is a
        link-local address, so assert_url_is_safe() rejects it before fetching.
        """
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "http://169.254.169.254/latest/meta-data/"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        # SSRF guard rejects the metadata IP → pre_tile_save raises, no fetch.
        with self.assertRaises(UnsafeURLError):
            self.datatype.pre_tile_save(tile, nodeid)
        mock_fetch.assert_not_called()

    @override_settings(SSRF_ALLOW_PRIVATE=False)
    @patch("manuspectrum.utils.manifest_registry.fetch_iiif_manifest")
    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_pre_tile_save_blocks_localhost(self, mock_manifest_model, mock_fetch):
        """pre_tile_save() must reject localhost URLs."""
        nodeid = str(uuid.uuid4())
        tile = MagicMock()
        tile.data = {nodeid: "http://localhost:6379/"}

        mock_filter_none = MagicMock()
        mock_filter_none.first.return_value = None
        mock_manifest_model.objects.filter.return_value = mock_filter_none

        # localhost resolves to a loopback address → SSRF guard raises.
        with self.assertRaises(UnsafeURLError):
            self.datatype.pre_tile_save(tile, nodeid)
        mock_fetch.assert_not_called()

    @patch("manuspectrum.utils.manifest_registry.fetch_iiif_manifest")
    @patch("manuspectrum.utils.manifest_registry.IIIFManifest")
    def test_pre_tile_save_allows_valid_external_url(
        self, mock_manifest_model, mock_fetch
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
        mock_fetch.return_value = mock_response

        with resolves_publicly():
            self.datatype.pre_tile_save(tile, nodeid)

        mock_fetch.assert_called_once()
