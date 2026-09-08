"""Unit tests for ``manuspectrum.utils.iiif_tools``.

Locks down the two helpers the IIIF layer leans on:

* ``CanvasIIIF`` — version detection, thumbnail resolution across every shape
  the Presentation spec allows (string / dict / list / derived from the image
  service / absent), canvas lookup by id, by 1-based index and by image
  service URL with scheme- and trailing-slash-insensitive matching.
* ``BBoxCalculator`` — the GeoJSON → IIIF ``xywh`` maths. Canvas y grows
  downwards while latitude grows upwards, so the module negates latitude:
  a canvas point sits at a NEGATIVE latitude, and a positive one lands above
  the canvas and is clamped to 0. Every expected tuple below is hand-computed
  from ``scale = 2 ** zoom``.

No network: the two functions that call out (``fetch_manifest`` and
``get_image_service_dimensions``) are exercised with ``requests.get`` patched.

Usage:
    python manage.py test tests.test_iiif_tools --settings="tests.test_settings"
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from manuspectrum.utils.iiif_tools import BBoxCalculator, CanvasIIIF

V2_CONTEXT = "http://iiif.io/api/presentation/2/context.json"
V3_CONTEXT = "http://iiif.io/api/presentation/3/context.json"

P1_SERVICE = "https://images.example.org/iiif/p1"
P2_SERVICE = "https://images.example.org/iiif/p2"
P3_SERVICE = "https://images.example.org/iiif/p3"


def v2_manifest():
    """Three canvases: p1 has a thumbnail, p2 has none, p3 has a list service."""
    return {
        "@context": V2_CONTEXT,
        "@id": "https://example.org/iiif/book1/manifest",
        "sequences": [
            {
                "canvases": [
                    {
                        "@id": "https://example.org/iiif/book1/canvas/p1",
                        "width": 1200,
                        "height": 1800,
                        "thumbnail": {"@id": f"{P1_SERVICE}/full/90,/0/default.jpg"},
                        "images": [{"resource": {"service": {"@id": P1_SERVICE}}}],
                    },
                    {
                        "@id": "https://example.org/iiif/book1/canvas/p2",
                        "width": 1000,
                        "height": 1500,
                        "images": [{"resource": {"service": {"@id": P2_SERVICE}}}],
                    },
                    {
                        "@id": "https://example.org/iiif/book1/canvas/p3",
                        "images": [{"resource": {"service": [{"@id": P3_SERVICE}]}}],
                    },
                ]
            }
        ],
    }


def v3_manifest():
    """Three canvases: c1 has a thumbnail, c2 a list body, c3 an ImageService2."""
    return {
        "@context": V3_CONTEXT,
        "id": "https://example.org/iiif/book1/v3/manifest",
        "items": [
            {
                "id": "https://example.org/iiif/book1/v3/canvas/1",
                "width": 1200,
                "height": 1800,
                "thumbnail": [
                    {
                        "id": f"{P1_SERVICE}/full/200,/0/default.jpg",
                        "type": "Image",
                    }
                ],
                "items": [
                    {
                        "items": [
                            {
                                "body": {
                                    "id": f"{P1_SERVICE}/full/max/0/default.jpg",
                                    "service": [
                                        {"id": P1_SERVICE, "type": "ImageService3"}
                                    ],
                                }
                            }
                        ]
                    }
                ],
            },
            {
                "id": "https://example.org/iiif/book1/v3/canvas/2",
                "width": 1000,
                "height": 1500,
                "items": [
                    {
                        "items": [
                            {
                                "body": [
                                    {
                                        "id": f"{P2_SERVICE}/full/max/0/default.jpg",
                                        "service": [
                                            {"id": P2_SERVICE, "type": "ImageService3"}
                                        ],
                                    }
                                ]
                            }
                        ]
                    }
                ],
            },
            {
                "id": "https://example.org/iiif/book1/v3/canvas/3",
                "items": [
                    {
                        "items": [
                            {
                                "body": {
                                    "id": f"{P3_SERVICE}/full/max/0/default.jpg",
                                    "service": {
                                        "@id": P3_SERVICE,
                                        "profile": "level2",
                                    },
                                }
                            }
                        ]
                    }
                ],
            },
        ],
    }


class DetectVersionTests(SimpleTestCase):
    def test_v3_context_string(self):
        self.assertEqual(CanvasIIIF.detect_version({"@context": V3_CONTEXT}), 3)

    def test_v2_context_string(self):
        self.assertEqual(CanvasIIIF.detect_version({"@context": V2_CONTEXT}), 2)

    def test_missing_context_falls_back_to_v2(self):
        self.assertEqual(CanvasIIIF.detect_version({"items": []}), 2)

    def test_list_context_is_not_inspected_and_falls_back_to_v2(self):
        """Characterisation, not endorsement: a list ``@context`` is valid v3.

        ``"presentation/3" in ctx`` is a substring test on a string but an
        element-equality test on a list, so this manifest is read as v2 and
        every later lookup goes to ``sequences`` and finds nothing. Flip this
        test when the detection is fixed.
        """
        manifest = {
            "@context": [
                "http://www.w3.org/ns/anno.jsonld",
                V3_CONTEXT,
            ]
        }
        self.assertEqual(CanvasIIIF.detect_version(manifest), 2)


class FetchManifestTests(SimpleTestCase):
    @patch("manuspectrum.utils.iiif_tools.requests.get")
    def test_returns_parsed_json_on_200(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, **{"json.return_value": {"@context": V3_CONTEXT}}
        )

        result = CanvasIIIF.fetch_manifest("https://example.org/manifest")

        self.assertEqual(result, {"@context": V3_CONTEXT})
        mock_get.assert_called_once_with("https://example.org/manifest", timeout=10)

    @patch("manuspectrum.utils.iiif_tools.requests.get")
    def test_returns_none_on_non_200(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)

        self.assertIsNone(CanvasIIIF.fetch_manifest("https://example.org/gone"))

    @patch(
        "manuspectrum.utils.iiif_tools.requests.get",
        side_effect=OSError("connection reset"),
    )
    def test_returns_none_when_request_raises(self, mock_get):
        self.assertIsNone(CanvasIIIF.fetch_manifest("https://example.org/manifest"))


class ThumbnailV3Tests(SimpleTestCase):
    def test_manifest_thumbnail_list_returns_first_id(self):
        manifest = v3_manifest()
        manifest["thumbnail"] = [
            {"id": "https://thumbs.example.org/first.jpg"},
            {"id": "https://thumbs.example.org/second.jpg"},
        ]

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            "https://thumbs.example.org/first.jpg",
        )

    def test_manifest_thumbnail_dict_returns_id(self):
        manifest = v3_manifest()
        manifest["thumbnail"] = {"id": "https://thumbs.example.org/dict.jpg"}

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            "https://thumbs.example.org/dict.jpg",
        )

    def test_manifest_thumbnail_string_returned_as_is(self):
        manifest = v3_manifest()
        manifest["thumbnail"] = "https://thumbs.example.org/plain.jpg"

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            "https://thumbs.example.org/plain.jpg",
        )

    def test_manifest_thumbnail_dict_without_id_returns_none(self):
        manifest = v3_manifest()
        manifest["thumbnail"] = {"type": "Image"}

        self.assertIsNone(CanvasIIIF.get_thumbnail_url(manifest))

    def test_falls_back_to_first_canvas_thumbnail(self):
        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(v3_manifest()),
            f"{P1_SERVICE}/full/200,/0/default.jpg",
        )

    def test_derives_url_from_first_canvas_image_service(self):
        manifest = v3_manifest()
        del manifest["items"][0]["thumbnail"]

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            f"{P1_SERVICE}/full/200,/0/default.jpg",
        )

    def test_derives_url_from_list_shaped_body(self):
        manifest = v3_manifest()
        manifest["items"] = [manifest["items"][1]]

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            f"{P2_SERVICE}/full/200,/0/default.jpg",
        )

    def test_returns_none_without_canvases(self):
        self.assertIsNone(
            CanvasIIIF.get_thumbnail_url({"@context": V3_CONTEXT, "items": []})
        )


class ThumbnailV2Tests(SimpleTestCase):
    def test_manifest_thumbnail_string_returned_as_is(self):
        manifest = v2_manifest()
        manifest["thumbnail"] = "https://thumbs.example.org/plain.jpg"

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            "https://thumbs.example.org/plain.jpg",
        )

    def test_manifest_thumbnail_dict_returns_at_id(self):
        manifest = v2_manifest()
        manifest["thumbnail"] = {"@id": "https://thumbs.example.org/dict.jpg"}

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            "https://thumbs.example.org/dict.jpg",
        )

    def test_manifest_thumbnail_dict_without_at_id_falls_back_to_canvas(self):
        manifest = v2_manifest()
        manifest["thumbnail"] = {"@type": "dctypes:Image"}

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            f"{P1_SERVICE}/full/90,/0/default.jpg",
        )

    def test_falls_back_to_first_canvas_thumbnail(self):
        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(v2_manifest()),
            f"{P1_SERVICE}/full/90,/0/default.jpg",
        )

    def test_canvas_thumbnail_may_be_a_bare_string(self):
        manifest = v2_manifest()
        manifest["sequences"][0]["canvases"][0][
            "thumbnail"
        ] = "https://thumbs.example.org/canvas.jpg"

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            "https://thumbs.example.org/canvas.jpg",
        )

    def test_derives_url_from_first_canvas_image_service(self):
        manifest = v2_manifest()
        del manifest["sequences"][0]["canvases"][0]["thumbnail"]

        self.assertEqual(
            CanvasIIIF.get_thumbnail_url(manifest),
            f"{P1_SERVICE}/full/200,/0/default.jpg",
        )

    def test_returns_none_without_sequences(self):
        self.assertIsNone(CanvasIIIF.get_thumbnail_url({"@context": V2_CONTEXT}))

    def test_returns_none_when_sequence_has_no_canvases(self):
        manifest = {"@context": V2_CONTEXT, "sequences": [{"canvases": []}]}

        self.assertIsNone(CanvasIIIF.get_thumbnail_url(manifest))

    def test_returns_none_for_empty_manifest(self):
        self.assertIsNone(CanvasIIIF.get_thumbnail_url(None))
        self.assertIsNone(CanvasIIIF.get_thumbnail_url({}))


class FindCanvasTests(SimpleTestCase):
    def test_v2_returns_matching_canvas(self):
        canvas = CanvasIIIF.find_canvas(
            v2_manifest(), "https://example.org/iiif/book1/canvas/p2"
        )

        self.assertEqual(canvas["width"], 1000)

    def test_v2_searches_every_sequence(self):
        manifest = v2_manifest()
        manifest["sequences"].append(
            {"canvases": [{"@id": "https://example.org/iiif/book1/canvas/p9"}]}
        )

        canvas = CanvasIIIF.find_canvas(
            manifest, "https://example.org/iiif/book1/canvas/p9"
        )

        self.assertEqual(canvas, {"@id": "https://example.org/iiif/book1/canvas/p9"})

    def test_v3_returns_matching_canvas(self):
        canvas = CanvasIIIF.find_canvas(
            v3_manifest(), "https://example.org/iiif/book1/v3/canvas/2"
        )

        self.assertEqual(canvas["height"], 1500)

    def test_returns_none_for_unknown_canvas(self):
        self.assertIsNone(CanvasIIIF.find_canvas(v2_manifest(), "https://nope"))
        self.assertIsNone(CanvasIIIF.find_canvas(v3_manifest(), "https://nope"))

    def test_lookup_is_exact_and_ignores_normalisation(self):
        self.assertIsNone(
            CanvasIIIF.find_canvas(
                v2_manifest(), "https://example.org/iiif/book1/canvas/p1/"
            )
        )

    def test_returns_none_for_empty_manifest(self):
        self.assertIsNone(CanvasIIIF.find_canvas(None, "https://example.org"))


class NormalizeUriTests(SimpleTestCase):
    def test_strips_scheme_and_trailing_slashes(self):
        self.assertEqual(
            CanvasIIIF._normalize_uri("https://example.org/iiif/p1//"),
            "example.org/iiif/p1",
        )
        self.assertEqual(
            CanvasIIIF._normalize_uri("http://example.org/iiif/p1"),
            "example.org/iiif/p1",
        )

    def test_leaves_schemeless_uri_untouched(self):
        self.assertEqual(
            CanvasIIIF._normalize_uri("example.org/iiif/p1"), "example.org/iiif/p1"
        )

    def test_empty_uri_normalises_to_empty_string(self):
        self.assertEqual(CanvasIIIF._normalize_uri(""), "")
        self.assertEqual(CanvasIIIF._normalize_uri(None), "")


class CanvasIndexTests(SimpleTestCase):
    def test_v2_matches_canvas_id_and_is_one_based(self):
        self.assertEqual(
            CanvasIIIF.get_canvas_index(
                v2_manifest(), "https://example.org/iiif/book1/canvas/p1"
            ),
            1,
        )
        self.assertEqual(
            CanvasIIIF.get_canvas_index(
                v2_manifest(), "https://example.org/iiif/book1/canvas/p2"
            ),
            2,
        )

    def test_v2_matches_across_scheme_and_trailing_slash(self):
        self.assertEqual(
            CanvasIIIF.get_canvas_index(
                v2_manifest(), "http://example.org/iiif/book1/canvas/p2/"
            ),
            2,
        )

    def test_v2_matches_by_image_service_url(self):
        self.assertEqual(CanvasIIIF.get_canvas_index(v2_manifest(), P2_SERVICE), 2)

    def test_v2_matches_by_list_shaped_image_service(self):
        self.assertEqual(
            CanvasIIIF.get_canvas_index(v2_manifest(), f"{P3_SERVICE}/"), 3
        )

    def test_v3_matches_canvas_id_and_is_one_based(self):
        self.assertEqual(
            CanvasIIIF.get_canvas_index(
                v3_manifest(), "https://example.org/iiif/book1/v3/canvas/2"
            ),
            2,
        )

    def test_v3_matches_across_scheme_and_trailing_slash(self):
        self.assertEqual(
            CanvasIIIF.get_canvas_index(
                v3_manifest(), "http://example.org/iiif/book1/v3/canvas/1/"
            ),
            1,
        )

    def test_v3_matches_by_image_service_url(self):
        self.assertEqual(CanvasIIIF.get_canvas_index(v3_manifest(), P2_SERVICE), 2)

    def test_v3_matches_an_image_service_declared_with_at_id(self):
        self.assertEqual(CanvasIIIF.get_canvas_index(v3_manifest(), P3_SERVICE), 3)

    def test_v3_skips_canvases_without_an_annotation_body(self):
        manifest = v3_manifest()
        manifest["items"].insert(0, {"id": "https://example.org/no-page", "items": []})
        manifest["items"].insert(
            1, {"id": "https://example.org/empty-page", "items": [{"items": []}]}
        )

        self.assertEqual(CanvasIIIF.get_canvas_index(manifest, P2_SERVICE), 4)

    def test_returns_none_for_unknown_uri(self):
        self.assertIsNone(CanvasIIIF.get_canvas_index(v2_manifest(), "https://nope"))
        self.assertIsNone(CanvasIIIF.get_canvas_index(v3_manifest(), "https://nope"))

    def test_returns_none_without_manifest_or_url(self):
        self.assertIsNone(CanvasIIIF.get_canvas_index(None, P1_SERVICE))
        self.assertIsNone(CanvasIIIF.get_canvas_index(v2_manifest(), None))
        self.assertIsNone(CanvasIIIF.get_canvas_index(v2_manifest(), ""))

    def test_returns_none_when_v2_manifest_has_no_sequences(self):
        self.assertIsNone(
            CanvasIIIF.get_canvas_index({"@context": V2_CONTEXT}, P1_SERVICE)
        )


class CanvasByIndexTests(SimpleTestCase):
    def test_v2_returns_canvas_and_at_id(self):
        canvas, url = CanvasIIIF.get_canvas_by_index(v2_manifest(), 2)

        self.assertEqual(url, "https://example.org/iiif/book1/canvas/p2")
        self.assertEqual(canvas["width"], 1000)

    def test_v3_returns_canvas_and_id(self):
        canvas, url = CanvasIIIF.get_canvas_by_index(v3_manifest(), 1)

        self.assertEqual(url, "https://example.org/iiif/book1/v3/canvas/1")
        self.assertEqual(canvas["height"], 1800)

    def test_index_below_one_returns_none_pair(self):
        self.assertEqual(CanvasIIIF.get_canvas_by_index(v3_manifest(), 0), (None, None))

    def test_index_past_the_end_returns_none_pair(self):
        self.assertEqual(CanvasIIIF.get_canvas_by_index(v2_manifest(), 4), (None, None))
        self.assertEqual(CanvasIIIF.get_canvas_by_index(v3_manifest(), 4), (None, None))

    def test_returns_none_pair_without_manifest(self):
        self.assertEqual(CanvasIIIF.get_canvas_by_index(None, 1), (None, None))

    def test_returns_none_pair_when_v2_manifest_has_no_sequences(self):
        self.assertEqual(
            CanvasIIIF.get_canvas_by_index({"@context": V2_CONTEXT}, 1), (None, None)
        )


class CanvasDimensionsTests(SimpleTestCase):
    def test_returns_declared_width_and_height(self):
        canvas, _ = CanvasIIIF.get_canvas_by_index(v2_manifest(), 1)

        self.assertEqual(CanvasIIIF.get_canvas_dimensions(canvas), (1200, 1800))

    def test_missing_canvas_falls_back_to_1000_square(self):
        self.assertEqual(CanvasIIIF.get_canvas_dimensions(None), (1000, 1000))
        self.assertEqual(CanvasIIIF.get_canvas_dimensions({}), (1000, 1000))

    def test_each_missing_dimension_falls_back_independently(self):
        self.assertEqual(CanvasIIIF.get_canvas_dimensions({"width": 640}), (640, 1000))
        self.assertEqual(CanvasIIIF.get_canvas_dimensions({"height": 480}), (1000, 480))


class ImageServiceDimensionsTests(SimpleTestCase):
    @patch("manuspectrum.utils.iiif_tools.requests.get")
    def test_reads_width_and_height_from_info_json(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, **{"json.return_value": {"width": 4096, "height": 2731}}
        )

        result = CanvasIIIF.get_image_service_dimensions(P1_SERVICE)

        self.assertEqual(result, (4096, 2731))
        mock_get.assert_called_once_with(f"{P1_SERVICE}/info.json", timeout=10)

    @patch("manuspectrum.utils.iiif_tools.requests.get")
    def test_incomplete_payload_falls_back_to_defaults(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, **{"json.return_value": {"width": 4096}}
        )

        self.assertEqual(
            CanvasIIIF.get_image_service_dimensions(P1_SERVICE), (1000, 1000)
        )

    @patch("manuspectrum.utils.iiif_tools.requests.get")
    def test_non_200_falls_back_to_defaults(self, mock_get):
        mock_get.return_value = MagicMock(status_code=503)

        self.assertEqual(
            CanvasIIIF.get_image_service_dimensions(P1_SERVICE), (1000, 1000)
        )

    @patch(
        "manuspectrum.utils.iiif_tools.requests.get",
        side_effect=OSError("connection reset"),
    )
    def test_request_failure_falls_back_to_defaults(self, mock_get):
        self.assertEqual(
            CanvasIIIF.get_image_service_dimensions(P1_SERVICE), (1000, 1000)
        )


# Ring spanning lng 2→6, lat -1→-5. At zoom 5 (scale 32) that is
# x 64→192, y 32→160 on the canvas.
RING = [[(2.0, -1.0), (6.0, -1.0), (6.0, -5.0), (2.0, -5.0)]]


class PolygonBboxTests(SimpleTestCase):
    def test_default_margin_pads_ten_pixels_on_each_side(self):
        self.assertEqual(
            BBoxCalculator.polygon_bbox(RING, 1000, 1000), (54, 22, 148, 148)
        )

    def test_zero_margin_fits_the_ring_exactly(self):
        self.assertEqual(
            BBoxCalculator.polygon_bbox(RING, 1000, 1000, margin=0), (64, 32, 128, 128)
        )

    def test_zoom_scales_by_powers_of_two(self):
        self.assertEqual(
            BBoxCalculator.polygon_bbox(RING, 1000, 1000, zoom=6, margin=0),
            (128, 64, 256, 256),
        )

    def test_width_and_height_are_clamped_to_the_canvas(self):
        self.assertEqual(
            BBoxCalculator.polygon_bbox(RING, 100, 100, margin=0), (64, 32, 36, 68)
        )

    def test_margined_box_is_clamped_to_the_canvas(self):
        self.assertEqual(
            BBoxCalculator.polygon_bbox(RING, 100, 100, margin=10), (54, 22, 46, 78)
        )

    def test_latitude_is_inverted_so_a_positive_ring_clamps_to_the_top(self):
        above = [[(2.0, 1.0), (6.0, 1.0), (6.0, 5.0), (2.0, 5.0)]]

        self.assertEqual(
            BBoxCalculator.polygon_bbox(above, 1000, 1000, margin=0), (64, 0, 128, 128)
        )

    def test_degenerate_ring_keeps_a_one_pixel_box(self):
        point_ring = [[(2.0, -1.0), (2.0, -1.0), (2.0, -1.0)]]

        self.assertEqual(
            BBoxCalculator.polygon_bbox(point_ring, 1000, 1000, margin=0),
            (64, 32, 1, 1),
        )

    def test_empty_geometry_returns_none(self):
        self.assertIsNone(BBoxCalculator.polygon_bbox([], 1000, 1000))
        self.assertIsNone(BBoxCalculator.polygon_bbox([[]], 1000, 1000))
        self.assertIsNone(BBoxCalculator.polygon_bbox(None, 1000, 1000))

    def test_malformed_coordinates_return_none(self):
        self.assertIsNone(BBoxCalculator.polygon_bbox([[(1.0,)]], 1000, 1000))


class PointBboxTests(SimpleTestCase):
    def test_default_radius_spans_the_context_multiplier(self):
        self.assertEqual(
            BBoxCalculator.point_bbox([4.0, -4.0], 1000, 1000), (78, 78, 100, 100)
        )

    def test_context_multiplier_sets_the_view_radius(self):
        self.assertEqual(
            BBoxCalculator.point_bbox([4.0, -4.0], 1000, 1000, context_multiplier=2),
            (108, 108, 40, 40),
        )

    def test_zero_radius_returns_a_single_pixel(self):
        self.assertEqual(
            BBoxCalculator.point_bbox([1.0, -2.0], 1000, 1000, radius=0), (32, 64, 1, 1)
        )

    def test_latitude_is_inverted_so_a_positive_point_clamps_to_the_top(self):
        self.assertEqual(
            BBoxCalculator.point_bbox([1.0, 2.0], 1000, 1000, radius=0), (32, 0, 1, 1)
        )

    def test_single_pixel_is_clamped_inside_the_canvas(self):
        self.assertEqual(
            BBoxCalculator.point_bbox([100.0, -100.0], 1000, 800, radius=0),
            (999, 799, 1, 1),
        )

    def test_contextual_box_is_clamped_to_the_canvas(self):
        self.assertEqual(
            BBoxCalculator.point_bbox([4.0, -4.0], 150, 120), (78, 78, 72, 42)
        )

    def test_incomplete_coordinates_return_none(self):
        self.assertIsNone(BBoxCalculator.point_bbox([1.0], 1000, 1000))
        self.assertIsNone(BBoxCalculator.point_bbox([], 1000, 1000))
        self.assertIsNone(BBoxCalculator.point_bbox(None, 1000, 1000))

    def test_non_numeric_coordinates_return_none(self):
        self.assertIsNone(BBoxCalculator.point_bbox(["a", "b"], 1000, 1000))


class GeometryToXywhTests(SimpleTestCase):
    def test_polygon_renders_an_exact_fragment(self):
        geometry = {"type": "Polygon", "coordinates": RING}

        self.assertEqual(
            BBoxCalculator.geometry_to_xywh(geometry, 1000, 1000, margin=0),
            "xywh=64,32,128,128",
        )

    def test_polygon_honours_the_default_margin(self):
        geometry = {"type": "Polygon", "coordinates": RING}

        self.assertEqual(
            BBoxCalculator.geometry_to_xywh(geometry, 1000, 1000),
            "xywh=54,22,148,148",
        )

    def test_point_renders_a_single_pixel_fragment(self):
        geometry = {"type": "Point", "coordinates": [1.0, -2.0]}

        self.assertEqual(
            BBoxCalculator.geometry_to_xywh(geometry, 1000, 1000, radius=0),
            "xywh=32,64,1,1",
        )

    def test_linestring_is_boxed_like_a_polygon_ring(self):
        geometry = {"type": "LineString", "coordinates": [(2.0, -1.0), (6.0, -5.0)]}

        self.assertEqual(
            BBoxCalculator.geometry_to_xywh(geometry, 1000, 1000, margin=0),
            "xywh=64,32,128,128",
        )

    def test_unsupported_geometry_type_returns_none(self):
        geometry = {"type": "MultiPolygon", "coordinates": RING}

        self.assertIsNone(BBoxCalculator.geometry_to_xywh(geometry, 1000, 1000))

    def test_missing_geometry_or_coordinates_returns_none(self):
        self.assertIsNone(BBoxCalculator.geometry_to_xywh(None, 1000, 1000))
        self.assertIsNone(BBoxCalculator.geometry_to_xywh({}, 1000, 1000))
        self.assertIsNone(
            BBoxCalculator.geometry_to_xywh({"type": "Point"}, 1000, 1000)
        )
        self.assertIsNone(
            BBoxCalculator.geometry_to_xywh(
                {"type": "Polygon", "coordinates": []}, 1000, 1000
            )
        )

    def test_uncomputable_bbox_returns_none(self):
        geometry = {"type": "Point", "coordinates": [1.0]}

        self.assertIsNone(BBoxCalculator.geometry_to_xywh(geometry, 1000, 1000))
