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
