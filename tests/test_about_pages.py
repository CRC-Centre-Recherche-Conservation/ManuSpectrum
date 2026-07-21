from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class ContactEmailTagTests(SimpleTestCase):
    def render(self):
        tpl = Template("{% load manuspectrum_settings %}{% contact_email %}")
        return tpl.render(Context({}))

    @override_settings(
        CONTACT_EMAIL="hello@example.org", DEFAULT_FROM_EMAIL="from@x.com"
    )
    def test_prefers_contact_email(self):
        self.assertEqual(self.render(), "hello@example.org")

    @override_settings(CONTACT_EMAIL="", DEFAULT_FROM_EMAIL="from@x.com")
    def test_falls_back_to_default_from_email(self):
        self.assertEqual(self.render(), "from@x.com")

    @override_settings(CONTACT_EMAIL="", DEFAULT_FROM_EMAIL="")
    def test_empty_when_unset(self):
        self.assertEqual(self.render(), "")


class AboutRoutingTests(TestCase):
    def test_pages_reachable_anonymously(self):
        for name in ("about-model", "about-team", "about-contact"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, f"{name} should be public")

    def test_homepage_and_pages_render(self):
        self.assertEqual(self.client.get(reverse("root")).status_code, 200)
        for name in ("about-model", "about-explorer", "about-team", "about-contact"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_index_htm_redirects_permanently_to_root(self):
        # SEO: /index.htm duplicated / — it must 301 (and keep query strings).
        resp = self.client.get("/index.htm")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/")
        resp = self.client.get("/index.htm?q=1")
        self.assertEqual(resp["Location"], "/?q=1")


# ArchesTestRunner forces debug_mode=True, and Django serves its technical 404
# instead of handler404 whenever DEBUG is on — so these tests pin DEBUG=False,
# which is also the only mode where real visitors ever see these pages.
@override_settings(DEBUG=False)
class ErrorPageTests(TestCase):
    def test_404_is_branded_with_working_home_link(self):
        # The Arches default 404 linked /index.html (sic) — a URL that does
        # not exist. Ours must carry the ManuSpectrum chrome and a real link.
        resp = self.client.get("/this-page-does-not-exist")
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "ManuSpectrum", status_code=404)
        self.assertContains(resp, 'href="/"', status_code=404)
        self.assertNotContains(resp, "/index.html", status_code=404)
        self.assertContains(resp, 'name="robots" content="noindex"', status_code=404)

    def test_404_api_calls_get_json(self):
        resp = self.client.get(
            "/api/this-does-not-exist", HTTP_ACCEPT="application/json"
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn("application/json", resp["Content-Type"])

    def test_500_template_renders_standalone(self):
        # The 500 page must render with an EMPTY context — no context
        # processors, no bundles — or it can crash during a real incident.
        from django.template.loader import render_to_string

        # Rendering with an empty context IS the guarantee: any dependency on
        # request context or bundles would raise right here.
        html = render_to_string("errors/500.htm", {})
        self.assertIn("ManuSpectrum", html)
        self.assertIn("Une erreur est survenue", html)

    def test_403_and_400_templates_render(self):
        from django.template.loader import get_template
        from django.test import RequestFactory

        req = RequestFactory().get("/x")
        for name in ("errors/403.htm", "errors/400.htm"):
            html = get_template(name).render({}, req)
            self.assertIn("ManuSpectrum", html)


class SocialMetaTests(TestCase):
    def test_about_pages_carry_og_and_valid_json_ld(self):
        import json
        import re

        for name in ("about-model", "about-explorer", "about-team", "about-contact"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn('property="og:title"', html, name)
            self.assertIn('property="og:image"', html, name)
            self.assertIn('name="twitter:card"', html, name)
            blocks = re.findall(
                r'<script type="application/ld\+json">(.*?)</script>', html, re.S
            )
            self.assertTrue(blocks, f"{name}: no JSON-LD")
            for b in blocks:
                json.loads(b)  # raises on invalid JSON

    def test_team_json_ld_lists_members(self):
        html = self.client.get(reverse("about-team")).content.decode()
        for member in ("Anne Michelin", "Gilles Kagan", "Maxime Humeau"):
            self.assertIn(f'"name": "{member}"', html)


class SitemapTests(TestCase):
    def test_static_sitemap_lists_about_pages_not_index_htm(self):
        xml = self.client.get("/sitemap.xml").content.decode()
        for name in ("about-model", "about-explorer", "about-team", "about-contact"):
            self.assertIn(reverse(name), xml)
        self.assertNotIn("/index.htm", xml)

    def test_sitemap_carries_french_alternates(self):
        xml = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("/fr/about/team", xml)
        self.assertIn('hreflang="fr"', xml)
        self.assertIn('hreflang="x-default"', xml)


class FrenchRoutingTests(TestCase):
    """prefix_default_language=False: EN stays unprefixed, FR lives at /fr/."""

    def test_english_urls_stay_unprefixed(self):
        self.assertEqual(reverse("about-team"), "/about/team")
        resp = self.client.get("/about/team")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'lang="en"')

    def test_french_twin_serves_french(self):
        resp = self.client.get("/fr/about/team")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'lang="fr"')

    def test_en_prefix_does_not_exist(self):
        # With prefix_default_language=False there must be no /en/ tree —
        # a working /en/ twin would be duplicate content.
        self.assertEqual(self.client.get("/en/about/team").status_code, 404)

    def test_hreflang_alternates_on_about_pages(self):
        html = self.client.get("/about/team").content.decode()
        self.assertIn('hreflang="fr"', html)
        self.assertIn("/fr/about/team", html)
        self.assertIn('hreflang="x-default"', html)

    def test_language_switcher_rendered_with_crawlable_links(self):
        html = self.client.get("/about/team").content.decode()
        self.assertIn("ms-lang-switch", html)
        self.assertIn('href="http://testserver/fr/about/team"', html)

    def test_translated_page_url_cannot_leak_an_external_host(self):
        # Security regression (open redirect): a "//evil.com/…" request path
        # must never surface as an off-site href in the switcher / hreflang.
        from django.template import Context, Template
        from django.test import RequestFactory

        req = RequestFactory().get("/placeholder")
        req.path = "//evil.com/login"  # what a raw WSGI request preserves
        req.resolver_match = None  # unrouted → the 404 render path
        tpl = Template("{% load manuspectrum_settings %}{% translated_page_url 'fr' %}")
        out = tpl.render(Context({"request": req}))
        self.assertNotIn("evil.com", out)
        self.assertEqual(out, "")  # no switcher on unrouted pages

    def test_all_about_alternates_point_at_our_host(self):
        import re

        for name in ("about-model", "about-explorer", "about-team", "about-contact"):
            html = self.client.get(reverse(name)).content.decode()
            for href in re.findall(r'hreflang="[^"]+" href="([^"]*)"', html):
                self.assertTrue(
                    href.startswith("http://testserver/"),
                    f"{name}: alternate escaped host → {href}",
                )

    def test_language_switcher_round_trip(self):
        # Regression: set_language must live INSIDE i18n_patterns. Unprefixed,
        # the request was forced to English (prefix_default_language=False),
        # translate_url Resolver404'd on the /fr/ referer, and switching back
        # to English bounced users to the same French page.
        resp = self.client.post(
            "/fr/i18n/setlang/",
            {"language": "en"},
            HTTP_REFERER="http://testserver/fr/about/team",
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith("/about/team"))
        self.assertNotIn("/fr/", resp["Location"])

        resp = self.client.post(
            "/i18n/setlang/",
            {"language": "fr"},
            HTTP_REFERER="http://testserver/about/team",
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/fr/about/team", resp["Location"])

    def test_robots_blocks_french_app_routes(self):
        body = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /fr/search", body)
        self.assertIn("Disallow: /fr/graph/", body)

    def test_every_disallow_has_a_french_twin(self):
        # Regression: /fr/renderer/ and /fr/renderer_config/ were the two
        # missing twins. Assert the invariant for the whole file instead of
        # a hand-picked subset, so a new rule can't reintroduce the gap.
        body = self.client.get("/robots.txt").content.decode()
        rules = [
            line[len("Disallow:") :].strip()
            for line in body.splitlines()
            if line.startswith("Disallow:")
        ]
        for path in rules:
            if path.startswith("/fr/") or path == "/api/":
                # /api/ is language-neutral (registered below the i18n wrap).
                continue
            self.assertIn(
                f"/fr{path}",
                rules,
                f"robots.txt: {path} has no /fr/ twin",
            )


class ContactPageTests(TestCase):
    @override_settings(CONTACT_EMAIL="team@manuspectrum.fr")
    def test_contact_email_rendered_in_form_dataset(self):
        resp = self.client.get(reverse("about-contact"))
        self.assertContains(resp, 'data-contact-email="team@manuspectrum.fr"')

    @override_settings(CONTACT_EMAIL="", DEFAULT_FROM_EMAIL="")
    def test_contact_page_ok_without_address(self):
        resp = self.client.get(reverse("about-contact"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-contact-email=""')


class ConceptualModelPageTests(TestCase):
    def test_key_sections_present(self):
        resp = self.client.get(reverse("about-model"))
        self.assertEqual(resp.status_code, 200)
        for needle in ("CIDOC-CRM", "CRMsci", "Getty AAT"):
            self.assertContains(resp, needle)
        # links to the interactive explorer
        self.assertContains(resp, reverse("about-explorer"))


class TeamPageTests(TestCase):
    def test_members_present(self):
        resp = self.client.get(reverse("about-team"))
        self.assertEqual(resp.status_code, 200)
        for name in ("Anne Michelin", "Gilles Kagan", "Maxime Humeau"):
            self.assertContains(resp, name)
