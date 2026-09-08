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
from django.db.models import Q

from arches.app.models.models import ResourceInstance, ResourceXResource, VwAnnotation
from arches.app.models.resource import Resource

from manuspectrum.views.serializers.iiif_annotation import (
    IIIFAnnotationSerializer,
    IIIFAnnotationSerializerV2,
)

logger = logging.getLogger(__name__)


# ======================================================================================
# Cache utilities
# ======================================================================================


def _cache_etag_key(cache_key: str) -> str:
    return f"{cache_key}__etag"


def cached_json_response(
    cache_key: str, data: dict, timeout: int = 3600
) -> HttpResponse:
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

    # Graph IDs (centralized for all IIIF annotation views)
    ANALYSIS_GRAPH_ID = "60c85aba-f079-45bc-997f-21cdd4f77b6d"
    DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
    COMPONENT_GRAPH_ID = "d47595b4-f8a6-419c-8f33-b388206280c4"

    def _get_display_name(self, resource: ResourceInstance):
        if hasattr(resource, "displayname"):
            displayname = resource.displayname
            return displayname() if callable(displayname) else displayname
        return str(resource.resourceinstanceid)

    def _get_manifest_data(self, manifest_url: str | None) -> dict | None:
        """
        Fetch and cache manifest data.
        Returns the parsed manifest JSON or None if not found.
        """
        if not manifest_url:
            return None

        cache_key = f"iiif_manifest_data:{manifest_url}"
        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Manifest cache hit for: {manifest_url}")
            return cached

        from manuspectrum.utils.iiif_tools import CanvasIIIF

        logger.info(f"Fetching manifest from: {manifest_url}")
        manifest_data = CanvasIIIF.fetch_manifest(manifest_url)
        if manifest_data:
            cache.set(cache_key, manifest_data, timeout=self.CACHE_TIMEOUT)
            logger.debug(
                f"Manifest fetched successfully, {len(manifest_data.get('items', manifest_data.get('sequences', [])))} canvases found"
            )
        else:
            logger.warning(f"Failed to fetch manifest from: {manifest_url}")
        return manifest_data

    def _get_canvas_page_num(
        self, canvas_uri: str, manifest_url: str | None
    ) -> int | None:
        """
        Get the 1-based page number (index in manifest) for a canvas.
        Returns the position of the canvas in the manifest's sequence/items.
        """
        if not canvas_uri or not manifest_url:
            logger.debug(
                f"Missing canvas_uri ({canvas_uri}) or manifest_url ({manifest_url})"
            )
            return None

        cache_key = f"iiif_canvas_pagenum:{canvas_uri}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        manifest_data = self._get_manifest_data(manifest_url)
        if not manifest_data:
            return None

        from manuspectrum.utils.iiif_tools import CanvasIIIF

        page_num = CanvasIIIF.get_canvas_index(manifest_data, canvas_uri)
        if page_num is not None:
            cache.set(cache_key, page_num, timeout=self.CACHE_TIMEOUT)
        else:
            logger.debug(f"Canvas '{canvas_uri}' not found in manifest items/sequences")
        return page_num

    def _resolve_canvas_id(
        self, canvas_uri: str | None, manifest_url: str | None
    ) -> str | None:
        """
        Resolve the value stored in ``VwAnnotation.canvas`` to a real IIIF Canvas id.

        ``VwAnnotation.canvas`` holds the *image service* URL
        (…/AVRANCHES_MS059_0010.tif), not the Canvas id (…/AVRANCHES_MS059/10), and
        it must stay that way: Arches' Leaflet annotation editor builds its tile
        requests from it, as do both thumbnail fetchers — see the comment at
        ``views/biblissima_proxy.py`` where the ingestion deliberately prefers
        ``imageServiceUrl`` over the ``canvasId`` it also has in hand.

        IIIF export needs the opposite: annotations must be attached to a Canvas
        (Presentation 2.1 §5.4, 3.0 §2.2), and Mirador filters on
        `canvasIds.includes(targetId)`, silently dropping anything that targets an
        image resource. One column, two consumers with opposite needs — hence the
        translation here, at the export boundary, rather than in the stored data.

        Returns the Canvas id, or ``canvas_uri`` unchanged when it cannot be resolved
        (already a Canvas id, canvas absent from the manifest, manifest unreachable).
        """
        if not canvas_uri or not manifest_url:
            return canvas_uri

        cache_key = f"iiif_canvas_id:{canvas_uri}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        # _get_canvas_page_num already fetches the manifest, runs get_canvas_index
        # and caches the position: reuse it rather than scanning the manifest twice
        # for the same canvas within a single request.
        index = self._get_canvas_page_num(canvas_uri, manifest_url)

        canvas_id = None
        if index is not None:
            from manuspectrum.utils.iiif_tools import CanvasIIIF

            manifest_data = self._get_manifest_data(manifest_url)
            _, canvas_id = CanvasIIIF.get_canvas_by_index(manifest_data, index)

        if not canvas_id:
            logger.warning(
                f"Could not resolve a canvas id for '{canvas_uri}' "
                f"in manifest '{manifest_url}'; targeting the stored value, "
                "which viewers will not render on the canvas."
            )
            return canvas_uri

        cache.set(cache_key, canvas_id, timeout=self.CACHE_TIMEOUT)
        return canvas_id

    @lru_cache(maxsize=256)
    def _get_canvas_dimensions(self, canvas_uri: str):
        """
        Retrieve canvas width/height from the IIIF infrastructure.
        Expects an image service URL (its /info.json carries the dimensions).
        """
        cache_key = f"iiif_canvas_dim:{canvas_uri}"

        dims = cache.get(cache_key)
        if dims and isinstance(dims, (list, tuple)) and len(dims) == 2:
            return dims[0], dims[1]

        from manuspectrum.utils.iiif_tools import CanvasIIIF

        width, height = CanvasIIIF.get_image_service_dimensions(canvas_uri)
        cache.set(cache_key, (width, height), timeout=self.CACHE_TIMEOUT)

        return width, height

    def _convert_geojson_to_iiif_target(
        self, annotation: dict, zoom: int = 5, canvas_id: str | None = None
    ) -> str:
        """
        Convert a GeoJSON geometry to a IIIF target with xywh fragment.

        The fragment is anchored on the *Canvas id*: the coordinate space of an
        annotation is defined by the Canvas, not by the image resource. Pass
        ``canvas_id`` when it has already been resolved, to avoid resolving twice.
        """
        geometry = annotation.get("geometry")
        image_service_url = annotation.get("canvas")
        manifest_url = annotation.get("manifest")

        target_base = canvas_id or self._resolve_canvas_id(
            image_service_url, manifest_url
        )

        if not geometry or not image_service_url:
            return target_base or ""

        canvas_width, canvas_height = self._get_canvas_dimensions(image_service_url)

        from manuspectrum.utils.iiif_tools import BBoxCalculator

        xywh_fragment = BBoxCalculator.geometry_to_xywh(
            geometry,
            canvas_width,
            canvas_height,
            zoom=zoom,
            margin=0,
            radius=0,
        )
        return f"{target_base}#{xywh_fragment}" if xywh_fragment else target_base

    def _build_annotation_payload(
        self, annotation: dict, resource_id: str | None = None
    ) -> dict:
        """
        Build the serializer payload for a single annotation.

        ``canvas_uri`` handed over to the serializers is always the resolved Canvas
        id, never the image service URL stored in ``VwAnnotation.canvas`` — the v3
        serializer labels it ``"type": "Canvas"`` and the v2 one uses it as ``on``.
        Resolving here once keeps that id and the base of ``target`` identical by
        construction; the serializers rely on the two agreeing.

        The returned keys match the serializers' ``to_representation`` signature.
        """
        manifest_url = annotation.get("manifest")
        canvas_id = self._resolve_canvas_id(annotation.get("canvas"), manifest_url)
        return {
            "target": self._convert_geojson_to_iiif_target(
                annotation, canvas_id=canvas_id
            ),
            "resource_id": resource_id or str(annotation["analysis_id"]),
            "canvas_uri": canvas_id,
            "manifest_url": manifest_url,
        }

    def _get_annotations_from_analyses(self, analyses: list[Resource]) -> list[dict]:
        """
        Optimized single-query fetch for all annotations associated to multiple analyses.
        Each VwAnnotation produces (in your model) exactly one IIIF Annotation.
        """
        annotations: list[dict] = []
        analysis_ids = [a.resourceinstanceid for a in analyses]
        if not analysis_ids:
            return annotations

        vw_annotations = VwAnnotation.objects.filter(
            resourceinstance_id__in=analysis_ids
        )

        for vw_anno in vw_annotations:
            try:
                feature = vw_anno.feature or {}
                if not feature:
                    continue
                props = feature.get("properties", {}) or {}
                geometry = feature.get("geometry", {}) or {}

                # Use canvas directly from VwAnnotation (SQL view column)
                # instead of props.get("canvas") which may have a different format
                canvas_uri = vw_anno.canvas or props.get("canvas")

                annotations.append(
                    {
                        "id": vw_anno.resourceinstance_id,
                        "geometry": geometry,
                        "properties": props,
                        "canvas": canvas_uri,
                        "manifest": props.get("manifest"),
                        "analysis_id": str(vw_anno.resourceinstance_id),
                        "analysis_label": props.get("label") or "",
                    }
                )
            except Exception as e:  # pragma: no cover
                logger.error(f"Error parsing annotation: {e}")
        return annotations


# ======================================================================================
# Collection View
# ======================================================================================


class IIIFAnnotationCollectionView(IIIFAnnotationMixin, View):
    """
    Returns a IIIF v3 AnnotationCollection for a Document or a Component.

    - Groups annotations by Canvas => each group becomes an AnnotationPage.
    - Adds pagination (first/last + items list with next/prev on each page).
    - Heavy responses are cached (compressed) with ETag headers.

    URL: /iiif/v3/annotation-collection/<uuid:resource_id>
    """

    def get(self, request, resource_id):
        cache_key = f"iiif_v3_collection_{resource_id}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            resource = ResourceInstance.objects.select_related("graph").get(
                resourceinstanceid=resource_id
            )

            analyses = self._get_related_analyses(resource)
            if not analyses:
                return JsonResponse({"error": "No analyses found"}, status=404)

            annotations = self._get_annotations_from_analyses(analyses)
            if not annotations:
                return JsonResponse(
                    {"error": "No annotations found for analyses"}, status=404
                )

            grouped_annos = self._group_by_canvas(annotations)

            all_annotation_data: list[dict] = []
            canvas_mapping: dict[str, list[int]] = {}

            for canvas_uri, canvas_annotations in grouped_annos.items():
                for a in canvas_annotations:
                    idx = len(all_annotation_data)
                    all_annotation_data.append(self._build_annotation_payload(a))
                    canvas_mapping.setdefault(canvas_uri, []).append(idx)

            # Batch serialize all annotations
            serialized = IIIFAnnotationSerializer.batch_to_representation(
                all_annotation_data
            )

            # regroup canvas
            grouped_serialized: dict[str, list[dict]] = {}
            for canvas_uri, indices in canvas_mapping.items():
                grouped_serialized[canvas_uri] = [serialized[i] for i in indices]

            collection = self._build_annotation_collection(resource, grouped_serialized)

            return cached_json_response(cache_key, collection, self.CACHE_TIMEOUT)

        except ResourceInstance.DoesNotExist:
            return JsonResponse({"error": "Resource not found"}, status=404)
        except Exception as e:  # pragma: no cover
            logger.error(f"Error generating collection: {e}")
            return JsonResponse({"error": str(e)}, status=500)

    def _get_related_analyses(self, resource: ResourceInstance) -> list[Resource]:
        """
        Fetch related 'Analysis' resources for a given Component or Document
        with minimal queries (filter by IDs, pas de boucle ORM).
        """
        rid = resource.resourceinstanceid
        graph_id = str(resource.graph_id)

        if graph_id == self.COMPONENT_GRAPH_ID:
            analysis_ids = list(
                ResourceXResource.objects.filter(
                    to_resource_id=rid,
                    from_resource_graph_id=self.ANALYSIS_GRAPH_ID,
                ).values_list("from_resource_id", flat=True)
            )

        elif graph_id == self.DOCUMENT_GRAPH_ID:
            rels = ResourceXResource.objects.filter(
                Q(to_resource_id=rid, from_resource_graph_id=self.ANALYSIS_GRAPH_ID)
                | Q(to_resource_id=rid, from_resource_graph_id=self.COMPONENT_GRAPH_ID)
            ).values_list("from_resource_id", "from_resource_graph_id")

            analysis_ids: list = []
            component_ids: list = []

            for res_id, g in rels:
                if str(g) == self.ANALYSIS_GRAPH_ID:
                    analysis_ids.append(res_id)
                else:
                    component_ids.append(res_id)

            if component_ids:
                indirect = ResourceXResource.objects.filter(
                    to_resource_id__in=component_ids,
                    from_resource_graph_id=self.ANALYSIS_GRAPH_ID,
                ).values_list("from_resource_id", flat=True)
                analysis_ids.extend(indirect)
        else:
            analysis_ids = []

        if not analysis_ids:
            return []

        return list(
            Resource.objects.filter(resourceinstanceid__in=analysis_ids).only(
                "resourceinstanceid", "graph_id"
            )
        )

    def _group_by_canvas(self, annotations: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for a in annotations:
            canvas = a.get("canvas")
            if canvas:
                grouped[canvas].append(a)
        return grouped

    def _get_canvas_page_numbers(self, grouped_annos: dict) -> dict[str, int]:
        """
        Get page numbers for each canvas based on their position in the manifest.
        Returns a dict mapping canvas_uri -> page_num (1-indexed).
        """
        canvas_page_nums: dict[str, int] = {}

        for canvas_uri, annos in grouped_annos.items():
            # Get manifest URL from first annotation
            manifest_url = None
            for anno in annos:
                manifest_url = anno.get("manifest")
                if manifest_url:
                    break

            # Get page number from manifest position
            page_num = self._get_canvas_page_num(canvas_uri, manifest_url)
            if page_num is None:
                # Fallback: use hash-based number to avoid collisions
                logger.warning(
                    f"Could not find canvas index for '{canvas_uri}' in manifest '{manifest_url}'. "
                    "Using hash fallback."
                )
                page_num = hash(canvas_uri) % 10000 + 1

            canvas_page_nums[canvas_uri] = page_num

        return canvas_page_nums

    def _build_annotation_collection(
        self, resource: ResourceInstance, grouped_annos: dict
    ) -> dict:
        collection_id = (
            f"{self.base_url}/v3/annotation-collection/{resource.resourceinstanceid}"
        )
        pages: list[dict] = []
        total = 0

        # Get real page numbers from manifest positions
        canvas_page_nums = self._get_canvas_page_numbers(grouped_annos)

        # Sort canvases by their page number
        sorted_canvases = sorted(
            grouped_annos.keys(), key=lambda uri: canvas_page_nums.get(uri, 0)
        )
        sorted_page_nums = [canvas_page_nums[uri] for uri in sorted_canvases]

        for idx, canvas_uri in enumerate(sorted_canvases):
            items = grouped_annos[canvas_uri]
            total += len(items)
            page_num = canvas_page_nums[canvas_uri]

            page = {
                "id": f"{collection_id}/page-{page_num}",
                "type": "AnnotationPage",
                "items": items,
                "partOf": collection_id,
            }
            # Add next/prev links based on sorted order
            if idx < len(sorted_canvases) - 1:
                next_page_num = sorted_page_nums[idx + 1]
                page["next"] = f"{collection_id}/page-{next_page_num}"
            if idx > 0:
                prev_page_num = sorted_page_nums[idx - 1]
                page["prev"] = f"{collection_id}/page-{prev_page_num}"
            pages.append(page)

        collection: dict = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": collection_id,
            "type": "AnnotationCollection",
            "label": {"fr": [f"Analyses pour {self._get_display_name(resource)}"]},
            "total": total,
        }
        if pages:
            collection["first"] = pages[0]["id"]
            collection["last"] = pages[-1]["id"]
            collection["items"] = pages
        return collection


# ======================================================================================
# Page View
# ======================================================================================


class IIIFAnnotationPageView(IIIFAnnotationMixin, View):
    """
    Returns a single IIIF v3 AnnotationPage belonging to a collection.
    Cached independently to avoid re-sending large collections.

    URL: /iiif/v3/annotation-collection/<uuid:resource_id>/page-<int:page_num>
    """

    def get(self, request, resource_id, page_num: int):
        cache_key = f"iiif_v3_page_{resource_id}_{page_num}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            resource = ResourceInstance.objects.select_related("graph").get(
                resourceinstanceid=resource_id
            )

            collection_view = IIIFAnnotationCollectionView()
            analyses = collection_view._get_related_analyses(resource)
            if not analyses:
                return JsonResponse({"error": "No analyses found"}, status=404)

            annotations = self._get_annotations_from_analyses(analyses)
            grouped = collection_view._group_by_canvas(annotations)

            # Get real page numbers from manifest positions
            canvas_page_nums = collection_view._get_canvas_page_numbers(grouped)

            # Find the canvas with the requested page number
            canvas_uri = None
            for uri, pnum in canvas_page_nums.items():
                if pnum == page_num:
                    canvas_uri = uri
                    break

            if not canvas_uri:
                return JsonResponse({"error": "Page not found"}, status=404)

            annos = grouped[canvas_uri]

            annotation_data = [self._build_annotation_payload(a) for a in annos]

            items = IIIFAnnotationSerializer.batch_to_representation(annotation_data)

            collection_id = f"{self.base_url}/v3/annotation-collection/{resource_id}"
            page_id = f"{collection_id}/page-{page_num}"

            page: dict = {
                "@context": "http://iiif.io/api/presentation/3/context.json",
                "id": page_id,
                "type": "AnnotationPage",
                "items": items,
                "partOf": {
                    "id": collection_id,
                    "type": "AnnotationCollection",
                    "label": {
                        "fr": [f"Analyses pour {self._get_display_name(resource)}"]
                    },
                },
            }

            # Calculate next/prev based on sorted page numbers
            sorted_page_nums = sorted(canvas_page_nums.values())
            current_idx = (
                sorted_page_nums.index(page_num) if page_num in sorted_page_nums else -1
            )

            if current_idx >= 0 and current_idx < len(sorted_page_nums) - 1:
                page["next"] = (
                    f"{collection_id}/page-{sorted_page_nums[current_idx + 1]}"
                )
            if current_idx > 0:
                page["prev"] = (
                    f"{collection_id}/page-{sorted_page_nums[current_idx - 1]}"
                )

            return cached_json_response(cache_key, page, self.CACHE_TIMEOUT)

        except ResourceInstance.DoesNotExist:
            return JsonResponse({"error": "Resource not found"}, status=404)
        except Exception as e:  # pragma: no cover
            logger.error(f"Error generating IIIF page: {e}")
            return JsonResponse({"error": str(e)}, status=500)


# ======================================================================================
# Single Annotation View
# ======================================================================================


class IIIFAnnotationView(IIIFAnnotationMixin, View):
    """
    Returns a single IIIF Annotation for a given 'Analysis' resource.

    URL: /iiif/v3/annotation/<uuid:resource_id>
    """

    def get(self, request, resource_id):
        cache_key = f"iiif_v3_annotation_{resource_id}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            analysis = Resource.objects.get(resourceinstanceid=resource_id)
            if str(analysis.graph_id) != self.ANALYSIS_GRAPH_ID:
                return JsonResponse(
                    {"error": "Resource is not an Analysis"}, status=400
                )

            annos = self._get_annotations_from_analyses([analysis])
            if not annos:
                return JsonResponse({"error": "No annotation data"}, status=404)

            anno = annos[0]  # 1 analysis -> 1 annotation
            payload = self._build_annotation_payload(anno, resource_id=str(resource_id))
            iiif_annotation = IIIFAnnotationSerializer.to_representation(**payload)

            return cached_json_response(cache_key, iiif_annotation, self.CACHE_TIMEOUT)

        except Resource.DoesNotExist:
            return JsonResponse({"error": "Annotation not found"}, status=404)
        except Exception as e:  # pragma: no cover
            logger.error(f"Error generating annotation: {e}")
            return JsonResponse({"error": str(e)}, status=500)


# ======================================================================================
# V2 Views (IIIF Presentation API 2.0 / Open Annotation)
# ======================================================================================


class IIIFAnnotationCollectionViewV2(IIIFAnnotationMixin, View):
    """
    Returns a IIIF v2 sc:Layer for a Document or a Component.

    - Groups annotations by Canvas => each group becomes an sc:AnnotationList.
    - The Layer references all AnnotationLists via otherContent.
    - Heavy responses are cached (compressed) with ETag headers.

    URL: /iiif/v2/annotation-collection/<uuid:resource_id>
    """

    def get(self, request, resource_id):
        cache_key = f"iiif_v2_collection_{resource_id}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            resource = ResourceInstance.objects.select_related("graph").get(
                resourceinstanceid=resource_id
            )

            # Reuse v3 logic for fetching analyses
            collection_view = IIIFAnnotationCollectionView()
            analyses = collection_view._get_related_analyses(resource)
            if not analyses:
                return JsonResponse({"error": "No analyses found"}, status=404)

            annotations = self._get_annotations_from_analyses(analyses)
            if not annotations:
                return JsonResponse(
                    {"error": "No annotations found for analyses"}, status=404
                )

            grouped_annos = collection_view._group_by_canvas(annotations)

            # Build v2 Layer structure
            layer = self._build_layer(resource, grouped_annos)

            return cached_json_response(cache_key, layer, self.CACHE_TIMEOUT)

        except ResourceInstance.DoesNotExist:
            return JsonResponse({"error": "Resource not found"}, status=404)
        except Exception as e:  # pragma: no cover
            logger.error(f"Error generating v2 collection: {e}")
            return JsonResponse({"error": str(e)}, status=500)

    def _build_layer(self, resource: ResourceInstance, grouped_annos: dict) -> dict:
        """Build a sc:Layer structure referencing all AnnotationLists."""
        layer_id = (
            f"{self.base_url}/v2/annotation-collection/{resource.resourceinstanceid}"
        )

        # Get real page numbers from manifest positions (reuse v3 logic)
        collection_view = IIIFAnnotationCollectionView()
        canvas_page_nums = collection_view._get_canvas_page_numbers(grouped_annos)

        # Sort canvases by their page number
        sorted_canvases = sorted(
            grouped_annos.keys(), key=lambda uri: canvas_page_nums.get(uri, 0)
        )

        other_content = []
        for canvas_uri in sorted_canvases:
            page_num = canvas_page_nums[canvas_uri]
            other_content.append(
                {
                    "@id": f"{layer_id}/page-{page_num}",
                    "@type": "sc:AnnotationList",
                }
            )

        layer: dict = {
            "@context": "http://iiif.io/api/presentation/2/context.json",
            "@id": layer_id,
            "@type": "sc:Layer",
            "label": f"Analyses pour {self._get_display_name(resource)}",
        }

        if other_content:
            layer["otherContent"] = other_content

        return layer


class IIIFAnnotationPageViewV2(IIIFAnnotationMixin, View):
    """
    Returns a single IIIF v2 sc:AnnotationList belonging to a Layer.
    Cached independently to avoid re-sending large collections.

    URL: /iiif/v2/annotation-collection/<uuid:resource_id>/page-<int:page_num>
    """

    def get(self, request, resource_id, page_num: int):
        cache_key = f"iiif_v2_page_{resource_id}_{page_num}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            resource = ResourceInstance.objects.select_related("graph").get(
                resourceinstanceid=resource_id
            )

            collection_view = IIIFAnnotationCollectionView()
            analyses = collection_view._get_related_analyses(resource)
            if not analyses:
                return JsonResponse({"error": "No analyses found"}, status=404)

            annotations = self._get_annotations_from_analyses(analyses)
            grouped = collection_view._group_by_canvas(annotations)

            # Get real page numbers from manifest positions
            canvas_page_nums = collection_view._get_canvas_page_numbers(grouped)

            # Find the canvas with the requested page number
            canvas_uri = None
            for uri, pnum in canvas_page_nums.items():
                if pnum == page_num:
                    canvas_uri = uri
                    break

            if not canvas_uri:
                return JsonResponse({"error": "Page not found"}, status=404)

            annos = grouped[canvas_uri]

            annotation_data = [self._build_annotation_payload(a) for a in annos]

            # Use v2 serializer
            items = IIIFAnnotationSerializerV2.batch_to_representation(annotation_data)

            layer_id = f"{self.base_url}/v2/annotation-collection/{resource_id}"
            list_id = f"{layer_id}/page-{page_num}"

            annotation_list: dict = {
                "@context": "http://iiif.io/api/presentation/2/context.json",
                "@id": list_id,
                "@type": "sc:AnnotationList",
                "label": f"Analyses page {page_num}",
                "resources": items,
                "within": {
                    "@id": layer_id,
                    "@type": "sc:Layer",
                    "label": f"Analyses pour {self._get_display_name(resource)}",
                },
            }

            return cached_json_response(cache_key, annotation_list, self.CACHE_TIMEOUT)

        except ResourceInstance.DoesNotExist:
            return JsonResponse({"error": "Resource not found"}, status=404)
        except Exception as e:  # pragma: no cover
            logger.error(f"Error generating v2 IIIF page: {e}")
            return JsonResponse({"error": str(e)}, status=500)


class IIIFAnnotationViewV2(IIIFAnnotationMixin, View):
    """
    Returns a single IIIF v2 Annotation for a given 'Analysis' resource.

    URL: /iiif/v2/annotation/<uuid:resource_id>
    """

    def get(self, request, resource_id):
        cache_key = f"iiif_v2_annotation_{resource_id}"
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        try:
            analysis = Resource.objects.get(resourceinstanceid=resource_id)
            if str(analysis.graph_id) != self.ANALYSIS_GRAPH_ID:
                return JsonResponse(
                    {"error": "Resource is not an Analysis"}, status=400
                )

            annos = self._get_annotations_from_analyses([analysis])
            if not annos:
                return JsonResponse({"error": "No annotation data"}, status=404)

            anno = annos[0]  # 1 analysis -> 1 annotation
            payload = self._build_annotation_payload(anno, resource_id=str(resource_id))

            # Use v2 serializer
            iiif_annotation = IIIFAnnotationSerializerV2.to_representation(**payload)

            return cached_json_response(cache_key, iiif_annotation, self.CACHE_TIMEOUT)

        except Resource.DoesNotExist:
            return JsonResponse({"error": "Annotation not found"}, status=404)
        except Exception as e:  # pragma: no cover
            logger.error(f"Error generating v2 annotation: {e}")
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


def _delete_page_patterns(resource_id, version: str = "v3"):
    """
    Delete all page caches for a given resource_id and version.
    """
    list_key = f"iiif_{version}_page_list_{resource_id}"
    page_nums = cache.get(list_key)

    if not page_nums:
        return

    # Delete each page individually
    for num in page_nums:
        cache.delete(f"iiif_{version}_page_{resource_id}_{num}")
        cache.delete(f"iiif_{version}_page_{resource_id}_{num}__etag")

    # Delete the index list itself
    cache.delete(list_key)


def _invalidate_for_analysis_id(analysis_uuid):
    """
    Invalidate:
      - the single annotation cache for this analysis (v2 and v3)
      - any collections/pages that include this analysis via Component and/or Document.
    """
    _delete_cache_keys(
        [
            f"iiif_v3_annotation_{analysis_uuid}",
            f"iiif_v2_annotation_{analysis_uuid}",
        ]
    )

    DOCUMENT_GRAPH = IIIFAnnotationMixin.DOCUMENT_GRAPH_ID
    COMPONENT_GRAPH = IIIFAnnotationMixin.COMPONENT_GRAPH_ID

    rels = ResourceXResource.objects.filter(from_resource_id=analysis_uuid)

    doc_ids: set = set()
    component_ids: set = set()

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
        _delete_cache_keys(
            [
                f"iiif_v3_collection_{doc_id}",
                f"iiif_v2_collection_{doc_id}",
            ]
        )
        _delete_page_patterns(doc_id, "v3")
        _delete_page_patterns(doc_id, "v2")


@receiver([post_save, post_delete], sender=VwAnnotation)
def invalidate_on_vwannotation_change(sender, instance: VwAnnotation, **kwargs):
    """
    Any change to a VwAnnotation affects the corresponding Analysis and
    thus any Collections/Pages that include it.
    """
    try:
        analysis_uuid = instance.resourceinstance_id
        _invalidate_for_analysis_id(analysis_uuid)
    except Exception as e:  # pragma: no cover
        logger.error(f"Cache invalidation (VwAnnotation) failed: {e}")


@receiver([post_save, post_delete], sender=ResourceXResource)
def invalidate_on_relation_change(sender, instance: ResourceXResource, **kwargs):
    """
    If a relation is created/removed involving an Analysis -> Component/Document,
    we must invalidate Collections/Pages that depend on this linkage.
    """
    try:
        ANALYSIS_GRAPH = IIIFAnnotationMixin.ANALYSIS_GRAPH_ID
        DOCUMENT_GRAPH = IIIFAnnotationMixin.DOCUMENT_GRAPH_ID
        COMPONENT_GRAPH = IIIFAnnotationMixin.COMPONENT_GRAPH_ID

        is_analysis_from = str(instance.from_resource_graph_id) == ANALYSIS_GRAPH
        is_analysis_to = str(instance.to_resource_graph_id) == ANALYSIS_GRAPH

        if is_analysis_from:
            _invalidate_for_analysis_id(instance.from_resource_id)

        elif is_analysis_to:
            _invalidate_for_analysis_id(instance.to_resource_id)

        else:
            to_gid = (
                str(instance.to_resource_graph_id)
                if instance.to_resource_graph_id
                else None
            )
            from_gid = (
                str(instance.from_resource_graph_id)
                if instance.from_resource_graph_id
                else None
            )

            if from_gid == COMPONENT_GRAPH and to_gid == DOCUMENT_GRAPH:
                doc_id = instance.to_resource_id
                _delete_cache_keys(
                    [
                        f"iiif_v3_collection_{doc_id}",
                        f"iiif_v2_collection_{doc_id}",
                    ]
                )
                _delete_page_patterns(doc_id, "v3")
                _delete_page_patterns(doc_id, "v2")

    except Exception as e:  # pragma: no cover
        logger.error(f"Cache invalidation (ResourceXResource) failed: {e}")
