"""
Custom SearchThumbnailFetcher implementations for IIIF resources
Place this file in your project and import it in your settings.py
"""
import logging
import requests

from arches.app.utils.search_thumbnail_fetcher import SearchThumbnailFetcher
from arches.app.utils.search_thumbnail_fetcher_factory import SearchThumbnailFetcherFactory

logger = logging.getLogger(__name__)


@SearchThumbnailFetcherFactory.register('72ac748a-7368-41e7-9f54-99be41319fac')
class ManifestThumbnailFetcher(SearchThumbnailFetcher):
    """
    Fetcher for resources with a 'manifest' type node
    Retrieves thumbnails from IIIF manifests
    """

    def get_thumbnail(self, retrieve=False):
        """
        Retrieves the thumbnail from an IIIF manifest

        Args:
            retrieve (bool): If True, downloads and returns binary data

        Returns:
            tuple: (binary_data, mime_type) or None if no thumbnail found
        """
        # Late import to avoid AppRegistryNotReady
        from arches.app.models.models import TileModel

        if not retrieve:
            # HEAD request - only check if thumbnail exists
            return self._check_thumbnail_exists()

        try:
            tiles = TileModel.objects.filter(
                resourceinstance=self.resource,
                nodegroup__node__datatype='manifest'
            )

            manifest_url = None
            for tile in tiles:
                for node_id, value in tile.data.items():
                    if value and isinstance(value, str) and 'manifest' in value.lower():
                        manifest_url = value
                        break
                if manifest_url:
                    break

            if not manifest_url:
                logger.warning(f"No manifest found for resource {self.resource.resourceinstanceid}")
                return None

            # Fetch the manifest
            response = requests.get(manifest_url, timeout=10)
            if response.status_code != 200:
                return None
            manifest_data = response.json()

            thumbnail_url = None

            # Option 1: Thumbnail at manifest level
            if 'thumbnail' in manifest_data:
                thumbnail_data = manifest_data['thumbnail']
                if isinstance(thumbnail_data, dict) and '@id' in thumbnail_data:
                    thumbnail_url = thumbnail_data['@id']
                elif isinstance(thumbnail_data, str):
                    thumbnail_url = thumbnail_data

            # Option 2: Thumbnail from first canvas
            if not thumbnail_url and 'sequences' in manifest_data:
                sequences = manifest_data['sequences']
                if sequences and len(sequences) > 0:
                    canvases = sequences[0].get('canvases', [])
                    if canvases and len(canvases) > 0:
                        first_canvas = canvases[0]
                        if 'thumbnail' in first_canvas:
                            thumb_data = first_canvas['thumbnail']
                            if isinstance(thumb_data, dict) and '@id' in thumb_data:
                                thumbnail_url = thumb_data['@id']
                            elif isinstance(thumb_data, str):
                                thumbnail_url = thumb_data

                        # Build a thumbnail URL from IIIF service
                        if not thumbnail_url and 'images' in first_canvas:
                            images = first_canvas['images']
                            if images and len(images) > 0:
                                resource = images[0].get('resource', {})
                                service = resource.get('service', {})
                                if '@id' in service:
                                    base_url = service['@id']
                                    # Create IIIF thumbnail URL (200px wide)
                                    thumbnail_url = f"{base_url}/full/200,/0/default.jpg"

            if not thumbnail_url:
                logger.warning(f"No thumbnail URL found in manifest for resource {self.resource.resourceinstanceid}")
                return None

            # Download the thumbnail
            thumb_response = requests.get(thumbnail_url, timeout=10)
            if thumb_response.status_code != 200:
                return None

            # Determine MIME type
            content_type = thumb_response.headers.get('Content-Type', 'image/jpeg')

            return (thumb_response.content, content_type)

        except Exception as e:
            logger.error(f"Error fetching manifest thumbnail for resource {self.resource.resourceinstanceid}: {e}")
            return None

    def _check_thumbnail_exists(self):
        """Quickly checks if a thumbnail exists without downloading it"""
        try:
            from arches.app.models.models import TileModel

            tiles = TileModel.objects.filter(
                resourceinstance=self.resource,
                nodegroup__node__datatype='manifest'
            ).exists()
            return tiles
        except Exception as e:
            logger.error(f"Error checking thumbnail existence: {e}")
            return False


@SearchThumbnailFetcherFactory.register('d47595b4-f8a6-419c-8f33-b388206280c4')
class ComponentThumbnailFetcher(SearchThumbnailFetcher):
    """
    Fetcher for resources with IIIF annotations of type Polygon only
    Generates a thumbnail of the annotated region in the canvas
    """

    def get_thumbnail(self, retrieve=False):
        """
        Retrieves a thumbnail of the annotated area (polygons only)

        Args:
            retrieve (bool): If True, generates and returns binary data

        Returns:
            tuple: (binary_data, mime_type) or None
        """
        # Late import to avoid AppRegistryNotReady
        from arches.app.models.models import VwAnnotation

        if not retrieve:
            return self._check_thumbnail_exists()

        try:
            # Find annotations for this resource
            annotations = VwAnnotation.objects.filter(
                resourceinstance=self.resource
            ).first()

            if not annotations:
                logger.info(f"No annotations found for resource {self.resource.resourceinstanceid}")
                return None

            # Extract annotation information
            feature = annotations.feature
            canvas = annotations.canvas

            # Extract manifest from feature properties
            manifest_url = feature.get('properties', {}).get('manifest')

            if not canvas or not manifest_url:
                logger.info(f"Missing canvas or manifest for annotation {self.resource.resourceinstanceid}")
                return None

            # Calculate IIIF region based on geometry
            geometry = feature.get('geometry', {})
            geo_type = geometry.get('type')
            coordinates = geometry.get('coordinates', [])

            # Process ONLY polygons
            if geo_type != 'Polygon':
                logger.info(
                    f"Skipping non-polygon annotation (type: {geo_type}) for resource {self.resource.resourceinstanceid}")
                return None

            if not coordinates:
                return None

            # Retrieve canvas dimensions
            try:
                manifest_response = requests.get(manifest_url, timeout=10)
                manifest_data = manifest_response.json()
                canvas_info = self._find_canvas_in_manifest(manifest_data, canvas)
                if not canvas_info:
                    return None

                canvas_width = canvas_info.get('width', 1000)
                canvas_height = canvas_info.get('height', 1000)
            except Exception as e:
                logger.warning(f"Could not get canvas dimensions: {e}")
                canvas_width = canvas_height = 1000

            # Calculate bounding box for the polygon
            bbox = self._calculate_polygon_bbox(coordinates, canvas_width, canvas_height)

            if not bbox:
                return None

            x, y, w, h = bbox

            # Build IIIF thumbnail URL with region
            # Format: {canvas}/x,y,w,h/200,/0/default.jpg
            thumbnail_url = f"{canvas}/{x},{y},{w},{h}/full/0/default.jpg"

            # Download the region image
            thumb_response = requests.get(thumbnail_url, timeout=10)
            if thumb_response.status_code != 200:
                logger.warning(f"Failed to fetch thumbnail from {thumbnail_url}")
                return None

            # Return the image as-is
            return (thumb_response.content, 'image/jpeg')

        except Exception as e:
            logger.error(f"Error fetching annotation thumbnail for resource {self.resource.resourceinstanceid}: {e}")
            return None

    def _check_thumbnail_exists(self):
        """Checks if annotations exist for this resource"""
        try:
            from arches.app.models.models import VwAnnotation

            return VwAnnotation.objects.filter(resourceinstance=self.resource).exists()
        except Exception as e:
            logger.error(f"Error checking annotation existence: {e}")
            return False

    def _find_canvas_in_manifest(self, manifest_data, canvas_url):
        """Finds canvas information in the manifest"""
        if 'sequences' not in manifest_data:
            return None

        for sequence in manifest_data['sequences']:
            for canvas in sequence.get('canvases', []):
                # Compare service URL
                if 'images' in canvas:
                    for image in canvas['images']:
                        service = image.get('resource', {}).get('service', {})
                        if service.get('@id') == canvas_url:
                            return canvas
        return None

    def _calculate_polygon_bbox(
            self,
            coordinates,
            canvas_width,
            canvas_height,
            zoom=5,
            margin=10
    ):
        """
        Calculates the bounding box (xywh) of a Leaflet polygon (CRS.Simple)
        and converts it to the IIIF image coordinate system.

        Args:
            coordinates (list): GeoJSON coordinates [[[lng, lat], ...]]
            canvas_width (int): IIIF canvas width in pixels
            canvas_height (int): IIIF canvas height in pixels
            zoom (int): Leaflet zoom level (5 in Arches context)
            margin (int): margin in pixels added around the bbox

        Returns:
            tuple (x, y, w, h) or None if invalid
        """
        try:
            if not coordinates or not coordinates[0]:
                return None

            ring = coordinates[0]

            scale = 2 ** zoom
            xs = [lng * scale for lng, lat in ring]
            ys = [-lat * scale for lng, lat in ring]

            xmin, ymin, xmax, ymax = min(xs), min(ys), max(xs), max(ys)
            x = max(0, int(xmin - margin))
            y = max(0, int(ymin - margin))
            w = min(int(xmax - xmin + 2 * margin), canvas_width - x)
            h = min(int(ymax - ymin + 2 * margin), canvas_height - y)

            w = max(1, min(w, canvas_width - x))
            h = max(1, min(h, canvas_height - y))

            return x, y, w, h
        except Exception as e:
            logger.error(f"Error calculating bounding box: {e}")
            return None