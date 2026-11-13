"""What the three search-thumbnail fetchers promise, without a database or a network.

Each fetcher answers two different questions through one method: with
``retrieve=False`` it is an existence probe deciding whether a search result
advertises a thumbnail at all, and with ``retrieve=True`` it returns
``(bytes, content_type)``. These tests lock both answers for each fetcher, every
early ``None``, the exact IIIF Image API region URL built from an annotation
bbox, and ``AnalysisThumbnailFetcher``'s manifest-before-annotation priority, and the
model each fetcher is registered on.

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

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from arches.app.utils.search_thumbnail_fetcher_factory import (
    SearchThumbnailFetcherFactory,
)

from manuspectrum.utils.cache import get_or_build, stable_cache_key
from manuspectrum.utils.search_thumbnail_fetchers import (
    _region_size,
    _sniff_image_type,
    AnalysisThumbnailFetcher,
    ComponentThumbnailFetcher,
    DocumentThumbnailFetcher,
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
POLYGON_REGION_SIZE = f"{POLYGON_REGION}/52,"
FAR_POLYGON = [[[20.0, -20.0], [40.0, -20.0], [40.0, -40.0], [20.0, -40.0]]]
FAR_POLYGON_UNCLAMPED_REGION = "630,630,660,660/300,"
POINT = [1.5, -2.0]
POINT_REGION = "0,14,100,100/100,"


class FetcherTestCase(SimpleTestCase):
    """Clears the default cache: a miss flag outlives a test otherwise."""

    def setUp(self):
        super().setUp()
        cache.clear()


def tile(**data):
    return SimpleNamespace(data=data)


def queryset(rows=(), exists=None):
    qs = mock.MagicMock()
    qs.__iter__.side_effect = lambda: iter(rows)
    qs.order_by.return_value = qs
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


class ManifestFetcherExistenceTests(FetcherTestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = DocumentThumbnailFetcher(RESOURCE)

    @mock.patch(TILE_MODEL)
    def test_a_manifest_url_means_a_thumbnail_exists(self, tile_model):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )

        self.assertIs(self.fetcher.get_thumbnail(), True)
        tile_model.objects.filter.assert_called_once_with(
            resourceinstance=RESOURCE, nodegroup__node__datatype="manifest"
        )

    @mock.patch(TILE_MODEL)
    def test_no_manifest_tile_means_none(self, tile_model):
        tile_model.objects.filter.return_value = queryset([])

        self.assertIsNone(self.fetcher.get_thumbnail())

    @mock.patch(TILE_MODEL)
    def test_a_tile_naming_no_manifest_means_none(self, tile_model):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: "https://example.org/iiif/2/book1/info.json"})]
        )

        self.assertIsNone(self.fetcher.get_thumbnail())

    @mock.patch(TILE_MODEL)
    def test_an_orm_failure_answers_none_instead_of_raising(self, tile_model):
        tile_model.objects.filter.side_effect = RuntimeError("connection lost")

        self.assertIsNone(self.fetcher.get_thumbnail())

    @mock.patch(SAFE_FETCH)
    @mock.patch(FETCH_MANIFEST)
    @mock.patch(TILE_MODEL)
    def test_the_probe_reads_no_manifest_and_fetches_no_image(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )

        self.fetcher.get_thumbnail()

        fetch_manifest.assert_not_called()
        safe_fetch.assert_not_called()


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(TILE_MODEL)
class ManifestFetcherRetrieveTests(FetcherTestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = DocumentThumbnailFetcher(RESOURCE)

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
            "https://img.example.org/thumb.png",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
        )

    @override_settings(
        CANTALOUPE_HTTP_ENDPOINT="https://manuspectrum.test/iiifserver/",
        CANTALOUPE_INTERNAL_ENDPOINT="http://cantaloupe:8182/",
    )
    def test_a_thumbnail_of_the_own_image_service_is_read_internally(
        self, tile_model, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = v2_manifest(
            thumbnail="https://manuspectrum.test/iiifserver/iiif/2/a.tif/full/90,/0/default.jpg"
        )
        safe_fetch.return_value = response(
            content=PNG_BYTES, headers={"Content-Type": "image/png"}
        )

        self.fetcher.get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            "http://cantaloupe:8182/iiif/2/a.tif/full/90,/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
            allow_private=True,
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
        safe_fetch.assert_called_once_with(
            DERIVED_THUMBNAIL, headers=IMAGE_HEADERS, purpose="thumbnail"
        )

    def test_the_first_value_naming_a_manifest_is_the_one_fetched(
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


LOCAL_UUID = "1fef8336-b2b3-440b-8985-0069bea072a0"
IIIF_MANIFEST_MODEL = "manuspectrum.iiif.sources.IIIFManifest"


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(IIIF_MANIFEST_MODEL)
@mock.patch(TILE_MODEL)
class LocalManifestFetcherTests(FetcherTestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = DocumentThumbnailFetcher(RESOURCE)

    def stored(self, iiif_manifest, manifest):
        rows = iiif_manifest.objects.filter.return_value.values_list.return_value
        rows.first.return_value = manifest

    def test_a_relative_local_manifest_is_read_from_the_database_without_http(
        self, tile_model, iiif_manifest, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: f"/manifest/{LOCAL_UUID}"})]
        )
        self.stored(iiif_manifest, v2_manifest())
        safe_fetch.return_value = response()

        self.assertEqual(
            self.fetcher.get_thumbnail(retrieve=True), (JPEG_BYTES, "image/jpeg")
        )
        fetch_manifest.assert_not_called()
        iiif_manifest.objects.filter.assert_called_once_with(globalid=LOCAL_UUID)
        safe_fetch.assert_called_once_with(
            DERIVED_THUMBNAIL, headers=IMAGE_HEADERS, purpose="thumbnail"
        )

    def test_an_absolute_local_manifest_is_read_from_the_database_without_http(
        self, tile_model, iiif_manifest, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [
                tile(
                    **{
                        MANIFEST_NODE: f"{settings.PUBLIC_SERVER_ADDRESS}manifest/{LOCAL_UUID}"
                    }
                )
            ]
        )
        self.stored(iiif_manifest, v2_manifest())
        safe_fetch.return_value = response()

        self.assertEqual(
            self.fetcher.get_thumbnail(retrieve=True), (JPEG_BYTES, "image/jpeg")
        )
        fetch_manifest.assert_not_called()
        iiif_manifest.objects.filter.assert_called_once_with(globalid=LOCAL_UUID)

    def test_an_unknown_local_manifest_gives_no_thumbnail(
        self, tile_model, iiif_manifest, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: f"/manifest/{LOCAL_UUID}"})]
        )
        self.stored(iiif_manifest, None)

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_not_called()
        safe_fetch.assert_not_called()

    def test_an_external_manifest_is_still_fetched_over_http(
        self, tile_model, iiif_manifest, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response()

        self.fetcher.get_thumbnail(retrieve=True)

        fetch_manifest.assert_called_once_with(TILE_MANIFEST_URL)
        iiif_manifest.objects.filter.assert_not_called()


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(IIIF_MANIFEST_MODEL)
@mock.patch(ANNOTATION_MODEL)
@mock.patch(TILE_MODEL)
class LocalManifestAnnotationFetcherTests(FetcherTestCase):
    def stored(self, iiif_manifest, manifest):
        rows = iiif_manifest.objects.filter.return_value.values_list.return_value
        rows.first.return_value = manifest

    def test_a_component_reads_its_local_manifest_from_the_database(
        self, tile_model, vw_annotation, iiif_manifest, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(manifest=f"/manifest/{LOCAL_UUID}")]
        )
        self.stored(iiif_manifest, v2_manifest())
        safe_fetch.return_value = response(content=REGION_BYTES)

        result = ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
        fetch_manifest.assert_not_called()

    def test_an_analysis_manifest_tile_reads_its_local_manifest_from_the_database(
        self, tile_model, vw_annotation, iiif_manifest, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: f"/manifest/{LOCAL_UUID}"})]
        )
        self.stored(iiif_manifest, v2_manifest())
        safe_fetch.return_value = response()

        result = AnalysisThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        self.assertEqual(result, (JPEG_BYTES, "image/jpeg"))
        fetch_manifest.assert_not_called()

    def test_an_analysis_annotation_reads_its_local_manifest_from_the_database(
        self, tile_model, vw_annotation, iiif_manifest, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(manifest=f"/manifest/{LOCAL_UUID}")]
        )
        self.stored(iiif_manifest, v2_manifest())
        safe_fetch.return_value = response(content=REGION_BYTES)

        result = AnalysisThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
        fetch_manifest.assert_not_called()


class ComponentFetcherExistenceTests(FetcherTestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = ComponentThumbnailFetcher(RESOURCE)

    @mock.patch(ANNOTATION_MODEL)
    def test_an_annotation_means_a_thumbnail_exists(self, vw_annotation):
        vw_annotation.objects.filter.return_value = queryset(exists=True)

        self.assertIs(self.fetcher.get_thumbnail(), True)
        vw_annotation.objects.filter.assert_called_once_with(resourceinstance=RESOURCE)

    @mock.patch(ANNOTATION_MODEL)
    def test_no_annotation_means_none(self, vw_annotation):
        vw_annotation.objects.filter.return_value = queryset(exists=False)

        self.assertIsNone(self.fetcher.get_thumbnail())

    @mock.patch(ANNOTATION_MODEL)
    def test_an_orm_failure_answers_none_instead_of_raising(self, vw_annotation):
        vw_annotation.objects.filter.side_effect = RuntimeError("view missing")

        self.assertIsNone(self.fetcher.get_thumbnail())


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(ANNOTATION_MODEL)
class ComponentFetcherRetrieveTests(FetcherTestCase):
    def setUp(self):
        super().setUp()
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
            f"{CANVAS_SERVICE}/{POLYGON_REGION_SIZE}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
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
            f"{CANVAS_SERVICE}/22,22,38,38/38,/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
        )

    def test_an_unmatched_canvas_leaves_the_region_unclamped(
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
            f"{CANVAS_SERVICE}/{FAR_POLYGON_UNCLAMPED_REGION}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
        )

    def test_malformed_coordinates_on_an_unmatched_canvas_fetch_nothing(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Polygon", "coordinates": [["x"]]})]
        )
        fetch_manifest.return_value = v2_manifest(
            service="https://img.example.org/iiif/2/other"
        )

        self.assertIsNone(self.fetcher.get_thumbnail(retrieve=True))
        safe_fetch.assert_not_called()

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

    def test_a_point_zone_is_accepted(self, vw_annotation, fetch_manifest, safe_fetch):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Point", "coordinates": POINT})]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(content=POINT_REGION_BYTES)

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (POINT_REGION_BYTES, "image/jpeg"))
        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/{POINT_REGION}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
        )

    def test_returns_none_for_a_geometry_that_is_neither_point_nor_polygon(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "LineString", "coordinates": [[1, -1]]})]
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


class AnalysisFetcherExistenceTests(FetcherTestCase):
    def setUp(self):
        super().setUp()
        self.fetcher = AnalysisThumbnailFetcher(RESOURCE)

    @mock.patch(ANNOTATION_MODEL)
    @mock.patch(TILE_MODEL)
    def test_a_manifest_tile_alone_means_a_thumbnail_exists(
        self, tile_model, vw_annotation
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
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
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(exists=True)

        self.assertIs(self.fetcher.get_thumbnail(), True)
        vw_annotation.objects.filter.assert_called_once_with(resourceinstance=RESOURCE)

    @mock.patch(ANNOTATION_MODEL)
    @mock.patch(TILE_MODEL)
    def test_neither_means_none(self, tile_model, vw_annotation):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset(exists=False)

        self.assertIsNone(self.fetcher.get_thumbnail())

    @mock.patch(ANNOTATION_MODEL)
    @mock.patch(TILE_MODEL)
    def test_an_orm_failure_answers_none_instead_of_raising(
        self, tile_model, vw_annotation
    ):
        tile_model.objects.filter.side_effect = RuntimeError("connection lost")

        self.assertIsNone(self.fetcher.get_thumbnail())


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(ANNOTATION_MODEL)
@mock.patch(TILE_MODEL)
class AnalysisFetcherRetrieveTests(FetcherTestCase):
    def setUp(self):
        super().setUp()
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
            "https://img.example.org/thumb.png",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
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
        safe_fetch.assert_called_once_with(
            DERIVED_THUMBNAIL, headers=IMAGE_HEADERS, purpose="thumbnail"
        )

    def test_a_refused_manifest_image_fetch_falls_back_to_the_annotation(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.with_manifest_tile(tile_model)
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest(
            thumbnail="https://img.example.org/thumb.png"
        )
        safe_fetch.side_effect = [
            RuntimeError("Disallowed port"),
            response(content=REGION_BYTES),
        ]

        result = self.fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(result, (REGION_BYTES, "image/jpeg"))

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
            f"{CANVAS_SERVICE}/{POLYGON_REGION_SIZE}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
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
            f"{CANVAS_SERVICE}/{POLYGON_REGION_SIZE}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
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
                f"{CANVAS_SERVICE}/{POLYGON_REGION_SIZE}/0/default.jpg",
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
            f"{CANVAS_SERVICE}/{POINT_REGION}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
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
            f"{CANVAS_SERVICE}/28,44,40,40/40,/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
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
            f"{CANVAS_SERVICE}/{POLYGON_REGION_SIZE}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
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
            f"{CANVAS_SERVICE}/22,22,38,38/38,/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
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


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(ANNOTATION_MODEL)
class ZoneChoiceTests(FetcherTestCase):
    def test_zones_are_read_in_feature_id_order(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        rows = queryset([annotation()])
        vw_annotation.objects.filter.return_value = rows
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response()

        ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        rows.order_by.assert_called_once_with("feature_id")

    def test_a_zone_drawn_outside_the_image_is_skipped_for_the_next_one(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        outside = annotation(geometry={"type": "Polygon", "coordinates": FAR_POLYGON})
        vw_annotation.objects.filter.return_value = queryset([outside, annotation()])
        fetch_manifest.return_value = v2_manifest(width=100, height=100)
        safe_fetch.return_value = response(content=REGION_BYTES)

        for fetcher in (ComponentThumbnailFetcher, AnalysisThumbnailFetcher):
            with self.subTest(fetcher=fetcher.__name__):
                cache.clear()
                safe_fetch.reset_mock()
                with mock.patch(TILE_MODEL) as tile_model:
                    tile_model.objects.filter.return_value = queryset([])
                    result = fetcher(RESOURCE).get_thumbnail(retrieve=True)
                self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
                safe_fetch.assert_called_once_with(
                    f"{CANVAS_SERVICE}/{POLYGON_REGION_SIZE}/0/default.jpg",
                    headers=IMAGE_HEADERS,
                    purpose="thumbnail",
                )

    def test_only_one_image_is_requested_when_it_fails(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(), annotation()]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response(status=403)

        self.assertIsNone(ComponentThumbnailFetcher(RESOURCE).get_thumbnail(True))
        self.assertEqual(safe_fetch.call_count, 1)

    def test_a_canvas_is_found_by_its_id_as_well_as_by_its_image_service(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        canvas_id = "https://example.org/iiif/2/book2/canvas/p1"
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(canvas=canvas_id)]
        )
        fetch_manifest.return_value = v2_manifest(width=60, height=60)
        safe_fetch.return_value = response()

        ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/22,22,38,38/38,/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
        )

    def test_a_list_valued_v2_image_service_does_not_break_the_lookup(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        manifest = v2_manifest(width=60, height=60)
        manifest["sequences"][0]["canvases"][0]["images"][0]["resource"]["service"] = [
            {"@id": CANVAS_SERVICE}
        ]
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = manifest
        safe_fetch.return_value = response()

        result = ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        self.assertEqual(result, (JPEG_BYTES, "image/jpeg"))
        safe_fetch.assert_called_once()

    def test_a_zone_left_of_or_above_the_image_is_skipped(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        left = [[[-20.0, -1.0], [-10.0, -1.0], [-10.0, -2.0], [-20.0, -2.0]]]
        above = [[[1.0, 10.0], [2.0, 10.0], [2.0, 5.0], [1.0, 5.0]]]
        zones = {
            "polygon left": {"type": "Polygon", "coordinates": left},
            "polygon above": {"type": "Polygon", "coordinates": above},
            "point left": {"type": "Point", "coordinates": [-20.0, -2.0]},
            "point above": {"type": "Point", "coordinates": [1.5, 20.0]},
        }
        fetch_manifest.return_value = v2_manifest(width=100, height=100)
        safe_fetch.return_value = response(content=REGION_BYTES)
        for label, geometry in zones.items():
            with self.subTest(zone=label):
                cache.clear()
                safe_fetch.reset_mock()
                vw_annotation.objects.filter.return_value = queryset(
                    [annotation(geometry=geometry), annotation()]
                )
                result = ComponentThumbnailFetcher(RESOURCE).get_thumbnail(True)
                self.assertEqual(result, (REGION_BYTES, "image/jpeg"))
                safe_fetch.assert_called_once_with(
                    f"{CANVAS_SERVICE}/{POLYGON_REGION_SIZE}/0/default.jpg",
                    headers=IMAGE_HEADERS,
                    purpose="thumbnail",
                )

    def test_a_point_whose_view_radius_reaches_the_image_is_kept(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Point", "coordinates": [-1.0, -2.0]})]
        )
        fetch_manifest.return_value = v2_manifest(width=100, height=100)
        safe_fetch.return_value = response()

        self.assertTrue(ComponentThumbnailFetcher(RESOURCE).get_thumbnail(True))

    def test_a_trailing_slash_gives_no_double_slash(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(canvas="https://other.example/iiif/2/unknown/")]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response()

        ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            f"https://other.example/iiif/2/unknown/{POLYGON_REGION_SIZE}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
        )

    @override_settings(EXPLORER_LEGACY_HOSTS=("legacy.example",))
    def test_a_legacy_host_canvas_is_rewritten_before_use(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        legacy = "http://legacy.example/iiif/2/page1"
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(canvas=legacy)]
        )
        fetch_manifest.return_value = v2_manifest(
            service=f"{settings.PUBLIC_SERVER_ADDRESS}iiif/2/page1"
        )
        safe_fetch.return_value = response()

        ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            f"{settings.PUBLIC_SERVER_ADDRESS}iiif/2/page1/{POLYGON_REGION_SIZE}/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
        )

    def test_an_unreadable_manifest_ends_the_search_without_an_image_fetch(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        vw_annotation.objects.filter.return_value = queryset(
            [
                annotation(manifest="https://example.org/a/manifest.json"),
                annotation(),
            ]
        )
        fetch_manifest.return_value = None

        self.assertIsNone(ComponentThumbnailFetcher(RESOURCE).get_thumbnail(True))
        fetch_manifest.assert_called_once()
        safe_fetch.assert_not_called()

    def test_each_manifest_is_read_once_per_call(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        outside = annotation(geometry={"type": "Polygon", "coordinates": FAR_POLYGON})
        vw_annotation.objects.filter.return_value = queryset(
            [outside, outside, annotation()]
        )
        fetch_manifest.return_value = v2_manifest(width=100, height=100)
        safe_fetch.return_value = response()

        ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        fetch_manifest.assert_called_once_with(ANNOTATION_MANIFEST_URL)

    def test_a_large_region_is_asked_at_a_bounded_size(
        self, vw_annotation, fetch_manifest, safe_fetch
    ):
        wide = [[[0.0, -0.0], [100.0, -0.0], [100.0, -25.0], [0.0, -25.0]]]
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry={"type": "Polygon", "coordinates": wide})]
        )
        fetch_manifest.return_value = v2_manifest(width=8000, height=8000)
        safe_fetch.return_value = response()

        ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        safe_fetch.assert_called_once_with(
            f"{CANVAS_SERVICE}/0,0,3220,820/300,/0/default.jpg",
            headers=IMAGE_HEADERS,
            purpose="thumbnail",
        )


class RegionSizeTests(SimpleTestCase):
    def test_a_region_within_the_bound_keeps_its_width(self):
        self.assertEqual(_region_size(200, 100), 200)
        self.assertEqual(_region_size(300, 300), 300)

    def test_the_longest_side_is_brought_to_the_bound(self):
        self.assertEqual(_region_size(600, 300), 300)
        self.assertEqual(_region_size(300, 600), 150)

    def test_the_width_is_at_least_one_pixel(self):
        self.assertEqual(_region_size(1, 3000), 1)


class SniffImageTypeTests(SimpleTestCase):
    def test_webp_is_recognised_by_its_marker_at_offset_eight(self):
        self.assertEqual(
            _sniff_image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp"
        )

    def test_unknown_bytes_are_not_an_image(self):
        self.assertIsNone(_sniff_image_type(b"<html>"))


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(ANNOTATION_MODEL)
@mock.patch(TILE_MODEL)
class MissMemoryTests(FetcherTestCase):
    fetchers = (
        DocumentThumbnailFetcher,
        ComponentThumbnailFetcher,
        AnalysisThumbnailFetcher,
    )

    def sources(self, tile_model, vw_annotation, fetch_manifest):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        vw_annotation.objects.filter.return_value = queryset([annotation()])
        fetch_manifest.return_value = v2_manifest()

    def test_a_failed_retrieval_is_remembered_for_both_modes(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.sources(tile_model, vw_annotation, fetch_manifest)
        for fetcher in self.fetchers:
            with self.subTest(fetcher=fetcher.__name__):
                cache.clear()
                safe_fetch.reset_mock()
                safe_fetch.return_value = response(status=403)
                self.assertIs(fetcher(RESOURCE).get_thumbnail(), True)

                self.assertIsNone(fetcher(RESOURCE).get_thumbnail(retrieve=True))
                calls = safe_fetch.call_count
                self.assertGreater(calls, 0)

                self.assertIsNone(fetcher(RESOURCE).get_thumbnail())
                self.assertIsNone(fetcher(RESOURCE).get_thumbnail(retrieve=True))
                self.assertEqual(safe_fetch.call_count, calls)

    def test_a_success_stores_nothing(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.sources(tile_model, vw_annotation, fetch_manifest)
        safe_fetch.return_value = response()
        for fetcher in self.fetchers:
            with self.subTest(fetcher=fetcher.__name__):
                cache.clear()
                self.assertTrue(fetcher(RESOURCE).get_thumbnail(retrieve=True))
                self.assertIs(fetcher(RESOURCE).get_thumbnail(), True)

    def test_no_source_is_not_remembered_as_a_miss(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset([])
        vw_annotation.objects.filter.return_value = queryset([])
        for fetcher in self.fetchers:
            with self.subTest(fetcher=fetcher.__name__):
                self.assertIsNone(fetcher(RESOURCE).get_thumbnail(retrieve=True))

        self.sources(tile_model, vw_annotation, fetch_manifest)
        safe_fetch.return_value = response()
        for fetcher in self.fetchers:
            with self.subTest(fetcher=fetcher.__name__, then="source"):
                self.assertTrue(fetcher(RESOURCE).get_thumbnail(retrieve=True))

    @override_settings(SEARCH_THUMBNAIL_MISS_TTL=123)
    def test_the_flag_lives_for_the_configured_ttl(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.sources(tile_model, vw_annotation, fetch_manifest)
        safe_fetch.return_value = response(status=403)

        with mock.patch(f"{FETCHERS}.cache") as fake_cache:
            fake_cache.get.return_value = None
            ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        self.assertEqual(fake_cache.set.call_args.args[1:], (True, 123))

    def test_a_cache_backend_error_does_not_break_the_thumbnail(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.sources(tile_model, vw_annotation, fetch_manifest)
        safe_fetch.return_value = response()

        with mock.patch(f"{FETCHERS}.cache") as fake_cache:
            fake_cache.get.side_effect = ConnectionError("down")
            fake_cache.set.side_effect = ConnectionError("down")
            self.assertTrue(DocumentThumbnailFetcher(RESOURCE).get_thumbnail(True))
            self.assertIs(DocumentThumbnailFetcher(RESOURCE).get_thumbnail(), True)
            cache.clear()
            safe_fetch.return_value = response(status=500)
            self.assertIsNone(DocumentThumbnailFetcher(RESOURCE).get_thumbnail(True))

    def test_the_analysis_manifest_is_the_first_manifest_url_of_any_tile(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [
                tile(**{MANIFEST_NODE: None, "note": "no url"}),
                tile(**{MANIFEST_NODE: TILE_MANIFEST_URL}),
            ]
        )
        fetch_manifest.return_value = v2_manifest()
        safe_fetch.return_value = response()

        fetcher = AnalysisThumbnailFetcher(RESOURCE)

        self.assertIs(fetcher.get_thumbnail(), True)
        self.assertTrue(fetcher.get_thumbnail(retrieve=True))
        fetch_manifest.assert_called_once_with(TILE_MANIFEST_URL)
        vw_annotation.objects.filter.assert_not_called()


@mock.patch(SAFE_FETCH)
@mock.patch(FETCH_MANIFEST)
@mock.patch(ANNOTATION_MODEL)
@mock.patch(TILE_MODEL)
class ImageCacheTests(FetcherTestCase):
    def zone_setup(self, vw_annotation, fetch_manifest, geometry=None):
        vw_annotation.objects.filter.return_value = queryset(
            [annotation(geometry=geometry)]
        )
        fetch_manifest.return_value = v2_manifest()

    def test_a_zone_image_is_fetched_upstream_once(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.zone_setup(vw_annotation, fetch_manifest)
        safe_fetch.return_value = response(content=REGION_BYTES)
        fetcher = ComponentThumbnailFetcher(RESOURCE)

        first = fetcher.get_thumbnail(retrieve=True)
        second = fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(first, (REGION_BYTES, "image/jpeg"))
        self.assertEqual(second, first)
        safe_fetch.assert_called_once()

    def test_a_changed_zone_is_fetched_again(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        safe_fetch.return_value = response(content=REGION_BYTES)
        fetcher = ComponentThumbnailFetcher(RESOURCE)
        self.zone_setup(vw_annotation, fetch_manifest)
        fetcher.get_thumbnail(retrieve=True)

        self.zone_setup(
            vw_annotation,
            fetch_manifest,
            geometry={"type": "Polygon", "coordinates": FAR_POLYGON},
        )
        fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(safe_fetch.call_count, 2)

    def test_a_failed_fetch_stores_nothing(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.zone_setup(vw_annotation, fetch_manifest)
        safe_fetch.return_value = response(status=403)
        fetcher = ComponentThumbnailFetcher(RESOURCE)
        self.assertIsNone(fetcher.get_thumbnail(retrieve=True))

        cache.clear()
        safe_fetch.return_value = response(
            content=b"<html>", headers={"Content-Type": "text/html"}
        )
        self.assertIsNone(fetcher.get_thumbnail(retrieve=True))

        safe_fetch.return_value = response(content=REGION_BYTES)
        cache.delete(
            stable_cache_key("search-thumbnail-miss", RESOURCE.resourceinstanceid)
        )
        self.assertEqual(
            fetcher.get_thumbnail(retrieve=True), (REGION_BYTES, "image/jpeg")
        )
        self.assertEqual(safe_fetch.call_count, 3)

    def test_a_manifest_thumbnail_is_fetched_upstream_once(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        tile_model.objects.filter.return_value = queryset(
            [tile(**{MANIFEST_NODE: TILE_MANIFEST_URL})]
        )
        fetch_manifest.return_value = v2_manifest(
            thumbnail="https://img.example.org/thumb.png"
        )
        safe_fetch.return_value = response(content=PNG_BYTES)
        fetcher = DocumentThumbnailFetcher(RESOURCE)

        first = fetcher.get_thumbnail(retrieve=True)
        second = fetcher.get_thumbnail(retrieve=True)

        self.assertEqual(first, (PNG_BYTES, "image/png"))
        self.assertEqual(second, first)
        safe_fetch.assert_called_once()

    @override_settings(SEARCH_THUMBNAIL_CACHE_TTL=1234)
    def test_the_image_is_stored_for_the_configured_ttl(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.zone_setup(vw_annotation, fetch_manifest)
        safe_fetch.return_value = response(content=REGION_BYTES)

        with mock.patch(f"{FETCHERS}.get_or_build", wraps=get_or_build) as build:
            ComponentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

        self.assertEqual(build.call_args.args[2], 1234)

    def test_the_default_ttl_is_a_week(
        self, tile_model, vw_annotation, fetch_manifest, safe_fetch
    ):
        self.assertEqual(settings.SEARCH_THUMBNAIL_CACHE_TTL, 7 * 24 * 60 * 60)


class RegistryTests(FetcherTestCase):
    def test_each_model_resolves_to_its_fetcher(self):
        registry = SearchThumbnailFetcherFactory.registry

        self.assertIs(
            registry["0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"], DocumentThumbnailFetcher
        )
        self.assertIs(
            registry["d47595b4-f8a6-419c-8f33-b388206280c4"], ComponentThumbnailFetcher
        )
        self.assertIs(
            registry["60c85aba-f079-45bc-997f-21cdd4f77b6d"], AnalysisThumbnailFetcher
        )
        self.assertNotIn("72ac748a-7368-41e7-9f54-99be41319fac", registry)
