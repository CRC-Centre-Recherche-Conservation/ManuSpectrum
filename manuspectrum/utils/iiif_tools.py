import requests
import logging

logger = logging.getLogger(__name__)

# -------------------------------
# IIIF Canvas
# -------------------------------
class CanvasIIIF:
    """Helper class for working with IIIF v2/v3 manifests and canvases."""

    @staticmethod
    def fetch_manifest(manifest_url):
        try:
            response = requests.get(manifest_url, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch manifest from {manifest_url}: {e}")
        return None

    @staticmethod
    def detect_version(manifest_data):
        """Detects IIIF version (2 or 3) from context or structure."""
        ctx = manifest_data.get('@context', '')
        if 'presentation/3' in ctx or 'iiif.io/api/presentation/3' in ctx:
            return 3
        return 2

    @staticmethod
    def get_thumbnail_url(manifest_data):
        """Extract thumbnail from manifest or first canvas, IIIF v2/v3 compatible."""
        if not manifest_data:
            return None

        version = CanvasIIIF.detect_version(manifest_data)

        # --- v3 ---
        if version == 3:
            thumb = manifest_data.get('thumbnail')
            if thumb:
                if isinstance(thumb, list):
                    thumb = thumb[0]
                if isinstance(thumb, dict):
                    return thumb.get('id')
                if isinstance(thumb, str):
                    return thumb

            items = manifest_data.get('items', [])
            if items:
                first_canvas = items[0]
                canvas_thumb = first_canvas.get('thumbnail')
                if canvas_thumb:
                    if isinstance(canvas_thumb, list):
                        canvas_thumb = canvas_thumb[0]
                    if isinstance(canvas_thumb, dict):
                        return canvas_thumb.get('id')
                    if isinstance(canvas_thumb, str):
                        return canvas_thumb

                # Try service-derived URL
                image_service = CanvasIIIF._get_service_from_canvas_v3(first_canvas)
                if image_service:
                    return f"{image_service}/full/200,/0/default.jpg"
            return None

        # --- v2 ---
        else:
            thumb = manifest_data.get('thumbnail')
            if isinstance(thumb, str):
                return thumb
            if isinstance(thumb, dict) and '@id' in thumb:
                return thumb['@id']

            sequences = manifest_data.get('sequences', [])
            if sequences:
                canvases = sequences[0].get('canvases', [])
                if canvases:
                    first_canvas = canvases[0]
                    thumb = first_canvas.get('thumbnail')
                    if isinstance(thumb, str):
                        return thumb
                    if isinstance(thumb, dict) and '@id' in thumb:
                        return thumb['@id']

                    # Build from IIIF service
                    service = CanvasIIIF._get_service_from_canvas_v2(first_canvas)
                    if service:
                        return f"{service}/full/200,/0/default.jpg"
            return None

    @staticmethod
    def find_canvas(manifest_data, canvas_url):
        """Finds a canvas info in IIIF v2/v3 manifest."""
        if not manifest_data:
            return None

        version = CanvasIIIF.detect_version(manifest_data)

        if version == 3:
            for canvas in manifest_data.get('items', []):
                if canvas.get('id') == canvas_url:
                    return canvas
            return None
        else:
            for seq in manifest_data.get('sequences', []):
                for canvas in seq.get('canvases', []):
                    if canvas.get('@id') == canvas_url:
                        return canvas
            return None

    @staticmethod
    def get_canvas_dimensions(canvas_info):
        """Returns (width, height) with safe defaults."""
        if not canvas_info:
            return (1000, 1000)
        return (
            canvas_info.get('width', 1000),
            canvas_info.get('height', 1000)
        )

    @staticmethod
    def _get_service_from_canvas_v2(canvas):
        """Extracts IIIF image service from v2 canvas."""
        images = canvas.get('images', [])
        if images:
            res = images[0].get('resource', {})
            service = res.get('service', {})
            return service.get('@id')
        return None

    @staticmethod
    def _get_service_from_canvas_v3(canvas):
        """Extracts IIIF image service from v3 canvas."""
        items = canvas.get('items', [])
        if not items:
            return None
        first_item = items[0]
        inner_items = first_item.get('items', [])
        if not inner_items:
            return None
        body = inner_items[0].get('body', {})
        if isinstance(body, list):
            body = body[0]
        service = body.get('service', [])
        if isinstance(service, list):
            service = service[0]
        if isinstance(service, dict):
            return service.get('id')
        return None


# -------------------
# BBox Calculator
# -------------------
class BBoxCalculator:
    """Helper for calculating bounding boxes in IIIF coordinate system."""

    @staticmethod
    def polygon_bbox(coordinates, canvas_width, canvas_height, zoom=5, margin=10):
        if not coordinates or not coordinates[0]:
            return None
        try:
            ring = coordinates[0]
            scale = 2 ** zoom
            xs = [lng * scale for lng, lat in ring]
            ys = [-lat * scale for lng, lat in ring]

            xmin, ymin, xmax, ymax = min(xs), min(ys), max(xs), max(ys)
            x = max(0, int(xmin - margin))
            y = max(0, int(ymin - margin))
            w = min(int(xmax - xmin + 2 * margin), canvas_width - x)
            h = min(int(ymax - ymin + 2 * margin), canvas_height - y)

            return x, y, w, h
        except Exception as e:
            logger.error(f"Error calculating polygon bbox: {e}")
            return None

    @staticmethod
    def point_bbox(coordinates, canvas_width, canvas_height, radius=10, zoom=5, context_multiplier=5):
        if not coordinates or len(coordinates) < 2:
            return None
        try:
            lng, lat = coordinates[0], coordinates[1]
            scale = 2 ** zoom
            x_center = lng * scale
            y_center = -lat * scale
            view_radius = radius * context_multiplier

            x = max(0, int(x_center - view_radius))
            y = max(0, int(y_center - view_radius))
            w = min(int(2 * view_radius), canvas_width - x)
            h = min(int(2 * view_radius), canvas_height - y)

            return x, y, w, h
        except Exception as e:
            logger.error(f"Error calculating point bbox: {e}")
            return None