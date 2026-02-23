"""
Unit tests for IIIFAnnotationSerializer.

Tests IIIF Presentation API v3 annotation building and batch processing.

Usage:
    python manage.py test tests.test_iiif_annotation_serializer
"""

import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestIIIFAnnotationSerializerSetup(TestCase):
    """Base class with common setup for serializer tests."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer
        self.serializer._clear_caches()
        self.serializer._batch_mode = False


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestToRepresentation(TestCase):
    """Tests for the to_representation method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer
        self.serializer._clear_caches()
        self.serializer._batch_mode = False

    def test_basic_annotation_structure(self):
        """Annotation should have required IIIF v3 fields."""
        resource_id = str(uuid.uuid4())
        target = "https://example.com/canvas/1#xywh=100,100,200,200"

        with patch.object(self.serializer, "_get_resource_tiles", return_value={}):
            result = self.serializer.to_representation(target, resource_id)

        self.assertEqual(
            result["@context"], "http://iiif.io/api/presentation/3/context.json"
        )
        self.assertEqual(result["type"], "Annotation")
        self.assertEqual(result["motivation"], "supplementing")
        self.assertIn(resource_id, result["id"])

        # Target with fragment should be a SpecificResource (IIIF v3)
        self.assertEqual(result["target"]["type"], "SpecificResource")
        self.assertEqual(
            result["target"]["source"]["id"], "https://example.com/canvas/1"
        )
        self.assertEqual(result["target"]["source"]["type"], "Canvas")
        self.assertEqual(result["target"]["selector"]["type"], "FragmentSelector")
        self.assertEqual(result["target"]["selector"]["value"], "xywh=100,100,200,200")

    def test_annotation_without_resource_id(self):
        """Annotation without resource_id should have fallback body."""
        target = "https://example.com/canvas/1"

        result = self.serializer.to_representation(target, resource_id="")

        self.assertEqual(result["body"]["type"], "TextualBody")
        self.assertEqual(result["body"]["value"], "No data available")
        self.assertEqual(result["body"]["format"], "text/plain")

    @patch("manuspectrum.views.serializers.iiif_annotation.Tile")
    def test_annotation_with_name_label(self, mock_tile):
        """Annotation should include label from name node."""
        resource_id = str(uuid.uuid4())
        name_node = self.serializer.DATATYPE_NODES["name"]

        tiles_data = {
            name_node: {
                "en": {"value": "Analysis Name"},
                "fr": {"value": "Nom de l'analyse"},
            }
        }

        with patch.object(
            self.serializer, "_get_resource_tiles", return_value=tiles_data
        ):
            result = self.serializer.to_representation(
                "https://example.com/canvas/1", resource_id
            )

        self.assertIn("label", result)
        self.assertEqual(result["label"]["en"], ["Analysis Name"])

    def test_annotation_includes_see_also(self):
        """Annotation should include seeAlso with report link."""
        resource_id = str(uuid.uuid4())

        with patch.object(self.serializer, "_get_resource_tiles", return_value={}):
            result = self.serializer.to_representation(
                "https://example.com/canvas/1", resource_id
            )

        self.assertIn("seeAlso", result)
        see_also_ids = [item["id"] for item in result["seeAlso"]]
        self.assertTrue(any(resource_id in id for id in see_also_ids))


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestBuildBody(TestCase):
    """Tests for the _build_body method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer
        self.serializer._clear_caches()
        self.serializer._batch_mode = False

    @patch("manuspectrum.views.serializers.iiif_annotation.IIIFManifest")
    def test_body_with_manifest(self, mock_manifest_model):
        """Body should be Manifest type when manifest node is present."""
        manifest_node = self.serializer.DATATYPE_NODES["manifest"]
        manifest_url = "https://example.com/manifest.json"

        mock_manifest = MagicMock()
        mock_manifest.label = "Test Manifest"
        mock_manifest_model.objects.get.return_value = mock_manifest

        tiles_data = {manifest_node: manifest_url}

        result = self.serializer._build_body(tiles_data)

        self.assertEqual(result["type"], "Manifest")
        self.assertEqual(result["id"], manifest_url)
        self.assertEqual(result["format"], "application/ld+json")

    def test_body_with_file_list(self):
        """Body should be Dataset type when file_list node is present."""
        filelist_node = self.serializer.DATATYPE_NODES["file_list"]
        name_node = self.serializer.DATATYPE_NODES["name"]

        tiles_data = {
            filelist_node: [{"url": "/files/data.csv", "name": "data.csv"}],
            name_node: {"en": {"value": "My Dataset"}},
        }

        result = self.serializer._build_body(tiles_data)

        self.assertEqual(result["type"], "Dataset")
        self.assertIn("data.csv", result["id"])

    def test_body_with_multiple_files(self):
        """Body should be a list when multiple files are present."""
        filelist_node = self.serializer.DATATYPE_NODES["file_list"]
        name_node = self.serializer.DATATYPE_NODES["name"]

        tiles_data = {
            filelist_node: [
                {"url": "/files/spectrum1.h5", "name": "spectrum1.h5"},
                {"url": "/files/spectrum2.h5", "name": "spectrum2.h5"},
                {"url": "/files/spectrum3.h5", "name": "spectrum3.h5"},
            ],
            name_node: {"en": {"value": "Multi-file Dataset"}},
        }

        result = self.serializer._build_body(tiles_data)

        # Should return a list of 3 bodies
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)

        # Each body should be a Dataset
        for idx, body in enumerate(result):
            self.assertEqual(body["type"], "Dataset")
            self.assertIn(f"spectrum{idx + 1}.h5", body["id"])
            # Label should include index (1/3, 2/3, 3/3)
            self.assertIn(f"({idx + 1}/3)", body["label"]["en"][0])

    def test_body_fallback_to_textual(self):
        """Body should fallback to TextualBody when no manifest or files."""
        name_node = self.serializer.DATATYPE_NODES["name"]

        tiles_data = {name_node: {"en": {"value": "Simple Analysis"}}}

        result = self.serializer._build_body(tiles_data)

        self.assertEqual(result["type"], "TextualBody")
        self.assertEqual(result["value"], "Simple Analysis")
        self.assertEqual(result["format"], "text/plain")

    def test_body_empty_tiles_fallback(self):
        """Body should have default value when tiles are empty."""
        result = self.serializer._build_body({})

        self.assertEqual(result["type"], "TextualBody")
        self.assertEqual(result["value"], "No data available")


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestBuildMetadata(TestCase):
    """Tests for the _build_metadata method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer
        self.serializer._clear_caches()
        self.serializer._batch_mode = False

    def test_metadata_with_acquisition_date(self):
        """Metadata should include acquisition date when present."""
        date_node = self.serializer.DATATYPE_NODES["acquisition_date"]
        tiles_data = {date_node: "2024-01-15"}

        result = self.serializer._build_metadata(tiles_data)

        date_entry = next((m for m in result if "Acquisition" in str(m["label"])), None)
        self.assertIsNotNone(date_entry)
        self.assertEqual(date_entry["value"]["en"], ["2024-01-15"])

    @patch("manuspectrum.views.serializers.iiif_annotation.Value")
    def test_metadata_with_technique_concepts(self, mock_value):
        """Metadata should resolve technique concepts to labels."""
        technique_node = self.serializer.DATATYPE_NODES["technique"]
        concept_id = str(uuid.uuid4())

        mock_value.objects.filter.return_value.select_related.return_value.values.return_value = [
            {
                "valueid": concept_id,
                "language_id": "en",
                "value": "XRF",
                "concept__conceptid": uuid.uuid4(),
            }
        ]

        tiles_data = {technique_node: [concept_id]}

        result = self.serializer._build_metadata(tiles_data)

        technique_entry = next(
            (m for m in result if "Technique" in str(m["label"])), None
        )
        self.assertIsNotNone(technique_entry)

    def test_metadata_empty_tiles(self):
        """Metadata should be empty list when no relevant tiles."""
        result = self.serializer._build_metadata({})
        self.assertEqual(result, [])

    def test_metadata_with_instrumental_metadata(self):
        """Metadata should include instrumental metadata when present."""
        meta_node = self.serializer.DATATYPE_NODES["metadata_fields"]
        tiles_data = {meta_node: {"en": {"value": "Voltage: 40kV, Current: 30mA"}}}

        result = self.serializer._build_metadata(tiles_data)

        instr_entry = next(
            (m for m in result if "Instrumental" in str(m["label"])), None
        )
        self.assertIsNotNone(instr_entry)


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestBuildSeeAlso(TestCase):
    """Tests for the _build_see_also method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer
        self.serializer._clear_caches()

    def test_see_also_always_includes_report(self):
        """seeAlso should always include link to analysis report."""
        analysis_id = str(uuid.uuid4())

        result = self.serializer._build_see_also({}, analysis_id)

        self.assertEqual(len(result), 1)
        self.assertIn("report", result[0]["id"])
        self.assertEqual(result[0]["type"], "Text")
        self.assertEqual(result[0]["format"], "text/html")

    def test_see_also_with_dataset_uri(self):
        """seeAlso should include dataset URI when present."""
        analysis_id = str(uuid.uuid4())
        doi_node = self.serializer.DATATYPE_NODES["dataset_uri"]
        dataset_uri = "https://doi.org/10.1234/dataset"

        tiles_data = {doi_node: dataset_uri}

        result = self.serializer._build_see_also(tiles_data, analysis_id)

        self.assertEqual(len(result), 2)
        dataset_entry = next((s for s in result if s["type"] == "Dataset"), None)
        self.assertIsNotNone(dataset_entry)
        self.assertEqual(dataset_entry["id"], dataset_uri)


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestBatchProcessing(TestCase):
    """Tests for batch processing methods."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer
        self.serializer._clear_caches()
        self.serializer._batch_mode = False

    @patch("manuspectrum.views.serializers.iiif_annotation.Tile")
    @patch("manuspectrum.views.serializers.iiif_annotation.Value")
    @patch("manuspectrum.views.serializers.iiif_annotation.Resource")
    @patch("manuspectrum.views.serializers.iiif_annotation.IIIFManifest")
    def test_batch_to_representation_processes_multiple(
        self, mock_manifest, mock_resource, mock_value, mock_tile
    ):
        """batch_to_representation should process multiple annotations."""
        mock_tile.objects.filter.return_value.values.return_value = []
        mock_value.objects.filter.return_value.select_related.return_value.values.return_value = (
            []
        )
        mock_resource.objects.filter.return_value = []
        mock_manifest.objects.filter.return_value.values.return_value = []

        annotations_data = [
            {
                "target": "https://example.com/canvas/1#xywh=0,0,100,100",
                "resource_id": str(uuid.uuid4()),
            },
            {
                "target": "https://example.com/canvas/1#xywh=100,100,100,100",
                "resource_id": str(uuid.uuid4()),
            },
            {
                "target": "https://example.com/canvas/2#xywh=0,0,50,50",
                "resource_id": str(uuid.uuid4()),
            },
        ]

        results = self.serializer.batch_to_representation(annotations_data)

        self.assertEqual(len(results), 3)
        for result in results:
            self.assertEqual(result["type"], "Annotation")
            self.assertIn("@context", result)

    def test_batch_mode_clears_after_processing(self):
        """Batch mode should be cleared after processing."""
        with patch("manuspectrum.views.serializers.iiif_annotation.Tile") as mock_tile:
            mock_tile.objects.filter.return_value.values.return_value = []

            self.serializer.batch_to_representation([])

        self.assertFalse(self.serializer._batch_mode)

    @patch("manuspectrum.views.serializers.iiif_annotation.Tile")
    def test_prefetch_all_data_called_in_batch(self, mock_tile):
        """_prefetch_all_data should be called during batch processing."""
        mock_tile.objects.filter.return_value.values.return_value = []

        with patch.object(self.serializer, "_prefetch_all_data") as mock_prefetch:
            self.serializer.batch_to_representation(
                [
                    {
                        "target": "https://example.com/canvas/1",
                        "resource_id": str(uuid.uuid4()),
                    }
                ]
            )

        mock_prefetch.assert_called_once()


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestPrefetchMethods(TestCase):
    """Tests for data prefetching methods."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer
        self.serializer._clear_caches()

    @patch("manuspectrum.views.serializers.iiif_annotation.Tile")
    def test_prefetch_tiles(self, mock_tile):
        """Tiles should be prefetched and cached by resource ID."""
        resource_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        mock_tile.objects.filter.return_value.values.return_value = [
            {"resourceinstance_id": resource_id, "data": {node_id: "test_value"}}
        ]

        self.serializer._prefetch_all_data([resource_id])

        self.assertIn(resource_id, self.serializer._tiles_cache)
        self.assertEqual(
            self.serializer._tiles_cache[resource_id][node_id], "test_value"
        )

    @patch("manuspectrum.views.serializers.iiif_annotation.Value")
    def test_batch_load_concepts(self, mock_value):
        """Concepts should be loaded with multilingual labels."""
        concept_id = str(uuid.uuid4())
        concept_uuid = uuid.uuid4()

        mock_value.objects.filter.return_value.select_related.return_value.values.return_value = [
            {
                "valueid": concept_id,
                "language_id": "en",
                "value": "English Label",
                "concept__conceptid": concept_uuid,
            },
            {
                "valueid": concept_id,
                "language_id": "fr",
                "value": "French Label",
                "concept__conceptid": concept_uuid,
            },
        ]

        self.serializer._batch_load_concepts([concept_id])

        self.assertIn(concept_id, self.serializer._concept_cache)
        self.assertEqual(
            self.serializer._concept_cache[concept_id]["labels"]["en"], "English Label"
        )
        self.assertEqual(
            self.serializer._concept_cache[concept_id]["labels"]["fr"], "French Label"
        )

    @patch("manuspectrum.views.serializers.iiif_annotation.Resource")
    def test_batch_load_resources(self, mock_resource):
        """Resources should be loaded with display names."""
        resource_id = str(uuid.uuid4())

        mock_res = MagicMock()
        mock_res.resourceinstanceid = resource_id
        mock_res.displayname.return_value = "Test Resource"
        mock_resource.objects.filter.return_value = [mock_res]

        self.serializer._batch_load_resources([resource_id])

        self.assertIn(resource_id, self.serializer._resource_cache)
        self.assertEqual(
            self.serializer._resource_cache[resource_id]["labels"]["en"],
            "Test Resource",
        )

    @patch("manuspectrum.views.serializers.iiif_annotation.IIIFManifest")
    def test_batch_load_manifests(self, mock_manifest):
        """Manifests should be loaded by URL."""
        manifest_url = "https://example.com/manifest.json"

        mock_manifest.objects.filter.return_value.values.return_value = [
            {"url": manifest_url, "label": "Test Manifest"}
        ]

        self.serializer._batch_load_manifests([manifest_url])

        self.assertIn(manifest_url, self.serializer._manifest_cache)
        self.assertEqual(
            self.serializer._manifest_cache[manifest_url]["label"], "Test Manifest"
        )


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestCacheManagement(TestCase):
    """Tests for cache management."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer

    def test_clear_caches(self):
        """_clear_caches should empty all cache dictionaries."""
        self.serializer._concept_cache = {"test": "value"}
        self.serializer._resource_cache = {"test": "value"}
        self.serializer._manifest_cache = {"test": "value"}
        self.serializer._tiles_cache = {"test": "value"}

        self.serializer._clear_caches()

        self.assertEqual(len(self.serializer._concept_cache), 0)
        self.assertEqual(len(self.serializer._resource_cache), 0)
        self.assertEqual(len(self.serializer._manifest_cache), 0)
        self.assertEqual(len(self.serializer._tiles_cache), 0)


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestGetLocalizedString(TestCase):
    """Tests for _get_localized_string helper."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer

    def test_localized_string_from_dict(self):
        """Should extract localized strings from language dict."""
        data = {"en": {"value": "English"}, "fr": {"value": "French"}}

        result = self.serializer._get_localized_string(data)

        self.assertEqual(result["en"], ["English"])
        self.assertEqual(result["fr"], ["French"])

    def test_localized_string_skips_empty(self):
        """Should skip empty or whitespace-only values."""
        data = {"en": {"value": "English"}, "fr": {"value": "   "}, "de": {"value": ""}}

        result = self.serializer._get_localized_string(data)

        self.assertIn("en", result)
        self.assertNotIn("fr", result)
        self.assertNotIn("de", result)

    def test_localized_string_fallback(self):
        """Should fallback to string representation for non-dict."""
        result = self.serializer._get_localized_string("simple string")

        self.assertEqual(result["en"], ["simple string"])


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestFormatMetadataValue(TestCase):
    """Tests for _format_metadata_value helper."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer
        self.serializer._clear_caches()
        self.serializer._batch_mode = False

    def test_format_acquisition_date(self):
        """Acquisition date should be formatted as simple string."""
        result = self.serializer._format_metadata_value(
            "2024-01-15", "acquisition_date"
        )

        self.assertEqual(result["en"], ["2024-01-15"])

    @patch("manuspectrum.views.serializers.iiif_annotation.Value")
    def test_format_technique_list(self, mock_value):
        """Technique list should resolve concepts and include URIs."""
        concept_id = str(uuid.uuid4())

        mock_value.objects.filter.return_value.select_related.return_value.values.return_value = [
            {
                "valueid": concept_id,
                "language_id": "en",
                "value": "XRF",
                "concept__conceptid": uuid.uuid4(),
            }
        ]

        result = self.serializer._format_metadata_value([concept_id], "technique")

        self.assertIn("en", result)
        self.assertTrue(any("XRF" in str(v) for v in result["en"]))

    @patch("manuspectrum.views.serializers.iiif_annotation.Resource")
    def test_format_instrument_resource(self, mock_resource):
        """Instrument should resolve resource and include URI."""
        resource_id = str(uuid.uuid4())

        mock_res = MagicMock()
        mock_res.resourceinstanceid = resource_id
        mock_res.displayname.return_value = "XRF Spectrometer"
        mock_resource.objects.get.return_value = mock_res

        result = self.serializer._format_metadata_value(
            {"resourceId": resource_id}, "instrument"
        )

        self.assertIn("en", result)
        self.assertTrue(any("XRF Spectrometer" in str(v) for v in result["en"]))

    def test_format_localized_dict(self):
        """Localized dict should be extracted properly."""
        data = {"en": {"value": "English text"}, "fr": {"value": "French text"}}

        result = self.serializer._format_metadata_value(data, "unknown_field")

        self.assertEqual(result["en"], ["English text"])
        self.assertEqual(result["fr"], ["French text"])


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestExtractResourceId(TestCase):
    """Tests for _extract_resource_id helper."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        self.serializer = IIIFAnnotationSerializer

    def test_extract_from_dict(self):
        """Should extract resourceId from dict."""
        value = {"resourceId": "abc-123"}
        result = self.serializer._extract_resource_id(value)
        self.assertEqual(result, "abc-123")

    def test_extract_from_string(self):
        """Should return string as-is."""
        value = "abc-123"
        result = self.serializer._extract_resource_id(value)
        self.assertEqual(result, "abc-123")

    def test_extract_from_other_returns_empty(self):
        """Should return empty string for other types."""
        result = self.serializer._extract_resource_id(12345)
        self.assertEqual(result, "")

    def test_extract_from_none_returns_empty(self):
        """Should return empty string for None."""
        result = self.serializer._extract_resource_id(None)
        self.assertEqual(result, "")


# ======================================================================================
# Tests for IIIFAnnotationSerializerV2
# ======================================================================================


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestIIIFAnnotationSerializerV2Setup(TestCase):
    """Base class with common setup for v2 serializer tests."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializerV2,
        )

        self.serializer = IIIFAnnotationSerializerV2
        self.serializer._clear_caches()
        self.serializer._batch_mode = False


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestV2ToRepresentation(TestCase):
    """Tests for the v2 to_representation method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializerV2,
        )

        self.serializer = IIIFAnnotationSerializerV2
        self.serializer._clear_caches()
        self.serializer._batch_mode = False

    def test_v2_basic_annotation_structure(self):
        """V2 Annotation should have required IIIF v2 fields."""
        resource_id = str(uuid.uuid4())
        target = "https://example.com/canvas/1#xywh=100,100,200,200"

        with patch.object(self.serializer, "_get_resource_tiles", return_value={}):
            result = self.serializer.to_representation(target, resource_id)

        # V2 uses @context, @id, @type instead of context, id, type
        self.assertEqual(
            result["@context"], "http://iiif.io/api/presentation/2/context.json"
        )
        self.assertEqual(result["@type"], "oa:Annotation")
        self.assertEqual(result["motivation"], "oa:commenting")
        self.assertIn(resource_id, result["@id"])
        self.assertIn("/v2/annotation/", result["@id"])

        # V2 uses 'on' instead of 'target'
        self.assertIn("on", result)
        self.assertNotIn("target", result)

        # V2 uses 'resource' instead of 'body'
        self.assertIn("resource", result)
        self.assertNotIn("body", result)

    def test_v2_annotation_without_resource_id(self):
        """V2 Annotation without resource_id should have fallback resource."""
        target = "https://example.com/canvas/1"

        result = self.serializer.to_representation(target, resource_id="")

        self.assertEqual(result["resource"]["@type"], "cnt:ContentAsText")
        self.assertEqual(result["resource"]["chars"], "No data available")
        self.assertEqual(result["resource"]["format"], "text/plain")

    @patch("manuspectrum.views.serializers.iiif_annotation.Tile")
    def test_v2_annotation_with_name_label(self, mock_tile):
        """V2 Annotation should include label as simple string."""
        resource_id = str(uuid.uuid4())
        name_node = self.serializer.DATATYPE_NODES["name"]

        tiles_data = {
            name_node: {
                "en": {"value": "Analysis Name"},
                "fr": {"value": "Nom de l'analyse"},
            }
        }

        with patch.object(
            self.serializer, "_get_resource_tiles", return_value=tiles_data
        ):
            result = self.serializer.to_representation(
                "https://example.com/canvas/1", resource_id
            )

        # V2 label is a simple string, not a dict
        self.assertIn("label", result)
        self.assertIsInstance(result["label"], str)
        self.assertEqual(result["label"], "Analysis Name")

    def test_v2_annotation_includes_see_also(self):
        """V2 Annotation should include seeAlso with report link."""
        resource_id = str(uuid.uuid4())

        with patch.object(self.serializer, "_get_resource_tiles", return_value={}):
            result = self.serializer.to_representation(
                "https://example.com/canvas/1", resource_id
            )

        self.assertIn("seeAlso", result)
        # V2 seeAlso uses @id and @type
        self.assertTrue(any("@id" in item for item in result["seeAlso"]))
        self.assertTrue(any("@type" in item for item in result["seeAlso"]))


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestV2ConvertLabelToV2(TestCase):
    """Tests for the _convert_label_to_v2 method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializerV2,
        )

        self.serializer = IIIFAnnotationSerializerV2

    def test_convert_v3_label_dict_to_string(self):
        """Should convert v3 label dict to simple string."""
        label_v3 = {"en": ["English Label"], "fr": ["French Label"]}
        result = self.serializer._convert_label_to_v2(label_v3)
        self.assertEqual(result, "English Label")

    def test_convert_v3_label_prefers_english(self):
        """Should prefer English label when available."""
        label_v3 = {"fr": ["French"], "en": ["English"], "de": ["German"]}
        result = self.serializer._convert_label_to_v2(label_v3)
        self.assertEqual(result, "English")

    def test_convert_v3_label_fallback_to_french(self):
        """Should fallback to French if English not available."""
        label_v3 = {"fr": ["French"], "de": ["German"]}
        result = self.serializer._convert_label_to_v2(label_v3)
        self.assertEqual(result, "French")

    def test_convert_string_returns_same(self):
        """Should return string as-is."""
        result = self.serializer._convert_label_to_v2("Simple Label")
        self.assertEqual(result, "Simple Label")

    def test_convert_none_returns_none(self):
        """Should return None for None input."""
        result = self.serializer._convert_label_to_v2(None)
        self.assertIsNone(result)

    def test_convert_empty_dict_returns_string(self):
        """Should handle empty dict gracefully."""
        result = self.serializer._convert_label_to_v2({})
        self.assertEqual(result, "{}")


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestV2BuildBodyV2(TestCase):
    """Tests for the _build_body_v2 method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializerV2,
        )

        self.serializer = IIIFAnnotationSerializerV2
        self.serializer._clear_caches()
        self.serializer._batch_mode = False

    @patch("manuspectrum.views.serializers.iiif_annotation.IIIFManifest")
    def test_v2_body_with_manifest(self, mock_manifest_model):
        """V2 resource should be sc:Manifest type when manifest node is present."""
        manifest_node = self.serializer.DATATYPE_NODES["manifest"]
        manifest_url = "https://example.com/manifest.json"

        mock_manifest = MagicMock()
        mock_manifest.label = "Test Manifest"
        mock_manifest_model.objects.get.return_value = mock_manifest

        tiles_data = {manifest_node: manifest_url}

        result = self.serializer._build_body_v2(tiles_data)

        self.assertEqual(result["@type"], "sc:Manifest")
        self.assertEqual(result["@id"], manifest_url)
        self.assertEqual(result["format"], "application/ld+json")

    def test_v2_body_with_file_list(self):
        """V2 resource should be dctypes:Dataset type when file_list node is present."""
        filelist_node = self.serializer.DATATYPE_NODES["file_list"]
        name_node = self.serializer.DATATYPE_NODES["name"]

        tiles_data = {
            filelist_node: [{"url": "/files/data.csv", "name": "data.csv"}],
            name_node: {"en": {"value": "My Dataset"}},
        }

        result = self.serializer._build_body_v2(tiles_data)

        self.assertEqual(result["@type"], "dctypes:Dataset")
        self.assertIn("data.csv", result["@id"])

    def test_v2_body_fallback_to_textual(self):
        """V2 resource should fallback to cnt:ContentAsText when no manifest or files."""
        name_node = self.serializer.DATATYPE_NODES["name"]

        tiles_data = {name_node: {"en": {"value": "Simple Analysis"}}}

        result = self.serializer._build_body_v2(tiles_data)

        self.assertEqual(result["@type"], "cnt:ContentAsText")
        self.assertEqual(result["chars"], "Simple Analysis")
        self.assertEqual(result["format"], "text/plain")


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestV2BuildTargetV2(TestCase):
    """Tests for the _build_target_v2 method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializerV2,
        )

        self.serializer = IIIFAnnotationSerializerV2

    def test_v2_target_with_fragment_returns_string(self):
        """V2 'on' should be simple URI string with fragment."""
        target = "https://example.com/canvas/1#xywh=100,100,200,200"
        result = self.serializer._build_target_v2(target)
        self.assertEqual(result, target)
        self.assertIsInstance(result, str)

    def test_v2_target_without_fragment_returns_canvas_uri(self):
        """V2 'on' should return canvas_uri when no fragment."""
        target = "https://example.com/canvas/1"
        canvas_uri = "https://example.com/canvas/1"
        result = self.serializer._build_target_v2(target, canvas_uri)
        self.assertEqual(result, canvas_uri)

    def test_v2_target_empty_returns_canvas_uri(self):
        """V2 'on' should return canvas_uri when target is empty."""
        canvas_uri = "https://example.com/canvas/1"
        result = self.serializer._build_target_v2("", canvas_uri)
        self.assertEqual(result, canvas_uri)


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestV2ConvertMetadataToV2(TestCase):
    """Tests for the _convert_metadata_to_v2 method."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializerV2,
        )

        self.serializer = IIIFAnnotationSerializerV2

    def test_convert_metadata_to_v2_format(self):
        """Should convert v3 metadata format to v2 simple format."""
        metadata_v3 = [
            {"label": {"en": ["Technique"]}, "value": {"en": ["XRF Spectroscopy"]}},
            {"label": {"en": ["Date"]}, "value": {"en": ["2024-01-15"]}},
        ]

        result = self.serializer._convert_metadata_to_v2(metadata_v3)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["label"], "Technique")
        self.assertEqual(result[0]["value"], "XRF Spectroscopy")
        self.assertEqual(result[1]["label"], "Date")
        self.assertEqual(result[1]["value"], "2024-01-15")

    def test_convert_metadata_empty_list(self):
        """Should return empty list for empty input."""
        result = self.serializer._convert_metadata_to_v2([])
        self.assertEqual(result, [])


@override_settings(PUBLIC_SERVER_ADDRESS="https://test.example.com/")
class TestV2BatchProcessing(TestCase):
    """Tests for v2 batch processing methods."""

    def setUp(self):
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializerV2,
        )

        self.serializer = IIIFAnnotationSerializerV2
        self.serializer._clear_caches()
        self.serializer._batch_mode = False

    @patch("manuspectrum.views.serializers.iiif_annotation.Tile")
    @patch("manuspectrum.views.serializers.iiif_annotation.Value")
    @patch("manuspectrum.views.serializers.iiif_annotation.Resource")
    @patch("manuspectrum.views.serializers.iiif_annotation.IIIFManifest")
    def test_v2_batch_to_representation_processes_multiple(
        self, mock_manifest, mock_resource, mock_value, mock_tile
    ):
        """V2 batch_to_representation should process multiple annotations."""
        mock_tile.objects.filter.return_value.values.return_value = []
        mock_value.objects.filter.return_value.select_related.return_value.values.return_value = (
            []
        )
        mock_resource.objects.filter.return_value = []
        mock_manifest.objects.filter.return_value.values.return_value = []

        annotations_data = [
            {
                "target": "https://example.com/canvas/1#xywh=0,0,100,100",
                "resource_id": str(uuid.uuid4()),
            },
            {
                "target": "https://example.com/canvas/1#xywh=100,100,100,100",
                "resource_id": str(uuid.uuid4()),
            },
        ]

        results = self.serializer.batch_to_representation(annotations_data)

        self.assertEqual(len(results), 2)
        for result in results:
            # V2 format checks
            self.assertEqual(result["@type"], "oa:Annotation")
            self.assertIn("@context", result)
            self.assertEqual(
                result["@context"], "http://iiif.io/api/presentation/2/context.json"
            )
