import re
from unittest import mock

from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase, override_settings

from manuspectrum.utils.public_visibility import anonymous_user
from manuspectrum.views.explorer.service import search_payload
from tests.explorer_fixtures import ExplorerCase

NOSCRIPT = re.compile(r"<noscript>(.*?)</noscript>", re.S)


def _technique_facet_values_for_visitor():
    payload = search_payload(QueryDict("grain=analyses"), anonymous_user(), "en")
    facet = next(
        (f for f in payload["facets"] if f["key"] == "technique"), {"values": []}
    )
    return [v for v in facet["values"] if v["count"] > 0]


def noscript_blocks(html):
    return NOSCRIPT.findall(html)


class RevealFallbackTests(TestCase):
    def test_homepage_keeps_only_the_header_noscript(self):
        html = self.client.get("/en/").content.decode()
        self.assertFalse(any(".reveal" in block for block in noscript_blocks(html)))
        self.assertEqual(html.count("<noscript>"), 1)

    def test_about_page_has_no_reveal_noscript(self):
        html = self.client.get("/en/about/team").content.decode()
        self.assertFalse(any(".reveal" in block for block in noscript_blocks(html)))

    @override_settings(DEBUG=False)
    def test_error_page_has_no_reveal_noscript(self):
        resp = self.client.get("/this-page-does-not-exist")
        self.assertEqual(resp.status_code, 404)
        html = resp.content.decode()
        self.assertFalse(any(".reveal" in block for block in noscript_blocks(html)))


SCRIPT_SRC = re.compile(r"<script\b[^>]*\bsrc=[^>]*>")


class ScriptLoadingTests(TestCase):
    def test_bundle_scripts_are_deferred_in_the_head(self):
        html = self.client.get("/en/").content.decode()
        head, body = html.split("</head>", 1)
        self.assertEqual(SCRIPT_SRC.findall(body), [])
        tags = SCRIPT_SRC.findall(head)
        self.assertTrue(tags)
        for tag in tags:
            self.assertRegex(tag, r"\sdefer[\s>]")


class AnalysisPopupTests(TestCase):
    def test_four_popups_are_rendered_hidden(self):
        html = self.client.get("/en/").content.decode()
        self.assertEqual(html.count('id="ms-analysis-popup-'), 4)
        for n in range(1, 5):
            self.assertRegex(
                html, rf'<div class="[^"]*" id="ms-analysis-popup-{n}" hidden>'
            )
            self.assertIn(f'aria-controls="ms-analysis-popup-{n}"', html)

    def test_popups_are_translated(self):
        html = self.client.get("/fr/").content.decode()
        self.assertIn("Vermillon (HgS)", html)
        self.assertIn("Encre ferrogallique", html)


class LogoDialogTests(TestCase):
    def test_zoom_is_a_labelled_dialog(self):
        html = self.client.get("/en/").content.decode()
        self.assertRegex(
            html,
            r'<dialog class="ms-logo-dialog" id="ms-logo-dialog" aria-labelledby="ms-logo-dialog-title">',
        )
        self.assertIn('id="ms-logo-dialog-title"', html)
        self.assertNotIn('class="ms-logo-overlay"', html)
        self.assertRegex(
            html, r'<button type="button" class="ms-logo-zoom-btn" id="ms-logo-zoom"'
        )


class ArchesPayloadTests(TestCase):
    def test_homepage_carries_no_arches_payload(self):
        for lang in ("en", "fr"):
            html = self.client.get(f"/{lang}/").content.decode()
            for marker in ("arches-translations", "arches-urls", "CKEDITOR_BASEPATH"):
                self.assertNotIn(marker, html, f"{marker} on /{lang}/")


class DiscoverEntryTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_search_form_has_a_default_submit_then_the_discover_button(self):
        html = self.client.get("/en/").content.decode()
        form = html[
            html.index('id="ms-search-form"') : html.index(
                "</form>", html.index('id="ms-search-form"')
            )
        ]
        buttons = re.findall(r"<button[^>]*>", form)
        self.assertEqual(len(buttons), 2)
        self.assertNotIn("formaction", buttons[0])
        self.assertIn('formaction="/en/discover"', buttons[1])

    def test_technique_chips_link_each_visible_technique_by_its_thesaurus_reference(
        self,
    ):
        techniques = [
            {
                "id": "http://example.org/technique/a",
                "label": {"value": "Technique A", "lang": "fr"},
                "count": 3,
            },
        ]
        with mock.patch(
            "manuspectrum.templatetags.explorer_home.homepage_techniques",
            return_value=techniques,
        ):
            html = self.client.get("/fr/").content.decode()
        self.assertIn(
            'class="ms-search-chip ms-technique-chip" lang="fr" '
            'href="/fr/discover?grain=analyses&amp;technique=http%3A%2F%2Fexample.org%2Ftechnique%2Fa"',
            html,
        )
        self.assertNotIn('data-term="Raman"', html)
        self.assertNotIn('data-term="XRF"', html)

    def test_no_technique_chip_row_without_visible_techniques(self):
        with mock.patch(
            "manuspectrum.templatetags.explorer_home.homepage_techniques",
            return_value=[],
        ):
            html = self.client.get("/fr/").content.decode()
        self.assertNotIn("ms-technique-chips", html)

    def test_homepage_survives_a_failing_explorer_search(self):
        with (
            mock.patch(
                "manuspectrum.views.explorer.home.search_payload",
                side_effect=RuntimeError("broken facet"),
            ) as search,
            self.assertLogs("manuspectrum.views.explorer.home", "ERROR"),
        ):
            response = self.client.get("/en/")
            self.client.get("/en/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("ms-technique-chips", response.content.decode())
        self.assertEqual(search.call_count, 2)

    def test_header_offers_the_explorer_on_every_public_page(self):
        for path in ("/en/", "/en/about/team", "/en/discover"):
            html = self.client.get(path).content.decode()
            self.assertIn('href="/en/discover"', html, path)
            if path != "/en/discover":
                self.assertNotIn('href="/en/discover" aria-current="page"', html, path)


class HomepageTechniquesTests(ExplorerCase):
    """The list comes from the Explorer facet for the visitor; nothing is hard-coded."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tile(
            cls.analyses["open"],
            "analysis_technique_used",
            cls.reference_value(
                "http://example.org/technique/fixture",
                "Fixture technique",
                "Technique de test",
            ),
        )

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_only_techniques_with_visible_analyses_are_listed(self):
        from manuspectrum.views.explorer.home import homepage_techniques

        facet = {
            "key": "technique",
            "values": [
                {
                    "id": "http://example.org/technique/a",
                    "label": {"value": "A", "lang": "en"},
                    "count": 2,
                    "selected": False,
                },
                {
                    "id": "http://example.org/technique/b",
                    "label": {"value": "B", "lang": "en"},
                    "count": 0,
                    "selected": False,
                },
            ],
        }
        with mock.patch(
            "manuspectrum.views.explorer.home.search_payload",
            return_value={"facets": [facet]},
        ) as search:
            listed = homepage_techniques("en")
        self.assertEqual([t["id"] for t in listed], ["http://example.org/technique/a"])
        self.assertEqual(search.call_args.args[1].username, "anonymous")
        self.assertEqual(search.call_args.args[0].get("grain"), "analyses")

    def test_the_list_follows_the_real_facet_of_the_fixture(self):
        from manuspectrum.views.explorer.home import homepage_techniques

        listed = homepage_techniques("en")
        uris = {t["id"] for t in listed}
        self.assertIn("http://example.org/technique/fixture", uris)
        self.assertTrue(all(t["count"] > 0 for t in listed))
        self.assertEqual(
            uris, {row["id"] for row in _technique_facet_values_for_visitor()}
        )

    def test_the_list_is_memoised_per_language(self):
        from manuspectrum.views.explorer.home import homepage_techniques

        with mock.patch(
            "manuspectrum.views.explorer.home.search_payload",
            return_value={"facets": []},
        ) as search:
            homepage_techniques("en")
            homepage_techniques("en")
            homepage_techniques("fr")
        self.assertEqual(search.call_count, 2)
