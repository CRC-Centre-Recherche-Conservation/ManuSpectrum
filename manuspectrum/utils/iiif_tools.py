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

    @staticmethod
    def get_image_service_dimensions(image_service_url):
        try:
            info_url = f"{image_service_url}/info.json"
            response = requests.get(info_url, timeout=10)

            if response.status_code == 200:
                info_data = response.json()
                width = info_data.get('width')
                height = info_data.get('height')

                if width and height:
                    logger.info(f"Retrieved dimensions from Image Service: {width}x{height}")
                    return (width, height)

        except Exception as e:
            logger.warning(f"Failed to fetch dimensions from {image_service_url}: {e}")

        logger.warning(f"Using default dimensions for {image_service_url}")
        return (1000, 1000)


# -------------------
# BBox Calculator
# -------------------
class BBoxCalculator:
    """Helper for calculating bounding boxes in IIIF coordinate system."""

    @staticmethod
    def polygon_bbox(coordinates, canvas_width, canvas_height, zoom=5, margin=10):
        """
        Compute the bounding box (bbox) of a polygon on a canvas.

        The behavior automatically adapts depending on the margin value:
          - If `margin > 0`: returns a visual bbox slightly larger than the polygon,
            useful for display, previews, or zooming.
          - If `margin == 0`: returns an exact bbox that tightly fits the polygon,
            useful for IIIF annotations or precise geometric data.

        Args:
            coordinates (list): A list of polygon coordinates in the form
                [[(lng, lat), (lng, lat), ...]].
            canvas_width (int): Width of the canvas (in pixels).
            canvas_height (int): Height of the canvas (in pixels).
            zoom (int, optional): Zoom level (scaling factor = 2 ** zoom). Defaults to 5.
            margin (int, optional): Margin around the polygon (in pixels).
                Set to 0 for exact bounding boxes. Defaults to 10.

        Returns:
            tuple[int, int, int, int] | None:
                (x, y, w, h) representing the top-left corner and dimensions
                of the bounding box in canvas coordinates.
                Returns None if coordinates are invalid or an error occurs.

        Notes:
            - The function ensures that the bbox stays within canvas bounds.
            - When `margin == 0`, bbox dimensions are guaranteed to be at least 1 pixel.
            - Latitude values are inverted for screen coordinate systems.

        Example:
            >>> coords = [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]]
            >>> polygon_bbox(coords, 1024, 1024, zoom=5, margin=10)
            (22, 22, 64, 64)
            >>> polygon_bbox(coords, 1024, 1024, zoom=5, margin=0)
            (32, 32, 44, 44)
        """
        if not coordinates or not coordinates[0]:
            return None

        try:
            ring = coordinates[0]
            scale = 2 ** zoom
            xs = [lng * scale for lng, lat in ring]
            ys = [-lat * scale for lng, lat in ring]

            xmin, ymin, xmax, ymax = min(xs), min(ys), max(xs), max(ys)

            # --- Exact bbox (no margin) ---
            if margin == 0:
                x = max(0, int(xmin))
                y = max(0, int(ymin))
                w = max(1, int(xmax - xmin))
                h = max(1, int(ymax - ymin))
                w = min(w, canvas_width - x)
                h = min(h, canvas_height - y)

            # --- Visual bbox (with margin) ---
            else:
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
        """
        Compute the bounding box (bbox) of a point on a canvas.

        The behavior automatically adapts depending on the `radius` value:
          - If `radius > 0`: returns a visual bbox around the point with a given radius,
            useful for display, zoom, or contextual visualization.
          - If `radius == 0`: returns an exact 1x1 pixel bbox,
            useful for IIIF annotations or precise coordinate mapping.

        Args:
            coordinates (list | tuple): Point coordinates as [lng, lat].
            canvas_width (int): Width of the canvas (in pixels).
            canvas_height (int): Height of the canvas (in pixels).
            radius (int, optional): Radius around the point in pixels.
                Set to 0 for an exact 1x1 pixel bbox. Defaults to 10.
            zoom (int, optional): Zoom level (scaling factor = 2 ** zoom). Defaults to 5.
            context_multiplier (int, optional): Factor to expand the view radius
                for contextual visualization. Defaults to 5.

        Returns:
            tuple[int, int, int, int] | None:
                (x, y, w, h) representing the top-left corner and dimensions
                of the bounding box in canvas coordinates.
                Returns None if coordinates are invalid or an error occurs.

        Notes:
            - The function ensures that the bbox stays within canvas bounds.
            - When `radius == 0`, the result is always (x, y, 1, 1).
            - Latitude values are inverted for screen coordinate systems.

        Example:
            >>> point_bbox([1.5, 2.0], 1024, 1024, radius=10, zoom=5)
            (46, 28, 100, 100)
            >>> point_bbox([1.5, 2.0], 1024, 1024, radius=0, zoom=5)
            (48, 32, 1, 1)
        """
        if not coordinates or len(coordinates) < 2:
            return None

        try:
            lng, lat = coordinates[0], coordinates[1]
            scale = 2 ** zoom
            x_center = lng * scale
            y_center = -lat * scale

            # --- Exact point (1x1 pixel) ---
            if radius == 0:
                x = max(0, int(x_center))
                y = max(0, int(y_center))
                x = min(x, canvas_width - 1)
                y = min(y, canvas_height - 1)
                return x, y, 1, 1

            # --- Contextual bbox (with visual radius) ---
            view_radius = radius * context_multiplier
            x = max(0, int(x_center - view_radius))
            y = max(0, int(y_center - view_radius))
            w = min(int(2 * view_radius), canvas_width - x)
            h = min(int(2 * view_radius), canvas_height - y)

            return x, y, w, h

        except Exception as e:
            logger.error(f"Error calculating point bbox: {e}")
            return None

    @staticmethod
    def geometry_to_xywh(geometry, canvas_width, canvas_height, zoom=5, margin=10, radius=10):
        """
        Convert a GeoJSON geometry object to an IIIF xywh fragment.

        The behavior automatically adapts depending on the given margin or radius:
          - If `margin > 0` (for polygons or lines), a visual bbox with margin is computed.
          - If `margin == 0`, an exact bbox is computed (tight fit, for IIIF or precise data).
          - If `radius > 0` (for points), a visual bbox is computed around the point.
          - If `radius == 0`, an exact 1x1 pixel bbox is returned.

        Args:
            geometry (dict): GeoJSON geometry object.
            canvas_width (int): Width of the canvas (in pixels).
            canvas_height (int): Height of the canvas (in pixels).
            zoom (int, optional): Zoom level (scaling factor = 2 ** zoom). Defaults to 5.
            margin (int, optional): Margin around polygons/lines (0 = exact). Defaults to 10.
            radius (int, optional): Radius around points (0 = exact). Defaults to 10.

        Returns:
            str | None:
                IIIF fragment string in the form "xywh=x,y,w,h", or None if the geometry is invalid.

        Example:
            >>> geom = {"type": "Polygon", "coordinates": [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]]}
            >>> geometry_to_xywh(geom, 1024, 1024, margin=0)
            'xywh=32,32,44,44'
            >>> point = {"type": "Point", "coordinates": [1.5, 2.0]}
            >>> geometry_to_xywh(point, 1024, 1024, radius=0)
            'xywh=48,32,1,1'
        """
        if not geometry:
            return None

        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")

        if not coordinates:
            return None

        try:
            # --- Points ---
            if geometry_type == "Point":
                bbox = BBoxCalculator.point_bbox(
                    coordinates,
                    canvas_width,
                    canvas_height,
                    zoom=zoom,
                    radius=radius,
                )

            # --- Polygons ---
            elif geometry_type == "Polygon":
                bbox = BBoxCalculator.polygon_bbox(
                    coordinates,
                    canvas_width,
                    canvas_height,
                    zoom=zoom,
                    margin=margin,
                )

            # --- Lines (treated like polygons for bbox calculation) ---
            elif geometry_type == "LineString":
                poly_coords = [coordinates]
                bbox = BBoxCalculator.polygon_bbox(
                    poly_coords,
                    canvas_width,
                    canvas_height,
                    zoom=zoom,
                    margin=margin,
                )

            else:
                logger.warning(f"Unsupported geometry type: {geometry_type}")
                return None

            if bbox:
                x, y, w, h = bbox
                return f"xywh={x},{y},{w},{h}"

            return None

        except Exception as e:
            logger.error(f"Error converting geometry to xywh: {e}")
            return None

