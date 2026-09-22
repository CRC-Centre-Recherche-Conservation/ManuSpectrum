"""What the project's vector-tile route adds to the Arches one.

An empty tile is a 204 a browser may keep while nothing is restricted; a node
the reader cannot see stays a 404; coordinates that name no tile are a 404
rather than a database error. The view tests replace ``MVTTiler``: its SQL
and its per-reader cache are Arches'. ``UnknownNodeOverHttpTests`` goes
through the middleware and the real tiler, which answers an unknown node
before any Elasticsearch call.

Usage:
    python manage.py test tests.test_mvt_view --settings="tests.test_settings"
"""

import uuid
from unittest import mock
from urllib.parse import unquote

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import translation

from manuspectrum.views.mvt import EmptyTileMVTView, tile_coordinates

NODE_ID = "fb5d9046-7052-11ef-8753-0575b5bada34"
VIEWABLE = ["3b1a3c7e-5c1d-4c7c-9b54-6f2d0e8f5a10"]
TILE = b"\x1a\x0bprotobuf"


def pin_language(test, language="en"):
    """Activate *language* for one test; a class decorator would hide the tests."""
    override = translation.override(language)
    override.__enter__()
    test.addCleanup(override.__exit__, None, None, None)


class MVTRoutingTests(SimpleTestCase):
    def setUp(self):
        pin_language(self)

    def test_a_tile_url_reaches_the_project_view(self):
        match = resolve(f"/en/mvt/{NODE_ID}/3/4/2.pbf")

        self.assertIs(match.func.view_class, EmptyTileMVTView)
        self.assertEqual(match.url_name, "mvt")
        self.assertEqual(
            match.kwargs, {"nodeid": NODE_ID, "zoom": "3", "x": "4", "y": "2"}
        )

    def test_the_french_tile_url_reaches_it_too(self):
        with translation.override("fr"):
            match = resolve(f"/fr/mvt/{NODE_ID}/3/4/2.pbf")

        self.assertIs(match.func.view_class, EmptyTileMVTView)
        self.assertEqual(match.url_name, "mvt")

    def test_the_url_template_handed_to_the_map_resolves_here(self):
        template = unquote(reverse("mvt", args=(NODE_ID, "{z}", "{x}", "{y}")))

        self.assertEqual(template, f"/en/mvt/{NODE_ID}/{{z}}/{{x}}/{{y}}.pbf")
        tile = template.replace("{z}", "3").replace("{x}", "4").replace("{y}", "2")
        self.assertIs(resolve(tile).func.view_class, EmptyTileMVTView)


class TileCoordinatesTests(SimpleTestCase):
    def test_digits_inside_the_pyramid_are_a_tile(self):
        self.assertEqual(tile_coordinates("3", "7", "0"), (3, 7, 0))
        self.assertEqual(tile_coordinates("03", "4", "2"), (3, 4, 2))
        self.assertEqual(tile_coordinates("0", "0", "0"), (0, 0, 0))

    def test_anything_else_is_not(self):
        for zoom, x, y in (
            ("{z}", "{x}", "{y}"),
            ("3", "8", "0"),
            ("3", "0", "8"),
            ("31", "0", "0"),
            ("99999999999", "0", "0"),
            ("3", "1" * 5000, "0"),
            ("3", "²", "0"),
        ):
            with self.subTest(zoom=zoom, x=x, y=y):
                self.assertIsNone(tile_coordinates(zoom, x, y))


@override_settings(MVT_EMPTY_TILE_MAX_AGE=3600)
class EmptyTileMVTViewTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.factory = RequestFactory()
        self.view = EmptyTileMVTView.as_view()
        patcher = mock.patch("manuspectrum.views.mvt.MVTTiler")
        self.tiler = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.restrictions(resources=0, nodegroups=0)

    def restrictions(self, resources, nodegroups):
        for name, count in (
            ("_count_restrictions", resources),
            ("_count_nodegroup_restrictions", nodegroups),
        ):
            patcher = mock.patch(
                f"manuspectrum.views.summary_service.{name}", return_value=count
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def get(self, zoom="3", x="4", y="2", **meta):
        request = self.factory.get(f"/en/mvt/{NODE_ID}/{zoom}/{x}/{y}.pbf", **meta)
        request.user = mock.Mock(id=7)
        request.user.userprofile.viewable_nodegroups = VIEWABLE
        return self.view(request, nodeid=NODE_ID, zoom=zoom, x=x, y=y)

    def test_an_empty_cluster_tile_is_a_public_204(self):
        self.tiler.createTile.return_value = ""

        response = self.get()

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=3600")

    def test_an_empty_protobuf_tile_is_a_public_204(self):
        self.tiler.createTile.return_value = b""

        response = self.get()

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=3600")

    def test_an_empty_tile_is_private_once_a_resource_is_restricted(self):
        self.restrictions(resources=1, nodegroups=0)
        self.tiler.createTile.return_value = b""

        response = self.get()

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_an_empty_tile_is_private_once_a_nodegroup_is_restricted(self):
        self.restrictions(resources=0, nodegroups=1)
        self.tiler.createTile.return_value = ""

        response = self.get()

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_an_empty_tile_is_private_while_the_csrf_cookie_is_renewed(self):
        self.tiler.createTile.return_value = b""

        response = self.get(CSRF_COOKIE_NEEDS_UPDATE=True)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_a_tile_with_features_is_served_as_arches_serves_it(self):
        self.tiler.createTile.return_value = TILE

        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, TILE)
        self.assertEqual(response.headers["Content-Type"], "application/x-protobuf")
        self.assertNotIn("Cache-Control", response.headers)

    def test_a_node_the_reader_cannot_see_stays_a_bodyless_404(self):
        self.tiler.createTile.return_value = None

        response = self.get()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.assertNotIn("Cache-Control", response.headers)

    def test_the_tiler_gets_integer_coordinates_and_the_readers_nodegroups(self):
        self.tiler.createTile.return_value = TILE

        self.get(zoom="03", x="4", y="2")

        nodeid, viewable, user, *coordinates = self.tiler.createTile.call_args.args
        self.assertEqual(nodeid, NODE_ID)
        self.assertEqual(viewable, VIEWABLE)
        self.assertEqual(coordinates, [3, 4, 2])

    def test_the_url_template_placeholder_is_a_404_without_a_query(self):
        response = self.get(zoom="{z}", x="{x}", y="{y}")

        self.assertEqual(response.status_code, 404)
        self.tiler.createTile.assert_not_called()

    def test_coordinates_outside_the_zoom_level_are_a_404(self):
        response = self.get(zoom="3", x="8", y="0")

        self.assertEqual(response.status_code, 404)
        self.tiler.createTile.assert_not_called()

    def test_a_tiler_failure_is_not_turned_into_an_empty_tile(self):
        self.tiler.createTile.side_effect = KeyError("clusterMaxZoom")

        with self.assertRaises(KeyError):
            self.get()


class UnknownNodeOverHttpTests(TestCase):
    def test_an_unknown_node_answers_a_bodyless_404(self):
        response = self.client.get(f"/en/mvt/{uuid.uuid4()}/3/4/2.pbf")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.assertNotIn("Cache-Control", response.headers)

    def test_the_url_template_placeholder_answers_a_bodyless_404(self):
        response = self.client.get(f"/en/mvt/{uuid.uuid4()}/{{z}}/{{x}}/{{y}}.pbf")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")


@override_settings(MVT_EMPTY_TILE_MAX_AGE=3600)
class EmptyTileOverHttpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        for target, value in (
            ("manuspectrum.views.summary_service._count_restrictions", 0),
            ("manuspectrum.views.summary_service._count_nodegroup_restrictions", 0),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch("manuspectrum.views.mvt.MVTTiler")
        patcher.start().return_value.createTile.return_value = b""
        self.addCleanup(patcher.stop)

    def test_an_empty_tile_is_public_through_the_middleware(self):
        response = self.client.get(f"/en/mvt/{NODE_ID}/3/4/2.pbf")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=3600")
        self.assertNotIn("csrftoken", response.cookies)

    def test_a_malformed_csrf_cookie_gets_a_private_empty_tile(self):
        self.client.cookies["csrftoken"] = "!!"

        response = self.client.get(f"/fr/mvt/{NODE_ID}/3/4/2.pbf")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertNotIn("public", response.headers["Cache-Control"])
        self.assertIn("csrftoken", response.cookies)
