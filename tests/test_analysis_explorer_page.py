import json
import re

from django.test import TestCase, override_settings
from django.urls import reverse

JSON_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


class AnalysisExplorerPageTests(TestCase):
    def test_page_renders_in_both_languages_with_both_labels(self):
        for lang, title in (
            ("en", "Analysis explorer"),
            ("fr", "Explorateur d'analyses"),
        ):
            response = self.client.get(f"/{lang}/discover")
            self.assertEqual(response.status_code, 200, lang)
            html = response.content.decode()
            self.assertIn(title, html, lang)
            self.assertIn('id="ms-explorer-app"', html, lang)

    def test_bare_path_redirects_to_a_language(self):
        response = self.client.get("/discover")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("/en/discover"))

    def test_canonical_never_carries_the_query(self):
        html = self.client.get(reverse("analysis-explorer") + "?q=XRF").content.decode()
        self.assertRegex(html, r'<link rel="canonical" href="[^"?]*/en/discover">')

    def test_noindex_only_with_a_query(self):
        plain = self.client.get(reverse("analysis-explorer")).content.decode()
        queried = self.client.get(
            reverse("analysis-explorer") + "?q=XRF"
        ).content.decode()
        self.assertNotIn('name="robots"', plain)
        self.assertIn('<meta name="robots" content="noindex, follow">', queried)

    def test_hreflang_alternates_point_at_both_languages(self):
        html = self.client.get(reverse("analysis-explorer")).content.decode()
        self.assertIn('hreflang="fr" href="http://testserver/fr/discover"', html)
        self.assertIn('hreflang="en" href="http://testserver/en/discover"', html)

    def test_json_ld_parses(self):
        html = self.client.get(reverse("analysis-explorer")).content.decode()
        blocks = JSON_LD.findall(html)
        self.assertTrue(blocks)
        for block in blocks:
            json.loads(block)

    @override_settings(EXPLORER_MIRADOR_URL="https://viewer.example/mirador/?a=1&b=2")
    def test_mount_point_carries_the_mirador_viewer_address(self):
        page = self.client.get(reverse("analysis-explorer")).content.decode()
        self.assertIn(
            'data-mirador-url="https://viewer.example/mirador/?a=1&amp;b=2"', page
        )

    @override_settings(EXPLORER_MIRADOR_URL="")
    def test_mount_point_has_no_mirador_viewer_without_the_setting(self):
        page = self.client.get(reverse("analysis-explorer")).content.decode()
        self.assertNotIn("data-mirador-url", page)

    @override_settings(EXPLORER_MIRADOR_URL="javascript:alert(1)")
    def test_a_mirador_setting_that_is_not_a_web_address_is_ignored(self):
        page = self.client.get(reverse("analysis-explorer")).content.decode()
        self.assertNotIn("data-mirador-url", page)

    def test_page_is_never_stored_by_a_shared_cache(self):
        cache_control = self.client.get(reverse("analysis-explorer"))["Cache-Control"]
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)

    def test_page_drops_the_arches_payload_other_pages_keep_it(self):
        explorer = self.client.get(reverse("analysis-explorer")).content.decode()
        team = self.client.get(reverse("about-team")).content.decode()
        self.assertNotIn("arches-translations", explorer)
        self.assertIn("arches-translations", team)

    def test_body_class_marks_the_app_and_stays_default_elsewhere(self):
        explorer = self.client.get(reverse("analysis-explorer")).content.decode()
        team = self.client.get(reverse("about-team")).content.decode()
        self.assertIn('<body class="ms-page ms-page--app">', explorer)
        self.assertIn('<body class="ms-page">', team)

    def test_fallback_and_noscript_are_rendered(self):
        html = self.client.get(reverse("analysis-explorer")).content.decode()
        self.assertIn('id="ms-explorer-fallback"', html)
        self.assertRegex(html, r'id="ms-explorer-fallback"[^>]*hidden')
        self.assertIn("<noscript>", html)

    def test_scripts_and_styles_of_the_page_are_loaded(self):
        html = self.client.get(reverse("analysis-explorer")).content.decode()
        self.assertRegex(
            html,
            r'<script src="[^"]*/js/views/pages/analysis-explorer\.\w+\.js"\s+defer></script>',
        )
        self.assertRegex(
            html, r'<link href="[^"]*/css/explorer\.\w+\.css" rel="stylesheet" />'
        )

    def test_header_tab_is_current_on_the_page(self):
        html = self.client.get(reverse("analysis-explorer")).content.decode()
        self.assertEqual(
            html.count(f'href="{reverse("analysis-explorer")}" aria-current="page"'), 1
        )
        self.assertIn(
            f'href="{reverse("analysis-explorer")}" class="ms-mobile-nav-link" aria-current="page"',
            html,
        )


class AnalysisExplorerIndexingTests(TestCase):
    def test_sitemap_lists_the_explorer_with_its_french_alternate(self):
        xml = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("/en/discover", xml)
        self.assertIn("/fr/discover", xml)

    def test_robots_does_not_block_the_explorer(self):
        robots = self.client.get("/robots.txt").content.decode()
        self.assertNotIn("discover", robots)
