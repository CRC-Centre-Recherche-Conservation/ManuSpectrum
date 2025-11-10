"""
IIIF Annotation & collection API
"""
from collections import defaultdict
from functools import lru_cache
import logging
import zlib
import orjson
import hashlib

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from arches.app.models.models import ResourceInstance, ResourceXResource, VwAnnotation
from arches.app.models.resource import Resource

from manuspectrum.views.serializers.iiif_annotation import IIIFAnnotationSerializer

logger = logging.getLogger(__name__)


# ======================================================================================
# Cache utilities
# ======================================================================================

def _cache_etag_key(cache_key: str) -> str:
    return f"{cache_key}__etag"


def cached_json_response(cache_key: str, data: dict, timeout: int = 3600) -> HttpResponse:
    """
    Store or refresh compressed JSON in Redis and build an HTTP response with ETag.
    """
    payload = orjson.dumps(data)
    compressed = zlib.compress(payload)
    etag = hashlib.md5(payload).hexdigest()

    cache.set(cache_key, compressed, timeout)
    cache.set(_cache_etag_key(cache_key), etag, timeout)

    resp = HttpResponse(payload, content_type="application/json")
    resp["ETag"] = etag
    resp["Cache-Control"] = "public, max-age=3600"
    return resp


def get_cached_response(cache_key: str) -> HttpResponse | None:
    """
    Read compressed JSON from Redis (if any) and return an HTTP response with ETag.
    """
    cached = cache.get(cache_key)
    if not cached:
        return None

    try:
        payload = zlib.decompress(cached)
    except Exception:
        # Corrupted cache entry: drop it.
        cache.delete(cache_key)
        cache.delete(_cache_etag_key(cache_key))
        return None

    etag = cache.get(_cache_etag_key(cache_key))
    resp = HttpResponse(payload, content_type="application/json")
    if etag:
        resp["ETag"] = etag
    resp["Cache-Control"] = "public, max-age=3600"
    return resp


# ======================================================================================
# Mixin with shared helpers
# ======================================================================================

class IIIFAnnotationMixin:
    """Shared helpers: display name, canvas dimensions, conversions, bulk fetching."""
    base_url = settings.PUBLIC_SERVER_ADDRESS + "iiif"
    CACHE_TIMEOUT = settings.CACHE_BY_USER["anonymous"]

    def _get_display_name(self, resource):
        if hasattr(resource, "displayname"):
            displayname = resource.displayname
            return displayname() if callable(displayname) else displayname
        return str(resource.resourceinstanceid)

    @lru_cache(maxsize=256)
    def _get_canvas_dimensions(self, canvas_uri: str, manifest_url: str | None = None):
        # Delegates to your project's IIIF tools; LRU avoids repeated lookups.
        from manuspectrum.utils.iiif_tools import CanvasIIIF
        return CanvasIIIF.get_image_service_dimensions(canvas_uri)

    def _convert_geojson_to_iiif_target(self, annotation: dict, zoom: int = 5) -> str:
        """
        Convert a GeoJSON geometry to a IIIF target with xywh fragment.
        """
        geometry = annotation.get("geometry")
        canvas_uri = annotation.get("canvas")
        manifest_url = annotation.get("manifest")

        if not geometry or not canvas_uri:
            return canvas_uri or ""

        canvas_width, canvas_height = self._get_canvas_dimensions(canvas_uri, manifest_url)
        from manuspectrum.utils.iiif_tools import BBoxCalculator

        xywh_fragment = BBoxCalculator.geometry_to_xywh(
            geometry, canvas_width, canvas_height, zoom=zoom, margin=0, radius=0
        )
        return f"{canvas_uri}#{xywh_fragment}" if xywh_fragment else canvas_uri

    def _get_annotations_from_analyses(self, analyses: list[Resource]) -> list[dict]:
        """
        Optimized single-query fetch for all annotations associated to multiple analyses.
        Each VwAnnotation produces (in your model) exactly one IIIF Annotation.
        """
        annotations: list[dict] = []
        analysis_ids = [a.resourceinstanceid for a in analyses]
        if not analysis_ids:
            return annotations

        vw_annotations = VwAnnotation.objects.filter(resourceinstance_id__in=analysis_ids)

        for vw_anno in vw_annotations:
            try:
                feature = vw_anno.feature or {}
                if not feature:
                    continue
                props = feature.get("properties", {}) or {}
                geometry = feature.get("geometry", {}) or {}

                annotations.append({
                    "id": vw_anno.resourceinstance_id,
                    "geometry": geometry,
                    "properties": props,
                    "canvas": props.get("canvas"),
                    "manifest": props.get("manifest"),
                    "analysis_id": str(vw_anno.resourceinstance_id),
                    "analysis_label": props.get("label") or "",
                })
            except Exception as e:
                logger.error(f"Error parsing annotation: {e}")
        return annotations


# ======================================================================================
# Collection View
# ======================================================================================

class IIIFAnnotationCollectionView(IIIFAnnotationMixin, View):
    """
    Returns a IIIF AnnotationCollection for a Document or a Component.

    - Groups annotations by Canvas => each group becomes an AnnotationPage.
    - Adds pagination (first/last + items list with next/prev on each page).
    - Heavy responses are cached (compressed) with ETag headers.

    URL: /iiif/annotation-collection/<uuid:resource_id>
    """

    ANALYSIS_GRAPH_ID = "60c85aba-f079-45bc-997f-21cdd4f77b6d"
    DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
    COMPONENT_GRAPH_ID = "d47595b4-f8a6-419c-8f33-b388206280c4"

    def get(self, request, resource_id):
        cache_key = f"iiif_collection_{resource_id}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            resource = ResourceInstance.objects.get(resourceinstanceid=resource_id)
            analyses = self._get_related_analyses(resource)
            if not analyses:
                return JsonResponse({"error": "No analyses found"}, status=404)

            annotations = self._get_annotations_from_analyses(analyses)
            if not annotations:
                return JsonResponse({"error": "No annotations found for analyses"}, status=404)

            grouped_annos = self._group_by_canvas(annotations)
            collection = self._build_annotation_collection(resource, grouped_annos)

            return cached_json_response(cache_key, collection, self.CACHE_TIMEOUT)

        except ResourceInstance.DoesNotExist:
            return JsonResponse({"error": "Resource not found"}, status=404)
        except Exception as e:
            logger.error(f"Error generating collection: {e}")
            return JsonResponse({"error": str(e)}, status=500)

    def _get_related_analyses(self, resource: ResourceInstance) -> list[Resource]:
        """
        Fetch related 'Analysis' resources for a given Component or Document
        with minimal queries (filter by IDs).
        """
        rid = resource.resourceinstanceid
        graph_id = str(resource.graph_id)

        rels = []
        if graph_id == self.COMPONENT_GRAPH_ID:
            rels = ResourceXResource.objects.filter(
                to_resource_id=rid,
                from_resource_graph_id=self.ANALYSIS_GRAPH_ID
            ).values_list("from_resource_id", flat=True)

        elif graph_id == self.DOCUMENT_GRAPH_ID:
            direct = list(ResourceXResource.objects.filter(
                to_resource_id=rid,
                from_resource_graph_id=self.ANALYSIS_GRAPH_ID
            ).values_list("from_resource_id", flat=True))

            components = list(ResourceXResource.objects.filter(
                to_resource_id=rid,
                from_resource_graph_id=self.COMPONENT_GRAPH_ID
            ).values_list("from_resource_id", flat=True))

            rels = direct
            if components:
                rels += list(ResourceXResource.objects.filter(
                    to_resource_id__in=components,
                    from_resource_graph_id=self.ANALYSIS_GRAPH_ID
                ).values_list("from_resource_id", flat=True))

        if not rels:
            return []

        return list(Resource.objects.filter(resourceinstanceid__in=rels))

    def _group_by_canvas(self, annotations: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for a in annotations:
            canvas = a.get("canvas")
            if canvas:
                grouped[canvas].append(a)
        return grouped

    def _build_annotation_collection(self, resource: ResourceInstance, grouped_annos: dict) -> dict:
        collection_id = f"{self.base_url}/annotation-collection/{resource.resourceinstanceid}"
        pages = []
        canvas_uris = list(grouped_annos.keys())
        total = 0

        for idx, canvas_uri in enumerate(canvas_uris):
            annos = grouped_annos[canvas_uri]
            total += len(annos)

            items = []
            for a in annos:
                target = self._convert_geojson_to_iiif_target(a)
                items.append(IIIFAnnotationSerializer.to_representation(target, resource_id=str(a['analysis_id'])))

            page = {
                "id": f"{collection_id}/page-{idx}",
                "type": "AnnotationPage",
                "items": items,
                "partOf": collection_id,
            }
            if idx < len(canvas_uris) - 1:
                page["next"] = f"{collection_id}/page-{idx + 1}"
            if idx > 0:
                page["prev"] = f"{collection_id}/page-{idx - 1}"
            pages.append(page)

        collection = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": collection_id,
            "type": "AnnotationCollection",
            "label": {"fr": [f"Analyses pour {self._get_display_name(resource)}"]},
            "total": total,
        }
        if pages:
            collection["first"], collection["last"] = pages[0]["id"], pages[-1]["id"]
            collection["items"] = pages
        return collection


# ======================================================================================
# Page View
# ======================================================================================

class IIIFAnnotationPageView(IIIFAnnotationMixin, View):
    """
    Returns a single IIIF AnnotationPage belonging to a collection.
    Cached independently to avoid re-sending large collections.

    URL: /iiif/annotation-collection/<uuid:resource_id>/page-<int:page_num>
    """

    def get(self, request, resource_id, page_num: int):
        cache_key = f"iiif_page_{resource_id}_{page_num}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            resource = ResourceInstance.objects.get(resourceinstanceid=resource_id)
            collection_view = IIIFAnnotationCollectionView()
            analyses = collection_view._get_related_analyses(resource)
            if not analyses:
                return JsonResponse({"error": "No analyses found"}, status=404)

            annotations = self._get_annotations_from_analyses(analyses)
            grouped = collection_view._group_by_canvas(annotations)

            canvas_uris = list(grouped.keys())
            if page_num < 0 or page_num >= len(canvas_uris):
                return JsonResponse({"error": "Page not found"}, status=404)

            canvas_uri = canvas_uris[page_num]
            annos = grouped[canvas_uri]
            collection_id = f"{self.base_url}/annotation-collection/{resource_id}"
            page_id = f"{collection_id}/page-{page_num}"

            items = []
            for a in annos:
                target = self._convert_geojson_to_iiif_target(a)
                items.append(IIIFAnnotationSerializer.to_representation(target, resource_id=str(a['analysis_id'])))

            page = {
                "@context": "http://iiif.io/api/presentation/3/context.json",
                "id": page_id,
                "type": "AnnotationPage",
                "items": items,
                "partOf": {
                    "id": collection_id,
                    "type": "AnnotationCollection",
                    "label": {"fr": [f"Analyses pour {self._get_display_name(resource)}"]},
                },
            }
            if page_num < len(canvas_uris) - 1:
                page["next"] = f"{collection_id}/page-{page_num + 1}"
            if page_num > 0:
                page["prev"] = f"{collection_id}/page-{page_num - 1}"

            return cached_json_response(cache_key, page, self.CACHE_TIMEOUT)

        except ResourceInstance.DoesNotExist:
            return JsonResponse({"error": "Resource not found"}, status=404)
        except Exception as e:
            logger.error(f"Error generating IIIF page: {e}")
            return JsonResponse({"error": str(e)}, status=500)


# ======================================================================================
# Single Annotation View
# ======================================================================================

class IIIFAnnotationView(IIIFAnnotationMixin, View):
    """
    Returns a single IIIF Annotation for a given 'Analysis' resource.

    URL: /iiif/annotation/<uuid:resource_id>
    """
    ANALYSIS_GRAPH_ID = "60c85aba-f079-45bc-997f-21cdd4f77b6d"

    def get(self, request, resource_id):
        cache_key = f"iiif_annotation_{resource_id}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            analysis = Resource.objects.get(resourceinstanceid=resource_id)
            if str(analysis.graph_id) != self.ANALYSIS_GRAPH_ID:
                return JsonResponse({"error": "Resource is not an Analysis"}, status=400)

            annos = self._get_annotations_from_analyses([analysis])
            if not annos:
                return JsonResponse({"error": "No annotation data"}, status=404)

            anno = annos[0]  # 1 analysis -> 1 annotation (your data model)
            target = self._convert_geojson_to_iiif_target(anno)
            iiif_annotation = IIIFAnnotationSerializer.to_representation(target, resource_id=str(resource_id))

            return cached_json_response(cache_key, iiif_annotation, self.CACHE_TIMEOUT)

        except Resource.DoesNotExist:
            return JsonResponse({"error": "Annotation not found"}, status=404)
        except Exception as e:
            logger.error(f"Error generating annotation: {e}")
            return JsonResponse({"error": str(e)}, status=500)


# ======================================================================================
# Cache invalidation signals
# ======================================================================================

def _delete_cache_keys(keys: list[str]):
    for key in keys:
        try:
            cache.delete(key)
            cache.delete(_cache_etag_key(key))
        except Exception:
            pass


def _delete_page_patterns(resource_id):
    """
    Delete all page caches for a given resource_id.
    Requires a cache backend with delete_pattern (django-redis provides it).
    """
    pattern = f"iiif_page_{resource_id}_*"
    try:
        cache.delete_pattern(pattern)
    except Exception:
        pass


def _invalidate_for_analysis_id(analysis_uuid):
    """
    Invalidate:
      - the single annotation cache for this analysis
      - any collections/pages that include this analysis via Component and/or Document.
    """
    _delete_cache_keys([f"iiif_annotation_{analysis_uuid}"])

    ANALYSIS_GRAPH = "60c85aba-f079-45bc-997f-21cdd4f77b6d"
    DOCUMENT_GRAPH = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
    COMPONENT_GRAPH = "d47595b4-f8a6-419c-8f33-b388206280c4"

    rels = ResourceXResource.objects.filter(from_resource_id=analysis_uuid)

    doc_ids = set()
    component_ids = set()

    for r in rels:
        to_gid = str(r.to_resource_graph_id) if r.to_resource_graph_id else None
        if to_gid == DOCUMENT_GRAPH:
            doc_ids.add(r.to_resource_id)
        elif to_gid == COMPONENT_GRAPH:
            component_ids.add(r.to_resource_id)

    if component_ids:
        comp_to_doc = ResourceXResource.objects.filter(
            from_resource_id__in=list(component_ids)
        )
        for r in comp_to_doc:
            to_gid = str(r.to_resource_graph_id) if r.to_resource_graph_id else None
            if to_gid == DOCUMENT_GRAPH:
                doc_ids.add(r.to_resource_id)

    if not doc_ids:
        return

    for doc_id in doc_ids:
        _delete_cache_keys([f"iiif_collection_{doc_id}"])
        _delete_page_patterns(doc_id)


@receiver([post_save, post_delete], sender=VwAnnotation)
def invalidate_on_vwannotation_change(sender, instance: VwAnnotation, **kwargs):
    """
    Any change to a VwAnnotation affects the corresponding Analysis and
    thus any Collections/Pages that include it.
    """
    try:
        analysis_uuid = instance.resourceinstance_id
        _invalidate_for_analysis_id(analysis_uuid)
    except Exception as e:
        logger.error(f"Cache invalidation (VwAnnotation) failed: {e}")


@receiver([post_save, post_delete], sender=ResourceXResource)
def invalidate_on_relation_change(sender, instance: ResourceXResource, **kwargs):
    """
    If a relation is created/removed involving an Analysis -> Component/Document,
    we must invalidate Collections/Pages that depend on this linkage.
    """
    try:
        ANALYSIS_GRAPH = "60c85aba-f079-45bc-997f-21cdd4f77b6d"
        is_analysis_from = str(instance.from_resource_graph_id) == ANALYSIS_GRAPH
        is_analysis_to = str(instance.to_resource_graph_id) == ANALYSIS_GRAPH

        if is_analysis_from:
            _invalidate_for_analysis_id(instance.from_resource_id)

        elif is_analysis_to:
            _invalidate_for_analysis_id(instance.to_resource_id)

        else:
            DOCUMENT_GRAPH = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
            COMPONENT_GRAPH = "d47595b4-f8a6-419c-8f33-b388206280c4"
            to_gid = str(instance.to_resource_graph_id) if instance.to_resource_graph_id else None
            from_gid = str(instance.from_resource_graph_id) if instance.from_resource_graph_id else None

            if from_gid == COMPONENT_GRAPH and to_gid == DOCUMENT_GRAPH:
                doc_id = instance.to_resource_id
                _delete_cache_keys([f"iiif_collection_{doc_id}"])
                _delete_page_patterns(doc_id)

    except Exception as e:
        logger.error(f"Cache invalidation (ResourceXResource) failed: {e}")