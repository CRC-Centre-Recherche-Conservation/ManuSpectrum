"""The ``/iiif/v3|v2/annotation-collection|annotation`` routes: URLs, numbering, ids, statuses, CORS.

Usage:
    python manage.py test tests.test_iiif_routes --settings=tests.test_settings
"""

import json
import subprocess
import sys
import uuid
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import resolve, reverse

from manuspectrum.iiif import ids
from tests.explorer_fixtures import CANVAS, FEATURES, IIIFCase

UNKNOWN = "00000000-0000-4000-8000-00000000000b"
BASE = settings.PUBLIC_SERVER_ADDRESS
ROUTE_NAMES = (
    "iiif-v3-annotation-collection",
    "iiif-v3-annotation-page",
    "iiif-v3-annotation",
    "iiif-v3-annotation-zone",
    "iiif-v2-annotation-collection",
    "iiif-v2-annotation-page",
    "iiif-v2-annotation",
    "iiif-v2-annotation-zone",
    "iiif-v3-characterization-collection",
    "iiif-v3-characterization-page",
    "iiif-v2-characterization-collection",
    "iiif-v2-characterization-page",
    "iiif-data-raw",
    "iiif-data-series",
    "iiif-xy-reading-context",
    "iiif-xy-reading-doc",
    "iiif-xy-reading-schema",
)


def path_of(url):
    return "/" + url[len(BASE) :]


class RouteCase(IIIFCase):
    def setUp(self):
        super().setUp()
        self.visitor = Client()

    def doc(self):
        return str(self.documents["open"].pk)

    def get(self, url, **headers):
        return self.visitor.get(url, **headers)


class LegacyUrlTests(RouteCase):
    def test_the_legacy_urls_still_answer(self):
        doc, analysis = self.doc(), str(self.analyses["open"].pk)
        expected = {
            ("iiif-v3-annotation-collection", (doc,)): 200,
            ("iiif-v3-annotation-page", (doc, 1)): 200,
            ("iiif-v3-annotation", (analysis,)): 200,
            ("iiif-v2-annotation-collection", (doc,)): 200,
            ("iiif-v2-annotation-page", (doc, 1)): 200,
            ("iiif-v2-annotation", (analysis,)): 200,
            ("iiif-v3-annotation-collection", (UNKNOWN,)): 404,
            ("iiif-v3-annotation", (UNKNOWN,)): 404,
        }
        for (name, args), status in expected.items():
            url = reverse(name, args=args)
            with self.subTest(name=name, url=url):
                self.assertTrue(url.startswith("/iiif/v"))
                self.assertEqual(self.get(url).status_code, status)

    def test_every_minted_url_resolves_to_its_route(self):
        doc, analysis, feature = (
            self.doc(),
            str(self.analyses["open"].pk),
            FEATURES["open"],
        )
        for version in (3, 2):
            for url, name in (
                (ids.collection(doc, version=version), "annotation-collection"),
                (ids.page(doc, 3, version=version), "annotation-page"),
                (ids.annotation_first(analysis, version), "annotation"),
                (ids.annotation(analysis, feature, version), "annotation-zone"),
                (
                    ids.collection(doc, "characterization", version),
                    "characterization-collection",
                ),
                (
                    ids.page(doc, 3, "characterization", version),
                    "characterization-page",
                ),
            ):
                with self.subTest(url=url):
                    self.assertEqual(
                        resolve(path_of(url.split("?")[0])).url_name,
                        f"iiif-v{version}-{name}",
                    )
        for url, name in (
            (ids.data_raw(feature), "iiif-data-raw"),
            (ids.data_series(feature), "iiif-data-series"),
            (ids.xy_context(), "iiif-xy-reading-context"),
            (ids.xy_doc(), "iiif-xy-reading-doc"),
            (ids.xy_schema(), "iiif-xy-reading-schema"),
        ):
            with self.subTest(url=url):
                self.assertEqual(resolve(path_of(url)).url_name, name)

    def test_the_routes_are_language_neutral(self):
        for name in ROUTE_NAMES:
            with self.subTest(name=name):
                self.assertFalse(
                    reverse(name, args=self._args(name)).startswith(("/en/", "/fr/"))
                )

    def _args(self, name):
        if name.startswith("iiif-xy-reading"):
            return ()
        if name.startswith("iiif-data"):
            return (FEATURES["open"],)
        if name.endswith("page"):
            return (self.doc(), 1)
        if name.endswith("zone"):
            return (self.doc(), FEATURES["open"])
        return (self.doc(),)

    def test_the_middleware_installs_the_arches_anonymous_row_on_the_request(self):
        response = self.get(f"/iiif/v3/annotation-collection/{UNKNOWN}")

        self.assertEqual(response.wsgi_request.user.username, "anonymous")

    def test_an_unknown_id_is_a_bodyless_404(self):
        for url in (
            f"/iiif/v3/annotation-collection/{UNKNOWN}",
            f"/iiif/v3/annotation-collection/{UNKNOWN}/page-1",
            f"/iiif/v2/annotation-collection/{UNKNOWN}",
            f"/iiif/v3/annotation/{UNKNOWN}",
            f"/iiif/v2/annotation/{UNKNOWN}/{UNKNOWN}",
        ):
            with self.subTest(url=url):
                response = self.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, b"")
                self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_a_document_is_not_an_annotation(self):
        self.assertEqual(self.get(f"/iiif/v3/annotation/{self.doc()}").status_code, 404)

    def test_an_analysis_is_not_a_collection(self):
        analysis = self.analyses["open"].pk
        self.assertEqual(
            self.get(f"/iiif/v3/annotation-collection/{analysis}").status_code, 404
        )

    def test_unexpected_errors_are_not_echoed(self):
        secret = "postgres://user:hunter2@db/manuspectrum"
        with (
            mock.patch(
                "manuspectrum.iiif.facts.document_facts",
                side_effect=RuntimeError(secret),
            ),
            self.assertLogs(
                "manuspectrum.views.iiif.annotations", level="ERROR"
            ) as logs,
        ):
            response = self.get(f"/iiif/v3/annotation-collection/{self.doc()}")

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(secret, response.content.decode())
        self.assertTrue(any(secret in line for line in logs.output))


class PageNumberTests(RouteCase):
    def test_page_numbers_are_canvas_positions(self):
        collection = self.get(f"/iiif/v3/annotation-collection/{self.doc()}").json()

        self.assertEqual(collection["first"]["id"], ids.page(self.doc(), 1))
        self.assertEqual(collection["last"]["id"], ids.page(self.doc(), 3))
        self.assertEqual(collection["total"], 4)
        first = self.get(f"/iiif/v3/annotation-collection/{self.doc()}/page-1").json()
        self.assertEqual(len(first["items"]), 3)
        self.assertEqual(first["next"]["id"], ids.page(self.doc(), 3))
        self.assertNotIn("prev", first)

    def test_page_numbers_do_not_depend_on_the_process(self):
        script = (
            "import os, django; os.environ['DJANGO_SETTINGS_MODULE']='tests.test_settings';"
            "django.setup();"
            "from manuspectrum.iiif import pages;"
            "from manuspectrum.iiif.facts import DocumentFacts, AnalysisFact, Zone;"
            "z=Zone('f', 'c2', 2, None);"
            "a=AnalysisFact('a', {}, (z,), (), (), {}, {}, {}, {}, {}, {}, {}, {}, None, False);"
            "d=DocumentFacts('d', {}, None, ('c1','c2'), ('1','2'), (a,));"
            "print(pages.page_numbers(d))"
        )
        runs = {
            subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                cwd=Path(settings.APP_ROOT).parent,
                env={**__import__("os").environ, "PYTHONHASHSEED": seed},
                timeout=300,
            )
            .stdout.strip()
            .splitlines()[-1]
            for seed in ("1", "2")
        }
        self.assertEqual(runs, {"[2]"})

    def test_an_empty_canvas_has_an_empty_page(self):
        page = self.get(f"/iiif/v3/annotation-collection/{self.doc()}/page-2").json()

        self.assertEqual(page["items"], [])
        self.assertEqual(page["prev"]["id"], ids.page(self.doc(), 1))
        self.assertEqual(page["next"]["id"], ids.page(self.doc(), 3))

    def test_a_page_out_of_range_is_404(self):
        for n in (0, 4, 5172):
            with self.subTest(n=n):
                self.assertEqual(
                    self.get(
                        f"/iiif/v3/annotation-collection/{self.doc()}/page-{n}"
                    ).status_code,
                    404,
                )

    def test_a_document_without_manifest_has_an_empty_collection(self):
        from arches.app.models.models import TileModel

        node = self.nodes[("document", "facsimiles")]
        TileModel.objects.filter(nodegroup_id=node.nodegroup_id).delete()
        cache.clear()

        response = self.get(f"/iiif/v3/annotation-collection/{self.doc()}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("total", response.json())
        self.assertEqual(
            self.get(f"/iiif/v3/annotation-collection/{self.doc()}/page-1").status_code,
            404,
        )

    def test_a_component_collection_numbers_the_pages_of_its_document(self):
        component = self.components["open"].pk
        collection = self.get(f"/iiif/v3/annotation-collection/{component}").json()

        self.assertEqual(collection["total"], 2)
        page = self.get(f"/iiif/v3/annotation-collection/{component}/page-1").json()
        self.assertEqual(
            sorted(a["id"] for a in page["items"]),
            sorted(
                ids.annotation(self.analyses[k].pk, FEATURES[k])
                for k in ("open", "draft")
            ),
        )


class AnnotationIdTests(RouteCase):
    def test_annotation_ids_are_unique_per_zone(self):
        page = self.get(f"/iiif/v3/annotation-collection/{self.doc()}/page-1").json()
        found = [a["id"] for a in page["items"]]

        self.assertEqual(len(found), len(set(found)))
        self.assertIn(
            ids.annotation(self.analyses["on_document"].pk, FEATURES["on_document_1"]),
            found,
        )

    def test_the_zone_url_dereferences_its_annotation(self):
        analysis = self.analyses["on_document"].pk
        for key in ("on_document_1", "on_document_3"):
            with self.subTest(key=key):
                url = ids.annotation(analysis, FEATURES[key])
                response = self.get(path_of(url))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["id"], url)

    def test_the_first_zone_url_answers_the_per_zone_id(self):
        analysis = self.analyses["on_document"].pk
        annotation = self.get(f"/iiif/v3/annotation/{analysis}").json()

        self.assertEqual(
            annotation["id"], ids.annotation(analysis, FEATURES["on_document_1"])
        )

    def test_a_feature_of_another_analysis_is_404(self):
        analysis = self.analyses["open"].pk
        other = FEATURES["on_document_3"]

        self.assertEqual(
            self.get(f"/iiif/v3/annotation/{analysis}/{other}").status_code, 404
        )
        self.assertEqual(
            self.get(f"/iiif/v2/annotation/{analysis}/{other}").status_code, 404
        )

    def test_an_analysis_without_a_located_zone_is_404(self):
        analysis = self.analyses["open"]
        from arches.app.models.models import TileModel

        node = self.nodes[("analysis", "literal_location_of_analysis")]
        TileModel.objects.filter(
            resourceinstance=analysis, nodegroup_id=node.nodegroup_id
        ).delete()
        cache.clear()

        self.assertEqual(
            self.get(f"/iiif/v3/annotation/{analysis.pk}").status_code, 404
        )


class OnlyFilterTests(RouteCase):
    def url(self, only, n=1):
        return f"/iiif/v3/annotation-collection/{self.doc()}/page-{n}?only={only}"

    def test_the_only_filter_keeps_the_named_analyses(self):
        kept = str(self.analyses["open"].pk)
        page = self.get(self.url(kept)).json()

        self.assertEqual(
            [a["id"] for a in page["items"]], [ids.annotation(kept, FEATURES["open"])]
        )
        self.assertEqual(page["id"], ids.page(self.doc(), 1, only={kept}))
        self.assertNotIn("next", page)
        self.assertNotIn("prev", page)
        self.assertEqual(page["partOf"][0]["id"], ids.collection(self.doc()))

    @override_settings(IIIF_PAGE_FILTER_MAX=2)
    def test_only_over_the_limit_is_400(self):
        three = ",".join(str(uuid.uuid4()) for _ in range(3))

        self.assertEqual(self.get(self.url(three)).status_code, 400)

    def test_a_malformed_only_is_400(self):
        for only in ("nope", "", f"{UNKNOWN},x"):
            with self.subTest(only=only):
                self.assertEqual(self.get(self.url(only)).status_code, 400)


class CacheHeaderTests(RouteCase):
    def test_the_visitor_page_is_public_no_cache_with_a_strong_etag(self):
        url = f"/iiif/v3/annotation-collection/{self.doc()}/page-1"
        first = self.get(url)
        again = self.get(url)

        self.assertEqual(first["Cache-Control"], "public, no-cache")
        self.assertRegex(first["ETag"], r'^"[0-9a-f]{40}"$')
        self.assertEqual(again["ETag"], first["ETag"])
        self.assertEqual(again.content, first.content)
        revalidated = self.get(url, HTTP_IF_NONE_MATCH=first["ETag"])
        self.assertEqual(revalidated.status_code, 304)

    def test_an_embargoed_document_is_404_and_leaves_no_memo(self):
        self.embargo(self.documents["open"])
        cache.clear()

        response = self.get(f"/iiif/v3/annotation-collection/{self.doc()}")

        self.assertEqual(response.status_code, 404)
        self.assertFalse([k for k in cache._cache if ":iiif:" in k])

    def test_a_memo_entry_is_never_served_to_a_refused_reader(self):
        url = f"/iiif/v3/annotation-collection/{self.doc()}"
        self.assertEqual(self.get(url).status_code, 200)
        self.embargo(self.documents["open"])

        response = self.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_the_media_types_are_the_iiif_profiles(self):
        v3 = self.get(f"/iiif/v3/annotation-collection/{self.doc()}")
        v2 = self.get(f"/iiif/v2/annotation-collection/{self.doc()}")

        self.assertEqual(
            v3["Content-Type"],
            'application/ld+json;profile="http://iiif.io/api/presentation/3/context.json"',
        )
        self.assertEqual(
            v2["Content-Type"],
            'application/ld+json;profile="http://iiif.io/api/presentation/2/context.json"',
        )


class CorsTests(RouteCase):
    def assert_cors(self, response):
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("ETag", response["Access-Control-Expose-Headers"])
        self.assertIn("WWW-Authenticate", response["Access-Control-Expose-Headers"])
        self.assertNotIn("Access-Control-Allow-Credentials", response)
        vary = response["Vary"].lower()
        self.assertIn("authorization", vary)
        self.assertIn("cookie", vary)

    def test_cors_headers_are_set_on_errors_too(self):
        for allow_all in (False, True):
            with (
                self.subTest(allow_all=allow_all),
                override_settings(CORS_ALLOW_ALL_ORIGINS=allow_all),
            ):
                for url in (
                    f"/iiif/v3/annotation-collection/{self.doc()}",
                    f"/iiif/v3/annotation-collection/{UNKNOWN}",
                    f"/iiif/v3/annotation-collection/{self.doc()}/page-9",
                    f"/iiif/v3/annotation-collection/{self.doc()}/page-1?only=x",
                ):
                    self.assert_cors(
                        self.get(url, HTTP_ORIGIN="https://viewer.example")
                    )

    def test_a_preflight_allows_authorization_without_credentials(self):
        for config in (
            {"CORS_ALLOW_ALL_ORIGINS": True},
            {"CORS_ALLOW_ALL_ORIGINS": False, "CORS_URLS_REGEX": r"^(?!/iiif/).*$"},
        ):
            with self.subTest(**config), override_settings(**config):
                response = self.visitor.options(
                    f"/iiif/v3/annotation/{self.analyses['open'].pk}",
                    HTTP_ORIGIN="https://viewer.example",
                    HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
                    HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization",
                )
                self.assertLess(response.status_code, 300)
                self.assertEqual(response["Access-Control-Allow-Origin"], "*")
                self.assertIn(
                    "authorization", response["Access-Control-Allow-Headers"].lower()
                )
                self.assertIn("GET", response["Access-Control-Allow-Methods"])
                self.assertNotIn("Access-Control-Allow-Credentials", response)

    def test_a_write_is_not_allowed(self):
        response = self.visitor.post(f"/iiif/v3/annotation-collection/{self.doc()}")

        self.assertEqual(response.status_code, 405)


class ContentTests(RouteCase):
    def test_a_zone_stored_under_the_image_service_targets_the_canvas(self):
        service = "https://example.org/iiif/image/f2r"
        manifest = json.loads(json.dumps(self.fetch.side_effect(self.fetch_url())))
        manifest["items"][1]["items"] = [
            {
                "id": "https://example.org/p",
                "type": "AnnotationPage",
                "items": [
                    {
                        "id": "https://example.org/p/a",
                        "type": "Annotation",
                        "motivation": "painting",
                        "target": manifest["items"][1]["id"],
                        "body": {
                            "id": f"{service}/full/max/0/default.jpg",
                            "type": "Image",
                            "service": [
                                {
                                    "id": service,
                                    "type": "ImageService3",
                                    "profile": "level1",
                                }
                            ],
                        },
                    }
                ],
            }
        ]
        self.fetch.side_effect = lambda url: manifest
        feature = str(uuid.uuid4())
        self.zone(
            self.analyses["open"],
            [(feature, service, {"type": "Point", "coordinates": [10, -20]})],
        )
        cache.clear()

        annotation = self.get(
            f"/iiif/v3/annotation/{self.analyses['open'].pk}/{feature}"
        )

        self.assertEqual(annotation.status_code, 200)
        self.assertEqual(
            annotation.json()["target"]["source"]["id"], manifest["items"][1]["id"]
        )
        self.assertEqual(
            self.get(f"/iiif/v3/annotation-collection/{self.doc()}/page-2").json()[
                "items"
            ][0]["id"],
            ids.annotation(self.analyses["open"].pk, feature),
        )

    def fetch_url(self):
        from tests.explorer_fixtures import MANIFEST

        return MANIFEST

    def test_the_target_names_the_document_manifest(self):
        annotation = self.get(f"/iiif/v3/annotation/{self.analyses['open'].pk}").json()

        self.assertEqual(annotation["target"]["source"]["id"], CANVAS)
        self.assertEqual(
            annotation["target"]["source"]["partOf"],
            [{"id": self.fetch_url(), "type": "Manifest"}],
        )
