import re

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

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
            self.assertRegex(tag, r"\s(defer[\s>]|type=\"module\")")


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


class TechniqueStatTests(TestCase):
    def test_the_ma_xrf_stat_names_x_ray_fluorescence_imaging(self):
        for lang, caption, wrong in (
            ("en", "X-ray Fluorescence Imaging", "Micro-Fluorescence"),
            ("fr", "Imagerie de fluorescence de rayons X", "Microfluorescence"),
        ):
            with self.subTest(lang=lang):
                html = self.client.get(f"/{lang}/").content.decode()
                self.assertRegex(
                    html,
                    rf'>MA-XRF</div>\s*<div class="ms-stat-label">{caption}</div>',
                )
                self.assertNotIn(wrong, html)


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
            for marker in ("arches-translations", "arches-urls", "arches-data"):
                self.assertNotIn(marker, html, f"{marker} on /{lang}/")


class DiscoverEntryTests(TestCase):
    def setUp(self):
        cache.clear()

    def _form(self, html):
        start = html.index('id="ms-search-form"')
        return html[start : html.index("</form>", start)]

    def test_search_form_offers_the_database_and_the_data_lab(self):
        html = self.client.get("/en/").content.decode()
        self.assertNotIn("<button", self._form(html))
        buttons = re.findall(r'<button type="submit" form="ms-search-form"[^>]*>', html)
        self.assertEqual(len(buttons), 2)
        self.assertNotIn("formaction", buttons[0])
        self.assertIn('aria-describedby="ms-way-db"', buttons[0])
        self.assertIn('formaction="/en/discover"', buttons[1])
        self.assertIn('aria-describedby="ms-way-lab"', buttons[1])
        for described in ("ms-way-db", "ms-way-lab"):
            self.assertIn(f'<figcaption id="{described}">', html)
        self.assertIn('<label class="ms-visually-hidden" for="ms-search-input">', html)
        self.assertNotIn("ms-search-cta", html)
        self.assertNotIn("ms-search-discover", html)

    def test_search_form_buttons_are_labelled_in_both_languages(self):
        for lang, db_label, lab_label in (
            ("en", "Search the database", "Search the Data Lab"),
            (
                "fr",
                "Rechercher dans la base",
                "Rechercher dans le Laboratoire des données",
            ),
        ):
            html = self.client.get(f"/{lang}/").content.decode()
            self.assertRegex(
                html, rf'form="ms-search-form"[^>]*>\s*{db_label}\s*</button>'
            )
            self.assertRegex(
                html, rf'form="ms-search-form"[^>]*>\s*{lab_label}\s*</button>'
            )

    def test_each_screenshot_links_to_its_tool(self):
        for lang in ("en", "fr"):
            html = self.client.get(f"/{lang}/").content.decode()
            with translation.override(lang):
                search_url = reverse("search_home")
            links = re.findall(r'<a class="ms-search-way-shot" href="([^"]*)">', html)
            self.assertEqual(links, [search_url, f"/{lang}/discover"], lang)

    def test_more_techniques_tile_links_to_the_corpus(self):
        html = self.client.get("/en/").content.decode()
        self.assertIn('<a class="ms-stat ms-stat--more', html)
        self.assertIn('href="/en/discover?screen=results"', html)

    def test_hero_offers_the_search_and_the_data_lab(self):
        for lang, search_label, lab_label in (
            ("en", "Search the database", "Data Lab"),
            ("fr", "Rechercher dans la base", "Laboratoire des données"),
        ):
            html = self.client.get(f"/{lang}/").content.decode()
            start = html.index('class="ms-hero-actions"')
            hero = html[start : html.index("ms-hero-scroll", start)]
            with translation.override(lang):
                search_url = reverse("search_home")
            self.assertIn(f'href="{search_url}"', hero, lang)
            self.assertIn(f'href="/{lang}/discover"', hero, lang)
            self.assertIn(search_label, hero, lang)
            self.assertIn(lab_label, hero, lang)

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
            self.assertIn(">Data Lab</a>", html, path)
            if path != "/en/discover":
                self.assertNotIn('href="/en/discover" aria-current="page"', html, path)

    def test_header_search_link_scrolls_to_the_homepage_section(self):
        html = self.client.get("/en/about/team").content.decode()
        self.assertEqual(html.count('<a href="/en/#search"'), 2)


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
            for marker in ("arches-urls", "arches-data"):
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


class ToolCardsTests(TestCase):
    def setUp(self):
        cache.clear()

    def _ways(self, html):
        start = html.index('class="ms-search-ways"')
        return html[start : html.index("</figure>\n                </div>", start)]

    def test_each_tool_card_carries_a_localised_screenshot(self):
        for lang in ("en", "fr"):
            ways = self._ways(self.client.get(f"/{lang}/").content.decode())
            imgs = re.findall(r"<img\b[^>]*>", ways)
            self.assertEqual(len(imgs), 2, lang)
            for img, tool in zip(imgs, ("search", "lab")):
                self.assertIn(f"tool-{tool}-{lang}-800.webp", img, lang)
                self.assertIn(f"tool-{tool}-{lang}.webp", img, lang)
                self.assertRegex(img, r'alt="[^"]+"')
                self.assertRegex(img, r'width="\d+"')
                self.assertRegex(img, r'height="\d+"')
                self.assertIn('loading="lazy"', img)

    def test_section_title_names_the_two_ways(self):
        for lang, title in (
            ("en", "Two ways to search"),
            ("fr", "Deux façons de chercher"),
        ):
            html = self.client.get(f"/{lang}/").content.decode()
            self.assertIn(f'<h2 class="ms-section-title">{title}</h2>', html)

    def test_hero_has_one_learn_more_cue_to_the_project(self):
        for lang, label in (("en", "Learn more"), ("fr", "En savoir plus")):
            html = self.client.get(f"/{lang}/").content.decode()
            self.assertNotIn("ms-hero-more", html)
            start = html.index('class="ms-hero-scroll"')
            cue = html[start : html.index("</div>", start)]
            self.assertIn('href="#project"', cue)
            self.assertIn(f"<span>{label}</span>", cue)
            self.assertEqual(html.count(f">{label}<"), 1, lang)
