import re

from django.core.cache import cache
from django.test import TestCase, override_settings

NOSCRIPT = re.compile(r"<noscript>(.*?)</noscript>", re.S)


def noscript_blocks(html):
    return NOSCRIPT.findall(html)


class RevealFallbackTests(TestCase):
    def test_homepage_has_no_noscript_block(self):
        html = self.client.get("/en/").content.decode()
        self.assertFalse(any(".reveal" in block for block in noscript_blocks(html)))
        self.assertEqual(html.count("<noscript>"), 0)

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

    def test_search_chips_offer_fors_after_vermilion(self):
        html = self.client.get("/en/").content.decode()
        chips = re.findall(
            r'<button type="button" class="ms-search-chip" data-term="([^"]*)"', html
        )
        self.assertEqual(chips[:2], ["Vermilion", "FORS"])

    def test_no_technique_chip_block(self):
        html = self.client.get("/en/").content.decode()
        self.assertNotIn("ms-technique", html)

    def test_header_offers_the_explorer_on_every_public_page(self):
        for path in ("/en/", "/en/about/team", "/en/discover"):
            html = self.client.get(path).content.decode()
            self.assertIn('href="/en/discover"', html, path)
            if path != "/en/discover":
                self.assertNotIn('href="/en/discover" aria-current="page"', html, path)


class AboutPagePayloadTests(TestCase):
    """The About pages render their own script strings, not the Arches ``javascript.htm`` payload."""

    def test_no_page_carries_the_arches_payload(self):
        for path in (
            "/en/about/team",
            "/en/about/model",
            "/en/about/explorer",
            "/en/about/contact",
        ):
            html = self.client.get(path).content.decode()
            for marker in ("arches-urls", "arches-data", "CKEDITOR_BASEPATH"):
                self.assertNotIn(marker, html, f"{marker} on {path}")
            self.assertNotIn("biblissima-", html, path)

    def test_each_scripted_page_renders_its_own_catalogue(self):
        pages = {
            "/en/about/contact": ("ms-contact-copied=", "ms-ge-fields="),
            "/en/about/explorer": ("ms-ge-fields=", "ms-contact-copied="),
            "/en/about/model": ("ms-cm-models-line=", "ms-ge-fields="),
        }
        for path, (present, absent) in pages.items():
            html = self.client.get(path).content.decode()
            self.assertIn("arches-translations", html, path)
            self.assertIn(present, html, path)
            self.assertNotIn(absent, html, path)

    def test_the_team_page_and_error_pages_carry_no_catalogue(self):
        self.assertNotIn(
            "arches-translations", self.client.get("/en/about/team").content.decode()
        )
        with override_settings(DEBUG=False):
            html = self.client.get("/en/not-a-page").content.decode()
        self.assertNotIn("arches-translations", html)

    def test_the_catalogue_is_translated(self):
        html = self.client.get("/fr/about/contact").content.decode()
        self.assertIn("ms-contact-copied=", html)
        self.assertIn("Copié.", html)

    def test_the_header_carries_no_noscript_style(self):
        for path in ("/en/", "/en/about/team", "/en/discover"):
            html = self.client.get(path).content.decode()
            self.assertFalse(
                any("<style" in block for block in noscript_blocks(html)), path
            )
            self.assertNotIn("ms-nav-dropdown:hover", html, path)
