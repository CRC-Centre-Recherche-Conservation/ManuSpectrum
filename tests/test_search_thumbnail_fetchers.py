"""What the three search-thumbnail fetchers promise, without a database or a network.

Each fetcher answers two different questions through one method: with
``retrieve=False`` it is an existence probe deciding whether a search result
advertises a thumbnail at all, and with ``retrieve=True`` it returns
``(bytes, content_type)``. These tests lock both answers for each fetcher, every
early ``None``, the exact IIIF Image API region URL built from an annotation
bbox, and ``AnalysisThumbnailFetcher``'s manifest-before-annotation priority.

The Arches ORM is imported inside the methods, so ``TileModel`` and
``VwAnnotation`` are patched on ``arches.app.models.models``; the manifest fetch
and the guarded image fetch (``safe_fetch``) are patched on the fetchers module.
Nothing here reaches Postgres, Elasticsearch or the network.

Image payloads carry a real signature: a fetcher serves what an image server
sent under this site's own origin, so it relays it only once the first bytes
name an image format.
"""

from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from manuspectrum.utils.search_thumbnail_fetchers import (
    AnalysisThumbnailFetcher,
    ComponentThumbnailFetcher,
    ManifestThumbnailFetcher,
)

FETCHERS = "manuspectrum.utils.search_thumbnail_fetchers"
TILE_MODEL = "arches.app.models.models.TileModel"
ANNOTATION_MODEL = "arches.app.models.models.VwAnnotation"
FETCH_MANIFEST = f"{FETCHERS}.CanvasIIIF.fetch_manifest"
SAFE_FETCH = f"{FETCHERS}.safe_fetch"

RESOURCE = SimpleNamespace(resourceinstanceid="0e6d1c02-64d0-4a13-8f2a-2a1c9b3f77ad")
MANIFEST_NODE = "ec2c9d3e-6bcd-4d9b-9d1f-6f9dfb6f0f11"

TILE_MANIFEST_URL = "https://example.org/iiif/2/book1/manifest.json"
ANNOTATION_MANIFEST_URL = "https://example.org/iiif/2/book2/manifest.json"
CANVAS_SERVICE = "https://img.example.org/iiif/2/page1"
DERIVED_THUMBNAIL = f"{CANVAS_SERVICE}/full/200,/0/default.jpg"

IMAGE_HEADERS = {"Accept": "image/*,*/*;q=0.8"}

JPEG = b"\xff\xd8\xff"
PNG = b"\x89PNG\r\n\x1a\n"
JPEG_BYTES = JPEG + b"JPEGDATA"
PNG_BYTES = PNG + b"PNGDATA"
REGION_BYTES = JPEG + b"REGION"
POINT_REGION_BYTES = JPEG + b"POINTREGION"

POLYGON = [[[1.0, -1.0], [2.0, -1.0], [2.0, -2.0], [1.0, -2.0]]]
POLYGON_REGION = "22,22,52,52"
FAR_POLYGON = [[[20.0, -20.0], [40.0, -20.0], [40.0, -40.0], [20.0, -40.0]]]
FAR_POLYGON_DEFAULT_CANVAS_REGION = "630,630,370,370"
POINT = [1.5, -2.0]
POINT_REGION = "0,14,100,100"


def tile(**data):
    return SimpleNamespace(data=data)


def queryset(rows=(), exists=None):
    qs = mock.MagicMock()
    qs.__iter__.side_effect = lambda: iter(rows)
    qs.first.return_value = rows[0] if rows else None
    qs.exists.return_value = bool(rows) if exists is None else exists
    return qs


def response(status=200, content=None, headers=None, url="https://img.example.org/x"):
    return SimpleNamespace(
        status_code=status,
        content=JPEG_BYTES if content is None else content,
        headers=headers or {},
        url=url,
    )


def annotation(
    geometry=None,
    canvas=CANVAS_SERVICE,
    manifest=ANNOTATION_MANIFEST_URL,
    **properties,
):
    properties["manifest"] = manifest
    return SimpleNamespace(
        canvas=canvas,
        feature={
            "geometry": (
                geometry
                if geometry is not None
                else {"type": "Polygon", "coordinates": POLYGON}
            ),
            "properties": {k: v for k, v in properties.items() if v is not None},
        },
    )


def v2_manifest(width=1024, height=1024, service=CANVAS_SERVICE, thumbnail=None):
    manifest = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "sequences": [
            {
                "canvases": [
                    {
                        "@id": "https://example.org/iiif/2/book2/canvas/p1",
                        "width": width,
                        "height": height,
                        "images": [{"resource": {"service": {"@id": service}}}],
                    }
                ]
            }
        ],
    }
    if thumbnail:
        manifest["thumbnail"] = thumbnail
    return manifest


def v3_manifest(width=1024, height=1024, service=CANVAS_SERVICE, thumbnail=None):
    manifest = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "items": [
            {
                "id": "https://example.org/iiif/3/book2/canvas/p1",
                "width": width,
                "height": height,
                "items": [{"items": [{"body": {"service": [{"id": service}]}}]}],
            }
        ],
    }
    if thumbnail:
        manifest["thumbnail"] = thumbnail
    return manifest


EMPTY_MANIFEST = {"@context": "http://iiif.io/api/presentation/2/context.json"}


class ManifestFetcherExistenceTests(SimpleTestCase):
    def setUp(self):
        self.fetcher = ManifestThumbnailFetcher(RESOURCE)

    @mock.patch(TILE_MODEL)
    def test_a_manifest_tile_means_a_thumbnail_exists(self, tile_model):
        tile_model.objects.filter.return_value = queryset(exists=True)

        self.assertIs(self.fetcher.get_thumbnail(), True)
        tile_model.objects.filter.assert_called_once_with(
            resourceinstance=RESOURCE, nodegroup__node__datatype="manifest"
        )

    @mock.patch(TILE_MODEL)
    def test_no_manifest_tile_means_no_thumbnail(self, tile_model):
        tile_model.objects.filter.return_value = queryset(exists=False)

        self.assertIs(self.fetcher.get_thumbnail(), False)

    @mock.patch(TILE_MODEL)
    def test_an_orm_failure_answers_no_thumbnail_instead_of_raising(self, tile_model):
        tile_model.objects.filter.side_effect = RuntimeError("connection lost")

        self.assertIs(self.fetcher.get_thumbnail(), False)


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(TILE_MODEL)
class ManifestFetcherRetrieveTests(SimpleTestCase):
    def setUp(self):
        self.fetcher = ManifestThumbnailFetcher(RESOURCE)

    def test_returns_the_image_bytes_and_the_type_its_signature_names(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = v2_manifest(
            thumbnail="https://img.example.org/thumb.png"
        )
        safe_fetch.return_value = response(
            content=PNG_BYTES, headers={"Content-Type": "image/png"}
        )

        self.assertEqual(
            self.fetcher.get_thumbnail(retrieve=True), (PNG_BYTES, "image/png")
        )
        fetch_manifest.assert_called_once_with(TILE_MANIFEST_URL)
        safe_fetch.assert_called_once_with(
            "https://img.example.org/thumb.png", headers=IMAGE_HEADERS
        )

    def test_the_content_type_comes_from_the_signature_when_the_header_is_absent(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(content=JPEG_BYTES, headers={})

        self.assertEqual(
            self.fetcher.get_thumbnail(retrieve=True), (JPEG_BYTES, "image/jpeg")
        )
        safe_fetch.assert_called_once_with(DERIVED_THUMBNAIL, headers=IMAGE_HEADERS)

    def test_the_first_tile_value_naming_a_manifest_is_the_one_fetched(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [
                tile(**{MANIFEST_NODE: None, "note": "no url here"}),
                tile(**{MANIFEST_NODE: TILE_MANIFEST_URL}),
            ]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response()

        self.fetcher.get_thumbnail(retrieve=True)

        fetch_manifest.assert_called_once_with(TILE_MANIFEST_URL)

    def test_returns_none_when_there_is_no_manifest_tile(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()
        safe_fetch.assert_not_called()

    def test_returns_none_when_no_tile_value_looks_like_a_manifest_url(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: "https://example.org/iiif/2/book1/info.json"})]
        )

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()

    def test_returns_none_when_the_manifest_cannot_be_fetched(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = None

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_when_the_manifest_carries_no_thumbnail_url(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = EMPTY_MANIFEST

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_when_the_image_response_is_not_200(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(status=404, content=b"not found")

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))

    def test_a_declared_non_image_is_refused(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(
            content=b"<html>rate limited</html>",
            headers={"Content-Type": "text/html"},
        )

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))

    def test_bytes_that_are_not_an_image_are_refused_whatever_is_declared(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(
            content=b"<svg onload=alert(1)>",
            headers={"Content-Type": "image/png"},
        )

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))

    def test_an_orm_failure_returns_none_instead_of_raising(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.side_effect = RuntimeError("connection lost")

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))


class ComponentFetcherExistenceTests(SimpleTestCase):
    def setUp(self):
        self.fetcher = ComponentThumbnailFetcher(RESOURCE)

    @mock.patch(ANNOTATION_MODEL)
    def test_an_annotation_means_a_thumbnail_exists(self, vw_annotation):
        vw_annotation.objects.filter.return_value = queryset(exists=True)

        self.assertIs(self.fetcher.get_thumbnail(), True)
        vw_annotation.objects.filter.assert_called_once_with(resourceinstance=RESOURCE)

    @mock.patch(ANNOTATION_MODEL)
    def test_no_annotation_means_no_thumbnail(self, vw_annotation):
        vw_annotation.objects.filter.return_value = queryset(exists=False)

        self.assertIs(self.fetcher.get_thumbnail(), False)

    @mock.patch(ANNOTATION_MODEL)
    def test_an_orm_failure_answers_no_thumbnail_instead_of_raising(
        self, vw_annotation
    ):
        vw_annotation.objects.filter.side_effect = RuntimeError("view missing")

        self.assertIs(self.fetcher.get_thumbnail(), False)


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(ANNOTATION_MODEL)
class ComponentFetcherRetrieveTests(SimpleTestCase):
    def setUp(self):
        self.fetcher = ComponentThumbnailFetcher(RESOURCE)

    def test_requests_the_iiif_region_of_the_annotated_polygon(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(content=REGION_BYTES)

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
        fetch_manifest.assert_called_once_with(ANNOTATION_MANIFEST_URL)
        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/{POLYGON_REGION}/full/0/default.jpg",
            headers=IMAGE_HEADERS,
        )

    def test_a_declared_png_serving_jpeg_bytes_is_served_as_jpeg(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(headers={"Content-Type": "image/png"})

        _, content_type = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(content_type, "image/jpeg")

    def test_the_matched_canvas_dimensions_clamp_the_region(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest(width=60, height=60)
        safe_fetch.return_value = response()

        self.fetcher.get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/22,22,38,38/full/0/default.jpg", headers=IMAGE_HEADERS
        )

    def test_an_unmatched_canvas_falls_back_to_1000_by_1000(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Polygon", "coordinates": FAR_POLYGON})]
        )
        fetch_manifest.return_value = v2_manifest(
            width=4000, height=4000, service="https://img.example.org/iiif/2/other"
        )
        safe_fetch.return_value = response()

        self.fetcher.get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/{FAR_POLYGON_DEFAULT_CANVAS_REGION}/full/0/default.jpg",
            headers=IMAGE_HEADERS,
        )

    def test_returns_none_when_the_resource_has_no_annotation(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset([])

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()

    def test_returns_none_when_the_annotation_has_no_canvas_service(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset([annotation(canvas=None)])

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()

    def test_returns_none_when_the_annotation_names_no_manifest(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(manifest=None)]
        )

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()

    def test_returns_none_when_the_manifest_cannot_be_fetched(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = None

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_for_a_geometry_that_is_not_a_polygon(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Point", "coordinates": POINT})]
        )
        fetch_manifest.return_value = v2_manifest()

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_when_the_polygon_yields_no_bbox(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Polygon", "coordinates": [[]]})]
        )
        fetch_manifest.return_value = v2_manifest()

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_when_the_image_response_is_not_200(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(status=503)

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))

    def test_an_orm_failure_returns_none_instead_of_raising(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.side_effect = RuntimeError("view missing")

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))


class FindCanvasByServiceTests(SimpleTestCase):
    fetchers = (ComponentThumbnailFetcher, AnalysisThumbnailFetcher)

    def test_matches_the_image_service_of_a_v2_canvas(self):
        manifest = v2_manifest()
        for fetcher in self.fetchers:
            with self.subTest(fetcher=fetcher.__name__):
                self.assertIs(
                    fetcher._find_canvas_by_service(manifest, CANVAS_SERVICE),
                    manifest["sequences"][0]["canvases"][0],
                )

    def test_matches_the_image_service_of_a_v3_canvas(self):
        manifest = v3_manifest()
        for fetcher in self.fetchers:
            with self.subTest(fetcher=fetcher.__name__):
                self.assertIs(
                    fetcher._find_canvas_by_service(manifest, CANVAS_SERVICE),
                    manifest["items"][0],
                )

    def test_returns_none_when_no_canvas_carries_that_service(self):
        for fetcher in self.fetchers:
            for label, manifest in (("v2", v2_manifest()), ("v3", v3_manifest())):
                with self.subTest(fetcher=fetcher.__name__, version=label):
                    self.assertIsNone(
                        fetcher._find_canvas_by_service(
                            manifest, "https://img.example.org/iiif/2/absent"
                        )
                    )

    def test_returns_none_without_a_manifest_or_without_a_service_url(self):
        for fetcher in self.fetchers:
            with self.subTest(fetcher=fetcher.__name__):
                self.assertIsNone(fetcher._find_canvas_by_service(None, CANVAS_SERVICE))
                self.assertIsNone(fetcher._find_canvas_by_service(v2_manifest(), None))

    def test_a_list_valued_v2_image_service_is_not_matched(self):
        manifest = v2_manifest()
        # Legal IIIF v2, but CanvasIIIF._get_service_from_canvas_v2 assumes a
        # dict; the AttributeError is swallowed and the canvas is skipped.
        manifest["sequences"][0]["canvases"][0]["images"][0]["resource"]["service"] = [
            {"@id": CANVAS_SERVICE}
        ]
        for fetcher in self.fetchers:
            with self.subTest(fetcher=fetcher.__name__):
                self.assertIsNone(
                    fetcher._find_canvas_by_service(manifest, CANVAS_SERVICE)
                )


class AnalysisFetcherExistenceTests(SimpleTestCase):
    def setUp(self):
        self.fetcher = AnalysisThumbnailFetcher(RESOURCE)

    @mock.patch(ANNOTATION_MODEL)
    @mock.patch(TILE_MODEL)
    def test_a_manifest_tile_alone_means_a_thumbnail_exists(
        self, tile_model, vw_annotation
    ):
        tile_model.objects.filter.return_value = queryset(exists=True)
        vw_annotation.objects.filter.return_value = queryset(exists=False)

        self.assertIs(self.fetcher.get_thumbnail(), True)
        tile_model.objects.filter.assert_called_once_with(
            resourceinstance=RESOURCE, nodegroup__node__datatype="manifest"
        )
        # The annotation view is the expensive half of this probe and cannot
        # change the answer once a manifest tile exists.
        vw_annotation.objects.filter.assert_not_called()

    @mock.patch(ANNOTATION_MODEL)
    @mock.patch(TILE_MODEL)
    def test_an_annotation_alone_means_a_thumbnail_exists(
        self, tile_model, vw_annotation
    ):
        tile_model.objects.filter.return_value = queryset(exists=False)
        vw_annotation.objects.filter.return_value = queryset(exists=True)

        self.assertIs(self.fetcher.get_thumbnail(), True)
        vw_annotation.objects.filter.assert_called_once_with(resourceinstance=RESOURCE)

    @mock.patch(ANNOTATION_MODEL)
    @mock.patch(TILE_MODEL)
    def test_neither_means_no_thumbnail(self, tile_model, vw_annotation):
        tile_model.objects.filter.return_value = queryset(exists=False)
        vw_annotation.objects.filter.return_value = queryset(exists=False)

        self.assertIs(self.fetcher.get_thumbnail(), False)

    @mock.patch(ANNOTATION_MODEL)
    @mock.patch(TILE_MODEL)
    def test_an_orm_failure_answers_no_thumbnail_instead_of_raising(
        self, tile_model, vw_annotation
    ):
        tile_model.objects.filter.side_effect = RuntimeError("connection lost")

        self.assertIs(self.fetcher.get_thumbnail(), False)


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(ANNOTATION_MODEL)
@mock.patch(TILE_MODEL)
class AnalysisFetcherRetrieveTests(SimpleTestCase):
    def setUp(self):
        self.fetcher = AnalysisThumbnailFetcher(RESOURCE)

    def with_manifest_tile(self, tile_model):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )

    def test_the_manifest_thumbnail_wins_and_the_annotation_is_never_queried(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.with_manifest_tile(tile_model)
        fetch_manifest.return_value = v2_manifest(
            thumbnail="https://img.example.org/thumb.png"
        )
        safe_fetch.return_value = response(
            content=PNG_BYTES, headers={"Content-Type": "image/png"}
        )

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (PNG_BYTES, "image/png"))
        safe_fetch.assert_called_once_with(
            "https://img.example.org/thumb.png", headers=IMAGE_HEADERS
        )
        vw_annotation.objects.filter.assert_not_called()

    def test_the_manifest_content_type_comes_from_the_signature(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.with_manifest_tile(tile_model)
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(content=JPEG_BYTES, headers={})

        self.assertEqual(
            self.fetcher.get_thumbnail(retrieve=True), (JPEG_BYTES, "image/jpeg")
        )
        safe_fetch.assert_called_once_with(DERIVED_THUMBNAIL, headers=IMAGE_HEADERS)

    def test_a_failed_manifest_fetch_falls_back_to_the_annotation(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.with_manifest_tile(tile_model)
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.side_effect = [None, v2_manifest()]
        safe_fetch.return_value = response(content=REGION_BYTES)

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
        self.assertEqual(
            fetch_manifest.call_args_list,
            [mock.call(TILE_MANIFEST_URL), mock.call(ANNOTATION_MANIFEST_URL)],
        )
        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/{POLYGON_REGION}/full/0/default.jpg",
            headers=IMAGE_HEADERS,
        )

    def test_a_manifest_without_a_thumbnail_url_falls_back_to_the_annotation(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.with_manifest_tile(tile_model)
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.side_effect = [EMPTY_MANIFEST, v2_manifest()]
        safe_fetch.return_value = response(content=REGION_BYTES)

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/{POLYGON_REGION}/full/0/default.jpg",
            headers=IMAGE_HEADERS,
        )

    def test_a_non_200_manifest_thumbnail_falls_back_to_the_annotation(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.with_manifest_tile(tile_model)
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.side_effect = [response(status=404), response(content=REGION_BYTES)]

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
        self.assertEqual(
            [call.args[0] for call in safe_fetch.call_args_list],
            [
                DERIVED_THUMBNAIL,
                f"{CANVAS_SERVICE}/{POLYGON_REGION}/full/0/default.jpg",
            ],
        )

    def test_a_tile_naming_no_manifest_falls_straight_through_to_the_annotation(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: "https://example.org/iiif/2/book1/info.json"})]
        )
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(content=REGION_BYTES)

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
        fetch_manifest.assert_called_once_with(ANNOTATION_MANIFEST_URL)

    def test_requests_the_iiif_region_around_an_annotated_point(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Point", "coordinates": POINT})]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(content=POINT_REGION_BYTES)

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (POINT_REGION_BYTES, "image/jpeg"))
        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/{POINT_REGION}/full/0/default.jpg", headers=IMAGE_HEADERS
        )

    def test_the_annotation_radius_property_sizes_the_point_region(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Point", "coordinates": POINT}, radius=4)]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response()

        self.fetcher.get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/28,44,40,40/full/0/default.jpg", headers=IMAGE_HEADERS
        )

    def test_requests_the_iiif_region_of_an_annotated_polygon(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(content=REGION_BYTES)

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/{POLYGON_REGION}/full/0/default.jpg",
            headers=IMAGE_HEADERS,
        )

    def test_a_v3_manifest_supplies_the_canvas_dimensions(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v3_manifest(width=60, height=60)
        safe_fetch.return_value = response()

        self.fetcher.get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/22,22,38,38/full/0/default.jpg", headers=IMAGE_HEADERS
        )

    def test_returns_none_when_there_is_neither_manifest_nor_annotation(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset([])

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()
        safe_fetch.assert_not_called()

    def test_returns_none_when_the_annotation_has_no_canvas_service(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset([annotation(canvas=None)])

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()

    def test_returns_none_when_the_annotation_names_no_manifest(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(manifest=None)]
        )

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()

    def test_returns_none_when_the_annotation_manifest_cannot_be_fetched(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = None

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_for_a_geometry_that_is_neither_point_nor_polygon(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(
            [
                annotation(
                    geometry={
                        "type": "LineString",
                        "coordinates": [[1.0, -1.0], [2.0, -2.0]],
                    }
                )
            ]
        )
        fetch_manifest.return_value = v2_manifest()

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_when_the_geometry_has_no_coordinates(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Polygon", "coordinates": []})]
        )
        fetch_manifest.return_value = v2_manifest()

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_when_the_polygon_yields_no_bbox(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Polygon", "coordinates": [[]]})]
        )
        fetch_manifest.return_value = v2_manifest()

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

    def test_returns_none_when_the_region_response_is_not_200(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(status=500)

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))

    def test_an_orm_failure_returns_none_instead_of_raising(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.side_effect = RuntimeError("connection lost")

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
