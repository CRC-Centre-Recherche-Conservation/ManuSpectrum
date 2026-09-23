import re

from django.test import TestCase, override_settings

NOSCRIPT = re.compile(r"<noscript>(.*?)</noscript>", re.S)


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
