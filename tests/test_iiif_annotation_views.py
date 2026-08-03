"""
Unit tests for IIIF Annotation Views and Cache utilities.

Tests cache management, HTTP responses, and view logic.

Usage:
    python manage.py test tests.test_iiif_annotation_views
"""

import json
import uuid
import zlib
from unittest.mock import MagicMock, patch, PropertyMock

from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase, RequestFactory, override_settings

# =============================================================================
# CACHE UTILITIES TESTS
# =============================================================================


class TestCacheEtagKey(TestCase):
    """Tests for _cache_etag_key function."""

    def test_generates_etag_suffix(self):
        """Should append __etag to cache key."""
        from manuspectrum.views.iiif_annotation import _cache_etag_key

        result = _cache_etag_key("my_cache_key")
        self.assertEqual(result, "my_cache_key__etag")

    def test_handles_empty_key(self):
        """Should work with empty string."""
        from manuspectrum.views.iiif_annotation import _cache_etag_key

        result = _cache_etag_key("")
        self.assertEqual(result, "__etag")


class TestCachedJsonResponse(TestCase):
    """Tests for cached_json_response function."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_returns_http_response(self):
        """Should return an HttpResponse."""
        from manuspectrum.views.iiif_annotation import cached_json_response

        data = {"test": "data"}
        response = cached_json_response("test_key", data)

        self.assertIsInstance(response, HttpResponse)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_response_contains_json_data(self):
        """Response body should contain JSON data."""
        from manuspectrum.views.iiif_annotation import cached_json_response

        data = {"key": "value", "number": 42}
        response = cached_json_response("test_key", data)

        response_data = json.loads(response.content)
        self.assertEqual(response_data["key"], "value")
        self.assertEqual(response_data["number"], 42)

    def test_sets_etag_header(self):
        """Response should have ETag header."""
        from manuspectrum.views.iiif_annotation import cached_json_response

        data = {"test": "data"}
        response = cached_json_response("test_key", data)

        self.assertIn("ETag", response)
        self.assertTrue(len(response["ETag"]) > 0)

    def test_sets_cache_control_header(self):
        """Response should have Cache-Control header."""
        from manuspectrum.views.iiif_annotation import cached_json_response

        data = {"test": "data"}
        response = cached_json_response("test_key", data)

        self.assertIn("Cache-Control", response)
        self.assertIn("public", response["Cache-Control"])
        self.assertIn("max-age=3600", response["Cache-Control"])

    def test_stores_compressed_data_in_cache(self):
        """Should store compressed data in cache."""
        from manuspectrum.views.iiif_annotation import cached_json_response

        data = {"test": "data"}
        cached_json_response("test_key", data)

        cached_data = cache.get("test_key")
        self.assertIsNotNone(cached_data)

        # Should be compressed
        decompressed = zlib.decompress(cached_data)
        self.assertEqual(json.loads(decompressed), data)

    def test_stores_etag_in_cache(self):
        """Should store ETag in separate cache key."""
        from manuspectrum.views.iiif_annotation import cached_json_response

        data = {"test": "data"}
        cached_json_response("test_key", data)

        etag = cache.get("test_key__etag")
        self.assertIsNotNone(etag)
        self.assertTrue(len(etag) > 0)

    def test_custom_timeout(self):
        """Should respect custom timeout."""
        from manuspectrum.views.iiif_annotation import cached_json_response

        data = {"test": "data"}
        cached_json_response("test_key", data, timeout=60)

        # Data should still be cached
        self.assertIsNotNone(cache.get("test_key"))


class TestGetCachedResponse(TestCase):
    """Tests for get_cached_response function."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_returns_none_when_not_cached(self):
        """Should return None when cache key doesn't exist."""
        from manuspectrum.views.iiif_annotation import get_cached_response

        result = get_cached_response("nonexistent_key")
        self.assertIsNone(result)

    def test_returns_response_when_cached(self):
        """Should return HttpResponse when data is cached."""
        from manuspectrum.views.iiif_annotation import (
            cached_json_response,
            get_cached_response,
        )

        data = {"test": "data"}
        cached_json_response("test_key", data)

        result = get_cached_response("test_key")

        self.assertIsInstance(result, HttpResponse)
        self.assertEqual(json.loads(result.content), data)

    def test_includes_etag_when_available(self):
        """Should include ETag header when available in cache."""
        from manuspectrum.views.iiif_annotation import (
            cached_json_response,
            get_cached_response,
        )

        data = {"test": "data"}
        cached_json_response("test_key", data)

        result = get_cached_response("test_key")

        self.assertIn("ETag", result)

    def test_handles_corrupted_cache(self):
        """Should handle corrupted cache data gracefully."""
        from manuspectrum.views.iiif_annotation import get_cached_response

        # Store non-compressed data directly
        cache.set("corrupt_key", b"not compressed data")

        result = get_cached_response("corrupt_key")

        self.assertIsNone(result)
        # Should have deleted corrupted entry
        self.assertIsNone(cache.get("corrupt_key"))


# =============================================================================
# IIIF ANNOTATION MIXIN TESTS
# =============================================================================


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestIIIFAnnotationMixin(TestCase):
    """Tests for IIIFAnnotationMixin shared helpers."""

    def setUp(self):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationMixin

        self.mixin = IIIFAnnotationMixin()

    def test_get_display_name_from_displayname_method(self):
        """Should call displayname() if it's callable."""
        resource = MagicMock()
        resource.displayname.return_value = "Test Resource"

        result = self.mixin._get_display_name(resource)

        self.assertEqual(result, "Test Resource")

    def test_get_display_name_from_displayname_property(self):
        """Should use displayname property if not callable."""
        resource = MagicMock(spec=["displayname", "resourceinstanceid"])
        resource.displayname = "Test Resource"

        result = self.mixin._get_display_name(resource)

        self.assertEqual(result, "Test Resource")

    def test_get_display_name_fallback_to_uuid(self):
        """Should fallback to resourceinstanceid if no displayname."""
        resource = MagicMock(spec=["resourceinstanceid"])
        resource.resourceinstanceid = uuid.uuid4()

        result = self.mixin._get_display_name(resource)

        self.assertEqual(result, str(resource.resourceinstanceid))

    @patch("manuspectrum.views.iiif_annotation.cache")
    def test_get_canvas_dimensions_uses_cache(self, mock_cache):
        """Should check cache before calling CanvasIIIF."""
        mock_cache.get.return_value = (1000, 1500)

        result = self.mixin._get_canvas_dimensions("https://example.com/canvas/1")

        self.assertEqual(result, (1000, 1500))

    def test_convert_geojson_to_iiif_target_with_geometry(self):
        """Should convert geometry to xywh fragment."""
        annotation = {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
            },
            "canvas": "https://example.com/canvas/1",
            "manifest": "https://example.com/manifest",
        }

        with patch.multiple(
            self.mixin,
            _get_canvas_dimensions=MagicMock(return_value=(2000, 3000)),
            _get_manifest_data=MagicMock(return_value=None),
        ):
            with patch("manuspectrum.utils.iiif_tools.BBoxCalculator") as mock_calc:
                mock_calc.geometry_to_xywh.return_value = "xywh=100,200,300,400"

                result = self.mixin._convert_geojson_to_iiif_target(annotation)

        self.assertIn("xywh=", result)
        self.assertIn("https://example.com/canvas/1", result)

    def test_convert_geojson_to_iiif_target_without_geometry(self):
        """Should return canvas URI without fragment when no geometry."""
        annotation = {"geometry": None, "canvas": "https://example.com/canvas/1"}

        result = self.mixin._convert_geojson_to_iiif_target(annotation)

        self.assertEqual(result, "https://example.com/canvas/1")

    def test_convert_geojson_to_iiif_target_without_canvas(self):
        """Should return empty string when no canvas."""
        annotation = {"geometry": {"type": "Point"}, "canvas": None}

        result = self.mixin._convert_geojson_to_iiif_target(annotation)

        self.assertEqual(result, "")


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestGetAnnotationsFromAnalyses(TestCase):
    """Tests for _get_annotations_from_analyses method."""

    def setUp(self):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationMixin

        self.mixin = IIIFAnnotationMixin()

    @patch("manuspectrum.views.iiif_annotation.VwAnnotation")
    def test_returns_empty_for_empty_analyses(self, mock_vw):
        """Should return empty list for empty analyses."""
        result = self.mixin._get_annotations_from_analyses([])

        self.assertEqual(result, [])
        mock_vw.objects.filter.assert_not_called()

    @patch("manuspectrum.views.iiif_annotation.VwAnnotation")
    def test_extracts_annotation_data(self, mock_vw):
        """Should extract annotation data from VwAnnotation objects."""
        analysis_id = uuid.uuid4()
        analysis = MagicMock()
        analysis.resourceinstanceid = analysis_id

        mock_annotation = MagicMock()
        mock_annotation.resourceinstance_id = analysis_id
        mock_annotation.canvas = (
            "https://example.com/canvas/1"  # Direct attribute from VwAnnotation
        )
        mock_annotation.feature = {
            "properties": {
                "canvas": "https://example.com/canvas/1",
                "manifest": "https://example.com/manifest",
                "label": "Test Analysis",
            },
            "geometry": {"type": "Point", "coordinates": [100, 200]},
        }

        mock_vw.objects.filter.return_value = [mock_annotation]

        result = self.mixin._get_annotations_from_analyses([analysis])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["canvas"], "https://example.com/canvas/1")
        self.assertEqual(result[0]["analysis_label"], "Test Analysis")

    @patch("manuspectrum.views.iiif_annotation.VwAnnotation")
    def test_skips_empty_features(self, mock_vw):
        """Should skip annotations with empty features."""
        analysis = MagicMock()
        analysis.resourceinstanceid = uuid.uuid4()

        mock_annotation = MagicMock()
        mock_annotation.resourceinstance_id = analysis.resourceinstanceid
        mock_annotation.feature = {}

        mock_vw.objects.filter.return_value = [mock_annotation]

        result = self.mixin._get_annotations_from_analyses([analysis])

        self.assertEqual(len(result), 0)

    @patch("manuspectrum.views.iiif_annotation.VwAnnotation")
    def test_skips_none_features(self, mock_vw):
        """Should skip annotations with None features."""
        analysis = MagicMock()
        analysis.resourceinstanceid = uuid.uuid4()

        mock_annotation = MagicMock()
        mock_annotation.resourceinstance_id = analysis.resourceinstanceid
        mock_annotation.feature = None

        mock_vw.objects.filter.return_value = [mock_annotation]

        result = self.mixin._get_annotations_from_analyses([analysis])

        self.assertEqual(len(result), 0)


# =============================================================================
# ANNOTATION COLLECTION VIEW TESTS
# =============================================================================


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestIIIFAnnotationCollectionView(TestCase):
    """Tests for IIIFAnnotationCollectionView."""

    def setUp(self):
        self.factory = RequestFactory()
        from manuspectrum.views.iiif_annotation import IIIFAnnotationCollectionView

        self.view = IIIFAnnotationCollectionView()
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("manuspectrum.views.iiif_annotation.ResourceInstance")
    def test_returns_404_for_nonexistent_resource(self, mock_ri):
        """Should return 404 when resource doesn't exist."""
        mock_ri.DoesNotExist = Exception
        mock_ri.objects.select_related.return_value.get.side_effect = (
            mock_ri.DoesNotExist
        )

        request = self.factory.get("/iiif/annotation-collection/123/")
        response = self.view.get(request, uuid.uuid4())

        self.assertEqual(response.status_code, 404)

    @patch("manuspectrum.views.iiif_annotation.ResourceInstance")
    def test_returns_404_when_no_analyses(self, mock_ri):
        """Should return 404 when no related analyses found."""
        mock_resource = MagicMock()
        mock_ri.objects.select_related.return_value.get.return_value = mock_resource

        with patch.object(self.view, "_get_related_analyses", return_value=[]):
            request = self.factory.get("/iiif/annotation-collection/123/")
            response = self.view.get(request, uuid.uuid4())

        self.assertEqual(response.status_code, 404)

    def test_group_by_canvas(self):
        """Should group annotations by canvas URI."""
        annotations = [
            {"canvas": "https://example.com/canvas/1", "id": "a1"},
            {"canvas": "https://example.com/canvas/1", "id": "a2"},
            {"canvas": "https://example.com/canvas/2", "id": "a3"},
        ]

        result = self.view._group_by_canvas(annotations)

        self.assertEqual(len(result["https://example.com/canvas/1"]), 2)
        self.assertEqual(len(result["https://example.com/canvas/2"]), 1)

    def test_group_by_canvas_skips_none(self):
        """Should skip annotations without canvas."""
        annotations = [
            {"canvas": "https://example.com/canvas/1", "id": "a1"},
            {"canvas": None, "id": "a2"},
        ]

        result = self.view._group_by_canvas(annotations)

        self.assertEqual(len(result), 1)

    def test_build_annotation_collection_structure(self):
        """Should build valid IIIF AnnotationCollection structure."""
        resource = MagicMock()
        resource.resourceinstanceid = uuid.uuid4()

        grouped_annos = {
            "https://example.com/canvas/1": [{"id": "anno1"}, {"id": "anno2"}],
            "https://example.com/canvas/2": [{"id": "anno3"}],
        }

        result = self.view._build_annotation_collection(resource, grouped_annos)

        self.assertEqual(
            result["@context"], "http://iiif.io/api/presentation/3/context.json"
        )
        self.assertEqual(result["type"], "AnnotationCollection")
        self.assertEqual(result["total"], 3)
        self.assertIn("first", result)
        self.assertIn("last", result)
        self.assertEqual(len(result["items"]), 2)  # 2 pages

    def test_build_annotation_collection_pagination(self):
        """Pages should have next/prev links."""
        resource = MagicMock()
        resource.resourceinstanceid = uuid.uuid4()

        grouped_annos = {
            "canvas1": [{"id": "a1"}],
            "canvas2": [{"id": "a2"}],
            "canvas3": [{"id": "a3"}],
        }

        result = self.view._build_annotation_collection(resource, grouped_annos)

        pages = result["items"]

        # First page should have next but no prev
        self.assertIn("next", pages[0])
        self.assertNotIn("prev", pages[0])

        # Middle page should have both
        self.assertIn("next", pages[1])
        self.assertIn("prev", pages[1])

        # Last page should have prev but no next
        self.assertNotIn("next", pages[2])
        self.assertIn("prev", pages[2])

    def test_build_annotation_collection_empty(self):
        """Should handle empty grouped annotations."""
        resource = MagicMock()
        resource.resourceinstanceid = uuid.uuid4()

        result = self.view._build_annotation_collection(resource, {})

        self.assertEqual(result["type"], "AnnotationCollection")
        self.assertEqual(result["total"], 0)
        self.assertNotIn("first", result)
        self.assertNotIn("items", result)


# =============================================================================
# SINGLE ANNOTATION VIEW TESTS
# =============================================================================


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestIIIFAnnotationView(TestCase):
    """Tests for IIIFAnnotationView."""

    def setUp(self):
        self.factory = RequestFactory()
        from manuspectrum.views.iiif_annotation import IIIFAnnotationView

        self.view = IIIFAnnotationView()
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("manuspectrum.views.iiif_annotation.Resource")
    def test_returns_404_for_nonexistent_resource(self, mock_resource):
        """Should return 404 when resource doesn't exist."""
        mock_resource.DoesNotExist = Exception
        mock_resource.objects.get.side_effect = mock_resource.DoesNotExist

        request = self.factory.get("/iiif/annotation/123/")
        response = self.view.get(request, uuid.uuid4())

        self.assertEqual(response.status_code, 404)

    @patch("manuspectrum.views.iiif_annotation.Resource")
    def test_returns_400_for_non_analysis_resource(self, mock_resource):
        """Should return 400 when resource is not an Analysis."""
        mock_res = MagicMock()
        mock_res.graph_id = uuid.uuid4()  # Different from ANALYSIS_GRAPH_ID
        mock_resource.objects.get.return_value = mock_res

        request = self.factory.get("/iiif/annotation/123/")
        response = self.view.get(request, uuid.uuid4())

        self.assertEqual(response.status_code, 400)

    @patch("manuspectrum.views.iiif_annotation.IIIFAnnotationSerializer")
    @patch("manuspectrum.views.iiif_annotation.Resource")
    def test_returns_annotation_for_valid_analysis(
        self, mock_resource, mock_serializer
    ):
        """Should return IIIF annotation for valid Analysis resource."""
        resource_id = uuid.uuid4()

        mock_res = MagicMock()
        mock_res.graph_id = self.view.ANALYSIS_GRAPH_ID
        mock_res.resourceinstanceid = resource_id
        mock_resource.objects.get.return_value = mock_res

        mock_serializer.to_representation.return_value = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "type": "Annotation",
        }

        with patch.object(
            self.view, "_get_annotations_from_analyses"
        ) as mock_get_annos:
            mock_get_annos.return_value = [{"canvas": "https://example.com/canvas"}]

            with patch.object(
                self.view, "_convert_geojson_to_iiif_target"
            ) as mock_convert:
                mock_convert.return_value = (
                    "https://example.com/canvas#xywh=0,0,100,100"
                )

                request = self.factory.get("/iiif/annotation/123/")
                response = self.view.get(request, resource_id)

        self.assertEqual(response.status_code, 200)

    @patch("manuspectrum.views.iiif_annotation.Resource")
    def test_returns_404_when_no_annotation_data(self, mock_resource):
        """Should return 404 when analysis has no annotation data."""
        resource_id = uuid.uuid4()

        mock_res = MagicMock()
        mock_res.graph_id = self.view.ANALYSIS_GRAPH_ID
        mock_res.resourceinstanceid = resource_id
        mock_resource.objects.get.return_value = mock_res

        with patch.object(self.view, "_get_annotations_from_analyses", return_value=[]):
            request = self.factory.get("/iiif/annotation/123/")
            response = self.view.get(request, resource_id)

        self.assertEqual(response.status_code, 404)


# =============================================================================
# CACHE INVALIDATION TESTS
# =============================================================================


class TestCacheInvalidation(TestCase):
    """Tests for cache invalidation functions."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_delete_cache_keys(self):
        """Should delete both cache key and etag key."""
        from manuspectrum.views.iiif_annotation import _delete_cache_keys

        cache.set("test_key", "value")
        cache.set("test_key__etag", "etag_value")

        _delete_cache_keys(["test_key"])

        self.assertIsNone(cache.get("test_key"))
        self.assertIsNone(cache.get("test_key__etag"))

    def test_delete_cache_keys_handles_missing(self):
        """Should not raise error for missing keys."""
        from manuspectrum.views.iiif_annotation import _delete_cache_keys

        # Should not raise
        _delete_cache_keys(["nonexistent_key"])

    def test_delete_page_patterns(self):
        """Should delete all cached pages for a resource (v3 by default)."""
        from manuspectrum.views.iiif_annotation import _delete_page_patterns

        resource_id = str(uuid.uuid4())

        # Setup cached pages with version prefix
        cache.set(f"iiif_v3_page_list_{resource_id}", [0, 1, 2])
        cache.set(f"iiif_v3_page_{resource_id}_0", "page0")
        cache.set(f"iiif_v3_page_{resource_id}_1", "page1")
        cache.set(f"iiif_v3_page_{resource_id}_2", "page2")

        _delete_page_patterns(resource_id, "v3")

        self.assertIsNone(cache.get(f"iiif_v3_page_list_{resource_id}"))
        self.assertIsNone(cache.get(f"iiif_v3_page_{resource_id}_0"))
        self.assertIsNone(cache.get(f"iiif_v3_page_{resource_id}_1"))
        self.assertIsNone(cache.get(f"iiif_v3_page_{resource_id}_2"))

    def test_delete_page_patterns_no_list(self):
        """Should handle case when page list doesn't exist."""
        from manuspectrum.views.iiif_annotation import _delete_page_patterns

        # Should not raise
        _delete_page_patterns(str(uuid.uuid4()))


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestCacheInvalidationSignals(TestCase):
    """Tests for cache invalidation signal handlers."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("manuspectrum.views.iiif_annotation.ResourceXResource")
    @patch("manuspectrum.views.iiif_annotation._delete_cache_keys")
    def test_invalidate_for_analysis_id(self, mock_delete, mock_rxr):
        """Should invalidate annotation cache and related collections (v2 and v3)."""
        from manuspectrum.views.iiif_annotation import _invalidate_for_analysis_id

        analysis_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        # Mock relation to a Document
        mock_rel = MagicMock()
        mock_rel.to_resource_id = doc_id
        mock_rel.to_resource_graph_id = (
            "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"  # DOCUMENT_GRAPH
        )

        mock_rxr.objects.filter.return_value = [mock_rel]

        _invalidate_for_analysis_id(analysis_id)

        # Should delete annotation cache for both v2 and v3
        mock_delete.assert_any_call(
            [
                f"iiif_v3_annotation_{analysis_id}",
                f"iiif_v2_annotation_{analysis_id}",
            ]
        )

    @patch("manuspectrum.views.iiif_annotation._invalidate_for_analysis_id")
    def test_signal_handler_vwannotation(self, mock_invalidate):
        """Signal handler should call _invalidate_for_analysis_id."""
        from manuspectrum.views.iiif_annotation import invalidate_on_vwannotation_change

        analysis_id = uuid.uuid4()
        instance = MagicMock()
        instance.resourceinstance_id = analysis_id

        invalidate_on_vwannotation_change(sender=None, instance=instance)

        mock_invalidate.assert_called_once_with(analysis_id)


# =============================================================================
# ANNOTATION PAGE VIEW TESTS
# =============================================================================


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestIIIFAnnotationPageView(TestCase):
    """Tests for IIIFAnnotationPageView."""

    def setUp(self):
        self.factory = RequestFactory()
        from manuspectrum.views.iiif_annotation import IIIFAnnotationPageView

        self.view = IIIFAnnotationPageView()
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("manuspectrum.views.iiif_annotation.ResourceInstance")
    def test_returns_404_for_nonexistent_resource(self, mock_ri):
        """Should return 404 when resource doesn't exist."""
        mock_ri.DoesNotExist = Exception
        mock_ri.objects.select_related.return_value.get.side_effect = (
            mock_ri.DoesNotExist
        )

        request = self.factory.get("/iiif/annotation-collection/123/page-0")
        response = self.view.get(request, uuid.uuid4(), 0)

        self.assertEqual(response.status_code, 404)

    @patch("manuspectrum.views.iiif_annotation.ResourceInstance")
    @patch("manuspectrum.views.iiif_annotation.IIIFAnnotationCollectionView")
    def test_returns_404_for_invalid_page_number(self, mock_collection, mock_ri):
        """Should return 404 when page number is out of range."""
        mock_resource = MagicMock()
        mock_ri.objects.select_related.return_value.get.return_value = mock_resource

        mock_collection_instance = MagicMock()
        mock_collection_instance._get_related_analyses.return_value = [MagicMock()]
        mock_collection.return_value = mock_collection_instance

        with patch.object(
            self.view,
            "_get_annotations_from_analyses",
            return_value=[{"canvas": "https://example.com/canvas/1"}],
        ):
            with patch.object(
                mock_collection_instance,
                "_group_by_canvas",
                return_value={"canvas1": [{"id": "a1"}]},
            ):
                request = self.factory.get("/iiif/annotation-collection/123/page-99")
                response = self.view.get(request, uuid.uuid4(), 99)

        self.assertEqual(response.status_code, 404)


# =============================================================================
# GET RELATED ANALYSES TESTS
# =============================================================================


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestGetRelatedAnalyses(TestCase):
    """Tests for _get_related_analyses method."""

    def setUp(self):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationCollectionView

        self.view = IIIFAnnotationCollectionView()

    @patch("manuspectrum.views.iiif_annotation.Resource")
    @patch("manuspectrum.views.iiif_annotation.ResourceXResource")
    def test_gets_analyses_for_component(self, mock_rxr, mock_resource):
        """Should get analyses directly linked to a Component."""
        resource = MagicMock()
        resource.resourceinstanceid = uuid.uuid4()
        resource.graph_id = self.view.COMPONENT_GRAPH_ID

        analysis_id = uuid.uuid4()
        mock_rxr.objects.filter.return_value.values_list.return_value = [analysis_id]

        mock_analysis = MagicMock()
        mock_resource.objects.filter.return_value.only.return_value = [mock_analysis]

        result = self.view._get_related_analyses(resource)

        self.assertEqual(len(result), 1)
        mock_rxr.objects.filter.assert_called()

    @patch("manuspectrum.views.iiif_annotation.Resource")
    @patch("manuspectrum.views.iiif_annotation.ResourceXResource")
    def test_gets_analyses_for_document(self, mock_rxr, mock_resource):
        """Should get analyses directly and via Components for Document."""
        resource = MagicMock()
        resource.resourceinstanceid = uuid.uuid4()
        resource.graph_id = self.view.DOCUMENT_GRAPH_ID

        analysis_id = uuid.uuid4()
        # Mock the filter().values_list() chain for Document
        mock_rxr.objects.filter.return_value.values_list.return_value = [
            (analysis_id, self.view.ANALYSIS_GRAPH_ID)
        ]

        mock_analysis = MagicMock()
        mock_resource.objects.filter.return_value.only.return_value = [mock_analysis]

        result = self.view._get_related_analyses(resource)

        mock_rxr.objects.filter.assert_called()

    def test_returns_empty_for_unknown_graph(self):
        """Should return empty list for unknown graph type."""
        resource = MagicMock()
        resource.resourceinstanceid = uuid.uuid4()
        resource.graph_id = str(uuid.uuid4())  # Unknown graph

        result = self.view._get_related_analyses(resource)

        self.assertEqual(result, [])

    @patch("manuspectrum.views.iiif_annotation.Resource")
    @patch("manuspectrum.views.iiif_annotation.ResourceXResource")
    def test_returns_empty_when_no_relations(self, mock_rxr, mock_resource):
        """Should return empty list when no relations found."""
        resource = MagicMock()
        resource.resourceinstanceid = uuid.uuid4()
        resource.graph_id = self.view.COMPONENT_GRAPH_ID

        mock_rxr.objects.filter.return_value.values_list.return_value = []

        result = self.view._get_related_analyses(resource)

        self.assertEqual(result, [])


# =============================================================================
# CANVAS INDEX TESTS (iiif_tools.py)
# =============================================================================


class TestGetCanvasIndex(TestCase):
    """Tests for CanvasIIIF.get_canvas_index function."""

    def test_finds_canvas_in_v3_manifest(self):
        """Should find canvas position in IIIF v3 manifest."""
        from manuspectrum.utils.iiif_tools import CanvasIIIF

        manifest_v3 = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": "https://example.com/manifest",
            "type": "Manifest",
            "items": [
                {"id": "https://example.com/canvas/1", "type": "Canvas"},
                {"id": "https://example.com/canvas/2", "type": "Canvas"},
                {"id": "https://example.com/canvas/3", "type": "Canvas"},
            ],
        }

        # First canvas = position 1
        self.assertEqual(
            CanvasIIIF.get_canvas_index(manifest_v3, "https://example.com/canvas/1"), 1
        )
        # Second canvas = position 2
        self.assertEqual(
            CanvasIIIF.get_canvas_index(manifest_v3, "https://example.com/canvas/2"), 2
        )
        # Third canvas = position 3
        self.assertEqual(
            CanvasIIIF.get_canvas_index(manifest_v3, "https://example.com/canvas/3"), 3
        )

    def test_finds_canvas_in_v2_manifest(self):
        """Should find canvas position in IIIF v2 manifest."""
        from manuspectrum.utils.iiif_tools import CanvasIIIF

        manifest_v2 = {
            "@context": "http://iiif.io/api/presentation/2/context.json",
            "@id": "https://example.com/manifest",
            "@type": "sc:Manifest",
            "sequences": [
                {
                    "@id": "https://example.com/sequence/1",
                    "canvases": [
                        {"@id": "https://example.com/canvas/1", "@type": "sc:Canvas"},
                        {"@id": "https://example.com/canvas/2", "@type": "sc:Canvas"},
                        {"@id": "https://example.com/canvas/3", "@type": "sc:Canvas"},
                    ],
                }
            ],
        }

        # First canvas = position 1
        self.assertEqual(
            CanvasIIIF.get_canvas_index(manifest_v2, "https://example.com/canvas/1"), 1
        )
        # Second canvas = position 2
        self.assertEqual(
            CanvasIIIF.get_canvas_index(manifest_v2, "https://example.com/canvas/2"), 2
        )
        # Third canvas = position 3
        self.assertEqual(
            CanvasIIIF.get_canvas_index(manifest_v2, "https://example.com/canvas/3"), 3
        )

    def test_returns_none_for_unknown_canvas(self):
        """Should return None when canvas is not found."""
        from manuspectrum.utils.iiif_tools import CanvasIIIF

        manifest_v3 = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "items": [
                {"id": "https://example.com/canvas/1", "type": "Canvas"},
            ],
        }

        result = CanvasIIIF.get_canvas_index(
            manifest_v3, "https://example.com/canvas/unknown"
        )
        self.assertIsNone(result)

    def test_handles_normalized_uri_http_https(self):
        """Should match canvas URIs with different http/https schemes."""
        from manuspectrum.utils.iiif_tools import CanvasIIIF

        manifest_v3 = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "items": [
                {"id": "https://example.com/canvas/1", "type": "Canvas"},
            ],
        }

        # Search with http:// but manifest has https://
        result = CanvasIIIF.get_canvas_index(manifest_v3, "http://example.com/canvas/1")
        self.assertEqual(result, 1)

    def test_handles_trailing_slashes(self):
        """Should match canvas URIs regardless of trailing slashes."""
        from manuspectrum.utils.iiif_tools import CanvasIIIF

        manifest_v3 = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "items": [
                {"id": "https://example.com/canvas/1", "type": "Canvas"},
            ],
        }

        # Search with trailing slash
        result = CanvasIIIF.get_canvas_index(
            manifest_v3, "https://example.com/canvas/1/"
        )
        self.assertEqual(result, 1)

    def test_returns_none_for_empty_manifest(self):
        """Should return None for empty or None manifest."""
        from manuspectrum.utils.iiif_tools import CanvasIIIF

        self.assertIsNone(
            CanvasIIIF.get_canvas_index(None, "https://example.com/canvas/1")
        )
        self.assertIsNone(
            CanvasIIIF.get_canvas_index({}, "https://example.com/canvas/1")
        )

    def test_returns_none_for_empty_canvas_url(self):
        """Should return None for empty canvas URL."""
        from manuspectrum.utils.iiif_tools import CanvasIIIF

        manifest_v3 = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "items": [{"id": "https://example.com/canvas/1", "type": "Canvas"}],
        }

        self.assertIsNone(CanvasIIIF.get_canvas_index(manifest_v3, None))
        self.assertIsNone(CanvasIIIF.get_canvas_index(manifest_v3, ""))


# =============================================================================
# CANVAS ID RESOLUTION TESTS (issue #32)
# =============================================================================

# VwAnnotation.canvas stores the *image service* URL, not the Canvas id.
# Both manifests below mirror the real Avranches demo data: the Canvas id
# (.../AVRANCHES_MS059/10) differs from the image service URL it displays
# (.../AVRANCHES_MS059_0010.tif).
IMAGE_SERVICE_URL = (
    "https://iiif.unicaen.fr/mrsh/bvmsm/AVRANCHES_MS059/AVRANCHES_MS059_0010.tif"
)
CANVAS_ID = "https://iiif.unicaen.fr/mrsh/bvmsm/AVRANCHES_MS059/10"
MANIFEST_URL = "https://emmsm.unicaen.fr/manifests/Avranches_BM_59.json"

MANIFEST_V2 = {
    "@context": "http://iiif.io/api/presentation/2/context.json",
    "@id": MANIFEST_URL,
    "@type": "sc:Manifest",
    "sequences": [
        {
            "@type": "sc:Sequence",
            "canvases": [
                {
                    "@id": CANVAS_ID,
                    "@type": "sc:Canvas",
                    "images": [
                        {
                            "@type": "oa:Annotation",
                            "resource": {
                                "@id": f"{IMAGE_SERVICE_URL}/full/full/0/default.jpg",
                                "@type": "dctypes:Image",
                                "service": {"@id": IMAGE_SERVICE_URL},
                            },
                        }
                    ],
                },
            ],
        }
    ],
}

MANIFEST_V3 = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": MANIFEST_URL,
    "type": "Manifest",
    "items": [
        {
            "id": CANVAS_ID,
            "type": "Canvas",
            "items": [
                {
                    "type": "AnnotationPage",
                    "items": [
                        {
                            "type": "Annotation",
                            "body": {
                                "id": f"{IMAGE_SERVICE_URL}/full/full/0/default.jpg",
                                "type": "Image",
                                "service": [{"id": IMAGE_SERVICE_URL}],
                            },
                        }
                    ],
                }
            ],
        },
    ],
}


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestResolveCanvasId(TestCase):
    """Tests for _resolve_canvas_id: image service URL -> IIIF Canvas id."""

    def setUp(self):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationMixin

        self.mixin = IIIFAnnotationMixin()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_resolves_image_service_url_to_canvas_id_v2(self):
        """A v2 image service URL should resolve to the Canvas @id."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            result = self.mixin._resolve_canvas_id(IMAGE_SERVICE_URL, MANIFEST_URL)

        self.assertEqual(result, CANVAS_ID)

    def test_resolves_image_service_url_to_canvas_id_v3(self):
        """A v3 image service URL should resolve to the Canvas id."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V3):
            result = self.mixin._resolve_canvas_id(IMAGE_SERVICE_URL, MANIFEST_URL)

        self.assertEqual(result, CANVAS_ID)

    def test_is_idempotent_when_already_a_canvas_id(self):
        """Resolving an actual Canvas id should return it unchanged."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            result = self.mixin._resolve_canvas_id(CANVAS_ID, MANIFEST_URL)

        self.assertEqual(result, CANVAS_ID)

    def test_falls_back_when_manifest_unavailable(self):
        """Should return the stored value when the manifest cannot be fetched."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=None):
            result = self.mixin._resolve_canvas_id(IMAGE_SERVICE_URL, MANIFEST_URL)

        self.assertEqual(result, IMAGE_SERVICE_URL)

    def test_falls_back_when_canvas_not_in_manifest(self):
        """Should return the stored value when no canvas matches."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            result = self.mixin._resolve_canvas_id(
                "https://iiif.unicaen.fr/unknown.tif", MANIFEST_URL
            )

        self.assertEqual(result, "https://iiif.unicaen.fr/unknown.tif")

    def test_returns_input_without_manifest_url(self):
        """No manifest URL means nothing to resolve against."""
        self.assertEqual(
            self.mixin._resolve_canvas_id(IMAGE_SERVICE_URL, None), IMAGE_SERVICE_URL
        )
        self.assertIsNone(self.mixin._resolve_canvas_id(None, MANIFEST_URL))

    def test_caches_resolved_canvas_id(self):
        """Second call should hit the cache instead of re-reading the manifest."""
        with patch.object(
            self.mixin, "_get_manifest_data", return_value=MANIFEST_V2
        ) as mock_manifest:
            self.mixin._resolve_canvas_id(IMAGE_SERVICE_URL, MANIFEST_URL)
            reads_after_cold_call = mock_manifest.call_count
            result = self.mixin._resolve_canvas_id(IMAGE_SERVICE_URL, MANIFEST_URL)

        self.assertEqual(result, CANVAS_ID)
        self.assertEqual(
            mock_manifest.call_count,
            reads_after_cold_call,
            "a resolved canvas id must be served from cache, not re-read",
        )


@override_settings(
    PUBLIC_SERVER_ADDRESS="https://test.example.com/", CACHE_BY_USER={"anonymous": 3600}
)
class TestAnnotationTargetsCanvas(TestCase):
    """The IIIF target must be the Canvas id, never the image service URL."""

    def setUp(self):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationMixin

        self.mixin = IIIFAnnotationMixin()
        self.annotation = {
            "geometry": {"type": "Point", "coordinates": [90.4, -80.2]},
            "canvas": IMAGE_SERVICE_URL,
            "manifest": MANIFEST_URL,
            "analysis_id": str(uuid.uuid4()),
        }
        cache.clear()

        # Dimensions come from the image service over HTTP: stub them everywhere.
        dims_patcher = patch.object(
            self.mixin, "_get_canvas_dimensions", return_value=(4000, 5000)
        )
        self.mock_dims = dims_patcher.start()
        self.addCleanup(dims_patcher.stop)

    def tearDown(self):
        cache.clear()

    def test_target_is_built_on_canvas_id(self):
        """_convert_geojson_to_iiif_target must anchor #xywh on the Canvas id."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            result = self.mixin._convert_geojson_to_iiif_target(self.annotation)

        self.assertTrue(
            result.startswith(f"{CANVAS_ID}#xywh="),
            f"target should be anchored on the Canvas id, got: {result}",
        )
        self.assertNotIn(".tif", result)

    def test_dimensions_still_read_from_image_service(self):
        """Dimensions must keep using the image service URL, not the Canvas id."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            self.mixin._convert_geojson_to_iiif_target(self.annotation)

        self.mock_dims.assert_called_once_with(IMAGE_SERVICE_URL)

    def test_target_without_geometry_is_canvas_id(self):
        """Even without geometry the bare target must be the Canvas id."""
        annotation = dict(self.annotation, geometry=None)

        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            result = self.mixin._convert_geojson_to_iiif_target(annotation)

        self.assertEqual(result, CANVAS_ID)

    def test_payload_passes_canvas_id_to_serializer(self):
        """The serializer must receive the Canvas id as canvas_uri."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            payload = self.mixin._build_annotation_payload(self.annotation)

        self.assertEqual(payload["canvas_uri"], CANVAS_ID)
        self.assertEqual(payload["manifest_url"], MANIFEST_URL)
        self.assertEqual(payload["resource_id"], self.annotation["analysis_id"])
        self.assertTrue(payload["target"].startswith(f"{CANVAS_ID}#xywh="))

    def test_payload_resolves_the_canvas_only_once(self):
        """target and canvas_uri share one resolution, so they cannot diverge."""
        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            with patch.object(
                self.mixin, "_resolve_canvas_id", return_value=CANVAS_ID
            ) as mock_resolve:
                payload = self.mixin._build_annotation_payload(self.annotation)

        mock_resolve.assert_called_once_with(IMAGE_SERVICE_URL, MANIFEST_URL)
        self.assertEqual(payload["target"].split("#")[0], payload["canvas_uri"])

    def test_payload_keys_match_serializer_signature(self):
        """The payload is splatted into to_representation: keys must line up."""
        import inspect

        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            payload = self.mixin._build_annotation_payload(self.annotation)

        accepted = set(
            inspect.signature(IIIFAnnotationSerializer.to_representation).parameters
        )
        self.assertEqual(set(payload) - accepted, set())

    def test_v3_specific_resource_source_is_the_canvas(self):
        """v3 target.source.id must be the Canvas id, matching its "type": "Canvas"."""
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializer,
        )

        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V3):
            payload = self.mixin._build_annotation_payload(self.annotation)

        target = IIIFAnnotationSerializer._build_target(
            payload["target"], payload["canvas_uri"], payload["manifest_url"]
        )

        self.assertEqual(target["type"], "SpecificResource")
        self.assertEqual(target["source"]["id"], CANVAS_ID)
        self.assertEqual(target["source"]["type"], "Canvas")
        self.assertTrue(target["selector"]["value"].startswith("xywh="))

    def test_v2_on_is_the_canvas(self):
        """v2 'on' must be the Canvas id plus fragment (Presentation 2.1 §5.4)."""
        from manuspectrum.views.serializers.iiif_annotation import (
            IIIFAnnotationSerializerV2,
        )

        with patch.object(self.mixin, "_get_manifest_data", return_value=MANIFEST_V2):
            payload = self.mixin._build_annotation_payload(self.annotation)

        on_target = IIIFAnnotationSerializerV2._build_target_v2(
            payload["target"], payload["canvas_uri"], payload["manifest_url"]
        )

        self.assertTrue(on_target.startswith(f"{CANVAS_ID}#xywh="))
        self.assertNotIn(".tif", on_target)


class TestGetCanvasPageNumbers(TestCase):
    """Tests for _get_canvas_page_numbers method in views."""

    def setUp(self):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationCollectionView

        self.view = IIIFAnnotationCollectionView()
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(
        __import__(
            "manuspectrum.views.iiif_annotation",
            fromlist=["IIIFAnnotationCollectionView"],
        ).IIIFAnnotationCollectionView,
        "_get_manifest_data",
    )
    def test_maps_canvas_to_manifest_position(self, mock_get_manifest):
        """Should map canvas URIs to their position in the manifest."""
        # Mock manifest data
        mock_get_manifest.return_value = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "items": [
                {"id": "https://example.com/canvas/1", "type": "Canvas"},
                {"id": "https://example.com/canvas/2", "type": "Canvas"},
                {"id": "https://example.com/canvas/3", "type": "Canvas"},
            ],
        }

        # Grouped annotations - canvas/2 and canvas/3 have annotations
        grouped_annos = {
            "https://example.com/canvas/2": [
                {"manifest": "https://example.com/manifest"}
            ],
            "https://example.com/canvas/3": [
                {"manifest": "https://example.com/manifest"}
            ],
        }

        result = self.view._get_canvas_page_numbers(grouped_annos)

        # canvas/2 is at position 2, canvas/3 is at position 3
        self.assertEqual(result["https://example.com/canvas/2"], 2)
        self.assertEqual(result["https://example.com/canvas/3"], 3)

    @patch.object(
        __import__(
            "manuspectrum.views.iiif_annotation",
            fromlist=["IIIFAnnotationCollectionView"],
        ).IIIFAnnotationCollectionView,
        "_get_manifest_data",
    )
    def test_uses_fallback_when_canvas_not_found(self, mock_get_manifest):
        """Should use hash fallback when canvas is not found in manifest."""
        mock_get_manifest.return_value = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "items": [
                {"id": "https://example.com/canvas/1", "type": "Canvas"},
            ],
        }

        grouped_annos = {
            "https://example.com/canvas/unknown": [
                {"manifest": "https://example.com/manifest"}
            ],
        }

        result = self.view._get_canvas_page_numbers(grouped_annos)

        # Should use hash fallback (not None, and between 1 and 10001)
        page_num = result["https://example.com/canvas/unknown"]
        self.assertIsNotNone(page_num)
        self.assertGreaterEqual(page_num, 1)
        self.assertLessEqual(page_num, 10001)
