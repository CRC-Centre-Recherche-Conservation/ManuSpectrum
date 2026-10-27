"""The Explorer's internal APIs answer the Explorer page's own requests only.

Usage:
    python manage.py test tests.test_explorer_ui_only --settings="tests.test_settings"
"""

from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import resolve, reverse
from django.utils import translation

from manuspectrum.views.explorer import guard
from tests.observability_helpers import delta, headers_without_request_id
from tests.test_explorer_service import ServiceCase

UUID = "00000000-0000-4000-8000-000000000001"
PAGE = {"HTTP_SEC_FETCH_SITE": "same-origin", "HTTP_SEC_FETCH_MODE": "cors"}
ABOUT = "/about/data#reuse"
CHECKS = "manuspectrum_explorer_ui_checks_total"


def route_kwargs(name):
    return {
        "explorer-document": {"resourceid": UUID},
        "explorer-document-match": {"resourceid": UUID},
        "explorer-analysis": {"resourceid": UUID},
        "explorer-facet": {"key": "technique"},
        "api-spectrum-preview": {"file_id": UUID},
    }.get(name, {})


@override_settings(EXPLORER_UI_ONLY="enforce")
class UiOnlyTests(ServiceCase):
    URL = "/en/api/explorer/search"

    def test_a_request_without_fetch_metadata_is_refused_before_any_build(self):
        with (
            mock.patch("manuspectrum.views.explorer.api.search_payload") as build,
            mock.patch("manuspectrum.views.explorer.api._ticket") as ticket,
        ):
            with delta(CHECKS, outcome="refused", reason="absent") as counted:
                response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response["Cache-Control"], "no-store")
        build.assert_not_called()
        ticket.assert_not_called()
        body = response.json()
        self.assertEqual(body["detail"], guard.DETAIL)
        self.assertTrue(body["reuse"].startswith("http"))
        self.assertTrue(body["reuse"].endswith("/en" + ABOUT))
        self.assertEqual(response["Link"], f'<{body["reuse"]}>; rel="help"')
        self.assertEqual(counted.value, 1)

    def test_the_refusal_names_the_language_of_the_url(self):
        body = self.client.get("/fr/api/explorer/search").json()
        self.assertTrue(body["reuse"].endswith("/fr" + ABOUT))
        response = self.client.get(f"/api/spectrum-preview/{UUID}")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json()["reuse"].endswith("/en" + ABOUT))

    def test_the_page_own_request_is_answered_like_the_unguarded_route(self):
        guarded = self.client.get(self.URL, **PAGE)
        with override_settings(EXPLORER_UI_ONLY="off"):
            plain = self.client.get(self.URL)
        self.assertEqual(guarded.status_code, 200)
        self.assertEqual(guarded.content, plain.content)
        for header in ("ETag", "Cache-Control"):
            self.assertEqual(guarded[header], plain[header])
        self.assertEqual(
            [h for h in headers_without_request_id(guarded) if h[0] != "Vary"],
            [h for h in headers_without_request_id(plain) if h[0] != "Vary"],
        )

    def test_guarded_answers_vary_on_the_fetch_metadata_headers(self):
        accepted = self.client.get(self.URL, **PAGE)
        refused = self.client.get(self.URL)
        for response in (accepted, refused):
            vary = [v.strip() for v in response["Vary"].split(",")]
            self.assertIn("Sec-Fetch-Site", vary)
            self.assertIn("Sec-Fetch-Mode", vary)
        gzipped = self.client.get(self.URL, HTTP_ACCEPT_ENCODING="gzip", **PAGE)
        vary = [v.strip() for v in gzipped["Vary"].split(",")]
        self.assertIn("Accept-Encoding", vary)
        self.assertIn("Sec-Fetch-Site", vary)

    @override_settings(EXPLORER_UI_ONLY="off")
    def test_off_adds_no_vary_of_its_own(self):
        response = self.client.get(self.URL)
        self.assertNotIn("Sec-Fetch-Site", response.get("Vary", ""))

    def test_a_browser_without_fetch_metadata_is_answered_from_a_page_of_the_site(self):
        referer = "http://testserver/en/discover"
        with delta(CHECKS, outcome="accepted", reason="referer") as counted:
            response = self.client.get(self.URL, HTTP_REFERER=referer)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(counted.value, 1)

    def test_the_referer_fallback_needs_this_site_and_no_fetch_metadata(self):
        cases = [
            ("http://elsewhere.example/en/discover", {}),
            ("not a url", {}),
            ("", {}),
            ("https://testserver/en/discover", {}),
            (
                "http://testserver/en/discover",
                {"HTTP_SEC_FETCH_SITE": "cross-site", "HTTP_SEC_FETCH_MODE": "cors"},
            ),
        ]
        for referer, headers in cases:
            with self.subTest(referer=referer, headers=headers):
                response = self.client.get(self.URL, HTTP_REFERER=referer, **headers)
                self.assertEqual(response.status_code, 403)

    @override_settings(PUBLIC_SERVER_ADDRESS="https://testserver/")
    def test_the_referer_scheme_is_the_public_one_behind_the_proxy(self):
        response = self.client.get(
            self.URL, HTTP_REFERER="https://testserver/en/discover"
        )
        self.assertEqual(response.status_code, 200)

    def test_a_revalidation_of_the_page_passes(self):
        first = self.client.get(self.URL, **PAGE)
        again = self.client.get(self.URL, HTTP_IF_NONE_MATCH=first["ETag"], **PAGE)
        self.assertEqual(again.status_code, 304)

    def test_each_foreign_origin_is_refused_with_its_reason(self):
        cases = [
            (
                "cross_site",
                {"HTTP_SEC_FETCH_SITE": "cross-site", "HTTP_SEC_FETCH_MODE": "cors"},
            ),
            (
                "same_site",
                {"HTTP_SEC_FETCH_SITE": "same-site", "HTTP_SEC_FETCH_MODE": "cors"},
            ),
            (
                "navigate",
                {"HTTP_SEC_FETCH_SITE": "none", "HTTP_SEC_FETCH_MODE": "navigate"},
            ),
            ("other", {"HTTP_SEC_FETCH_SITE": "none"}),
            (
                "navigate",
                {
                    "HTTP_SEC_FETCH_SITE": "same-origin",
                    "HTTP_SEC_FETCH_MODE": "navigate",
                },
            ),
            (
                "other",
                {
                    "HTTP_SEC_FETCH_SITE": "same-origin",
                    "HTTP_SEC_FETCH_MODE": "no-cors",
                },
            ),
            (
                "other",
                {"HTTP_SEC_FETCH_SITE": "made-up", "HTTP_SEC_FETCH_MODE": "cors"},
            ),
        ]
        for reason, headers in cases:
            with self.subTest(reason=reason, headers=headers):
                with delta(CHECKS, outcome="refused", reason=reason) as counted:
                    response = self.client.get(self.URL, **headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(counted.value, 1)

    def test_a_signed_in_reader_without_the_headers_is_refused_too(self):
        self.client.force_login(User.objects.create_user("reader"))
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_the_page_request_is_counted_accepted(self):
        with delta(CHECKS, outcome="accepted", reason="same_origin") as counted:
            self.client.get(self.URL, **PAGE)
        self.assertEqual(counted.value, 1)

    @override_settings(EXPLORER_UI_ONLY="observe")
    def test_observe_answers_and_counts(self):
        with delta(CHECKS, outcome="observed", reason="absent") as counted:
            response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(counted.value, 1)

    @override_settings(EXPLORER_UI_ONLY="off")
    def test_off_checks_and_counts_nothing(self):
        with delta(CHECKS, outcome="refused", reason="absent") as counted:
            response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(counted.value, 0)

    @override_settings(EXPLORER_UI_ONLY="on")
    def test_an_unknown_mode_is_a_configuration_error(self):
        with self.assertRaises(ImproperlyConfigured):
            self.client.get(self.URL, **PAGE)

    def test_every_listed_route_resolves_to_a_guarded_view(self):
        for name in guard.UI_ONLY_ROUTES:
            with self.subTest(route=name), translation.override("en"):
                path = reverse(name, kwargs=route_kwargs(name))
                view = resolve(path).func.view_class
                self.assertTrue(getattr(view.dispatch, "ui_only", False))
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_the_products_meant_for_reuse_are_not_refused(self):
        paths = [
            "/api/explorer/export",
            "/api/explorer/series.csv",
            "/api/explorer/events.csv",
            "/api/explorer/events.geojson",
            "/iiif/v3/explorer-manifest",
            f"/iiif/v3/annotation-collection/{UUID}",
            f"/iiif/v3/annotation/{UUID}",
            f"/iiif/data/{UUID}/raw",
            "/iiif/context/xy-reading/1.jsonld",
            "/iiif/auth/login",
            "/api/site-notice",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertNotEqual(response.status_code, 403)
                self.assertNotIn("#reuse", response.get("Link", ""))

    def test_the_spectrum_preview_is_refused_before_any_read(self):
        with (
            mock.patch("manuspectrum.views.spectrum_preview.read_series") as read,
            mock.patch("manuspectrum.views.spectrum_preview.get_or_build") as build,
            mock.patch("manuspectrum.views.spectrum_preview.file_allowed") as allowed,
        ):
            response = self.client.get(f"/api/spectrum-preview/{UUID}")
        self.assertEqual(response.status_code, 403)
        read.assert_not_called()
        build.assert_not_called()
        allowed.assert_not_called()

    def test_the_reuse_page_renders_in_both_languages_and_is_linked_in_the_footer(self):
        for code, title in (("en", "Reuse the data"), ("fr", "Réutiliser les données")):
            with self.subTest(language=code):
                response = self.client.get(f"/{code}/about/data")
                self.assertEqual(response.status_code, 200)
                page = response.content.decode()
                self.assertIn('id="reuse"', page)
                self.assertIn(title, page)
                self.assertIn(f'href="/{code}/about/data"', page)
                self.assertIn("/{lang}/api/explorer/", page)
        self.assertNotIn(
            "/api/explorer/*", self.client.get("/en/about/data").content.decode()
        )

    def test_the_reuse_page_loads_the_script_of_the_other_public_pages(self):
        page = self.client.get("/en/about/data").content.decode()
        self.assertIn("pages/team", page)

    def test_the_explorer_about_page_no_longer_holds_the_reuse_section(self):
        page = self.client.get("/en/about/explorer").content.decode()
        self.assertNotIn('id="reuse"', page)

    def test_the_series_csv_line_names_the_selection_and_the_per_file_route(self):
        page = self.client.get("/en/about/data").content.decode()
        self.assertIn("/iiif/data/{file}/series.csv", page)

    def test_the_reuse_page_documents_the_products_the_refusal_points_to(self):
        page = self.client.get("/en/about/data").content.decode()
        self.assertIn('id="reuse"', page)
        for name in (
            "explorer-export",
            "iiif-v3-explorer-manifest",
            "explorer-series-csv",
            "explorer-events-csv",
        ):
            with translation.override("en"):
                self.assertIn(reverse(name), page)
