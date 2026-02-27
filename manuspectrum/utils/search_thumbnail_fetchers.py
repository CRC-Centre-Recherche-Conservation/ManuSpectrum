import logging
import requests

from arches.app.utils.search_thumbnail_fetcher import SearchThumbnailFetcher
from arches.app.utils.search_thumbnail_fetcher_factory import (
    SearchThumbnailFetcherFactory,
)
from manuspectrum.utils.iiif_tools import CanvasIIIF, BBoxCalculator

logger = logging.getLogger(__name__)


@SearchThumbnailFetcherFactory.register("72ac748a-7368-41e7-9f54-99be41319fac")
class ManifestThumbnailFetcher(SearchThumbnailFetcher):
    """
    Fetcher for resources with a 'manifest' type node (IIIF v2/v3).
    Retrieves thumbnails from IIIF manifests.
    """

    def get_thumbnail(self, retrieve=False):
        # Late import to avoid AppRegistryNotReady
        from arches.app.models.models import TileModel

        if not retrieve:
            return self._check_thumbnail_exists()

        try:
            tiles = TileModel.objects.filter(
                resourceinstance=self.resource, nodegroup__node__datatype="manifest"
            )

            manifest_url = None
            for tile in tiles:
                for _, value in tile.data.items():
                    if value and isinstance(value, str) and "manifest" in value.lower():
                        manifest_url = value
                        break
                if manifest_url:
                    break

            if not manifest_url:
                logger.warning(
                    f"No manifest found for resource {self.resource.resourceinstanceid}"
                )
                return None

            manifest_data = CanvasIIIF.fetch_manifest(manifest_url)
            if not manifest_data:
                return None

            thumbnail_url = CanvasIIIF.get_thumbnail_url(manifest_data)
            if not thumbnail_url:
                logger.warning(
                    f"No thumbnail URL found in manifest for resource {self.resource.resourceinstanceid}"
                )
                return None

            resp = requests.get(thumbnail_url, timeout=10)
            if resp.status_code != 200:
                return None

            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return (resp.content, content_type)

        except Exception as e:
            logger.error(
                f"Error fetching manifest thumbnail for resource {self.resource.resourceinstanceid}: {e}"
            )
            return None

    def _check_thumbnail_exists(self):
        try:
            from arches.app.models.models import TileModel

            return TileModel.objects.filter(
                resourceinstance=self.resource, nodegroup__node__datatype="manifest"
            ).exists()
        except Exception as e:
            logger.error(f"Error checking thumbnail existence: {e}")
            return False


@SearchThumbnailFetcherFactory.register("d47595b4-f8a6-419c-8f33-b388206280c4")
class ComponentThumbnailFetcher(SearchThumbnailFetcher):
    """
    Fetcher for resources with IIIF annotations of type Polygon only.
    Generates a thumbnail of the annotated region using the IIIF Image API.
    """

    def get_thumbnail(self, retrieve=False):
        from arches.app.models.models import VwAnnotation

        if not retrieve:
            try:
                return VwAnnotation.objects.filter(
                    resourceinstance=self.resource
                ).exists()
            except Exception as e:
                logger.error(f"Error checking annotation existence: {e}")
                return False

        try:
            annotation = VwAnnotation.objects.filter(
                resourceinstance=self.resource
            ).first()
            if not annotation:
                logger.info(
                    f"No annotations found for resource {self.resource.resourceinstanceid}"
                )
                return None

            feature = annotation.feature or {}
            canvas_service_url = annotation.canvas
            manifest_url = feature.get("properties", {}).get("manifest")

            if not canvas_service_url or not manifest_url:
                logger.info(
                    f"Missing canvas service or manifest for {self.resource.resourceinstanceid}"
                )
                return None

            manifest_data = CanvasIIIF.fetch_manifest(manifest_url)
            if not manifest_data:
                return None

            canvas_info = ComponentThumbnailFetcher._find_canvas_by_service(
                manifest_data, canvas_service_url
            )
            width, height = CanvasIIIF.get_canvas_dimensions(canvas_info)

            geometry = feature.get("geometry", {})
            if geometry.get("type") != "Polygon":
                logger.info(
                    f"Skipping non-polygon annotation for {self.resource.resourceinstanceid}"
                )
                return None

            coords = geometry.get("coordinates", [])
            bbox = BBoxCalculator.polygon_bbox(coords, width, height)
            if not bbox:
                return None
            x, y, w, h = bbox

            # IIIF Image API request (region -> full size -> rotation 0 -> default.jpg)
            thumb_url = f"{canvas_service_url}/{x},{y},{w},{h}/full/0/default.jpg"

            resp = requests.get(thumb_url, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch thumbnail from {thumb_url}")
                return None

            return (resp.content, "image/jpeg")

        except Exception as e:
            logger.error(
                f"Error fetching annotation thumbnail for resource {self.resource.resourceinstanceid}: {e}"
            )
            return None

    @staticmethod
    def _find_canvas_by_service(manifest_data, service_url):
        """Find canvas whose first image service matches service_url (v2/v3)."""
        if not manifest_data or not service_url:
            return None
        version = CanvasIIIF.detect_version(manifest_data)

        try:
            if version == 3:
                for canvas in manifest_data.get("items", []):
                    svc = CanvasIIIF._get_service_from_canvas_v3(canvas)
                    if svc == service_url:
                        return canvas
                return None
            else:
                for seq in manifest_data.get("sequences", []):
                    for canvas in seq.get("canvases", []):
                        svc = CanvasIIIF._get_service_from_canvas_v2(canvas)
                        if svc == service_url:
                            return canvas
                return None
        except Exception as e:
            logger.warning(f"Error searching canvas by service: {e}")
            return None


@SearchThumbnailFetcherFactory.register("60c85aba-f079-45bc-997f-21cdd4f77b6d")
class AnalysisThumbnailFetcher(SearchThumbnailFetcher):
    """
    Fetcher for analysis resources with manifest or IIIF annotations.
    Priority:
    1. Manifest thumbnail if manifest tile exists
    2. Annotation-based thumbnail (Point with circle or Polygon region)
    """

    def get_thumbnail(self, retrieve=False):
        from arches.app.models.models import TileModel, VwAnnotation

        if not retrieve:
            try:
                has_manifest = TileModel.objects.filter(
                    resourceinstance=self.resource, nodegroup__node__datatype="manifest"
                ).exists()
                has_annotations = VwAnnotation.objects.filter(
                    resourceinstance=self.resource
                ).exists()
                return has_manifest or has_annotations
            except Exception as e:
                logger.error(f"Error checking thumbnail existence: {e}")
                return False

        try:
            # 1) Try manifest thumbnail
            manifest_tile = TileModel.objects.filter(
                resourceinstance=self.resource, nodegroup__node__datatype="manifest"
            ).first()

            manifest_url = None
            if manifest_tile and manifest_tile.data:
                for _, value in manifest_tile.data.items():
                    if value and isinstance(value, str) and "manifest" in value.lower():
                        manifest_url = value
                        break

            if manifest_url:
                manifest_data = CanvasIIIF.fetch_manifest(manifest_url)
                if manifest_data:
                    thumb_url = CanvasIIIF.get_thumbnail_url(manifest_data)
                    if thumb_url:
                        resp = requests.get(thumb_url, timeout=10)
                        if resp.status_code == 200:
                            return (
                                resp.content,
                                resp.headers.get("Content-Type", "image/jpeg"),
                            )

            # 2) Fallback: annotation-based (Point or Polygon)
            annotation = VwAnnotation.objects.filter(
                resourceinstance=self.resource
            ).first()
            if not annotation:
                logger.info(
                    f"No manifest or annotations found for resource {self.resource.resourceinstanceid}"
                )
                return None

            feature = annotation.feature or {}
            canvas_service_url = annotation.canvas  # base IIIF Image API
            manifest_url = feature.get("properties", {}).get("manifest")

            if not canvas_service_url or not manifest_url:
                logger.info(
                    f"Missing canvas service or manifest for annotation {self.resource.resourceinstanceid}"
                )
                return None

            manifest_data = CanvasIIIF.fetch_manifest(manifest_url)
            if not manifest_data:
                return None

            canvas_info = AnalysisThumbnailFetcher._find_canvas_by_service(
                manifest_data, canvas_service_url
            )
            width, height = CanvasIIIF.get_canvas_dimensions(canvas_info)

            geometry = feature.get("geometry", {})
            geo_type = geometry.get("type")
            coords = geometry.get("coordinates", [])
            if not coords:
                return None

            if geo_type == "Point":
                radius = feature.get("properties", {}).get("radius", 10)
                bbox = BBoxCalculator.point_bbox(coords, width, height, radius=radius)
            elif geo_type == "Polygon":
                bbox = BBoxCalculator.polygon_bbox(coords, width, height)
            else:
                logger.info(
                    f"Unsupported geometry type: {geo_type} for resource {self.resource.resourceinstanceid}"
                )
                return None

            if not bbox:
                return None

            x, y, w, h = bbox
            thumb_url = f"{canvas_service_url}/{x},{y},{w},{h}/full/0/default.jpg"

            resp = requests.get(thumb_url, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch thumbnail from {thumb_url}")
                return None

            return (resp.content, "image/jpeg")

        except Exception as e:
            logger.error(
                f"Error fetching analysis thumbnail for resource {self.resource.resourceinstanceid}: {e}"
            )
            return None

    @staticmethod
    def _find_canvas_by_service(manifest_data, service_url):
        """Find canvas whose first image service matches service_url (v2/v3)."""
        if not manifest_data or not service_url:
            return None
        version = CanvasIIIF.detect_version(manifest_data)

        try:
            if version == 3:
                for canvas in manifest_data.get("items", []):
                    svc = CanvasIIIF._get_service_from_canvas_v3(canvas)
                    if svc == service_url:
                        return canvas
                return None
            else:
                for seq in manifest_data.get("sequences", []):
                    for canvas in seq.get("canvases", []):
                        svc = CanvasIIIF._get_service_from_canvas_v2(canvas)
                        if svc == service_url:
                            return canvas
                return None
        except Exception as e:
            logger.warning(f"Error searching canvas by service: {e}")
            return None
