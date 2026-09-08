from django.conf import settings
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
        # SEO: /index.htm duplicates the root. Like every page it lives under
        # a language prefix, and redirects permanently to the root of its own
        # language. A bare /index.htm reaches the same place through
        # LocaleMiddleware's negotiation redirect first; what matters is where
        # the chain ends and that the query string survives.
        self.assertEqual(self.client.get("/en/index.htm")["Location"], "/en/")
        self.assertEqual(self.client.get("/fr/index.htm")["Location"], "/fr/")

        chain = self.client.get("/index.htm?q=1", follow=True)
        self.assertEqual(chain.redirect_chain[-1], ("/en/?q=1", 301))


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
        self.assertContains(resp, 'href="/en/"', status_code=404)
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

    def test_sitemap_has_no_bare_x_default_url(self):
        xml = self.client.get("/sitemap.xml").content.decode()
        self.assertNotIn('hreflang="x-default"', xml)


class LanguagePrefixRoutingTests(TestCase):
    """Every page URL carries its language; unprefixed paths are negotiated."""

    def test_pages_live_under_a_language_prefix(self):
        self.assertEqual(reverse("about-team"), "/en/about/team")
        for prefix, tag in (("/en", "en"), ("/fr", "fr")):
            resp = self.client.get(f"{prefix}/about/team")
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f'lang="{tag}"')

    def test_unprefixed_page_redirects_to_the_default_language(self):
        resp = self.client.get("/about/team")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/en/about/team")

    def test_unprefixed_page_honours_the_accept_language_header(self):
        resp = self.client.get("/about/team", HTTP_ACCEPT_LANGUAGE="fr-FR,fr;q=0.9")
        self.assertEqual(resp["Location"], "/fr/about/team")

    def test_unprefixed_page_honours_the_language_cookie(self):
        # The explicit choice made through the switcher outranks the header.
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "fr"
        resp = self.client.get("/about/team", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9")
        self.assertEqual(resp["Location"], "/fr/about/team")

    def test_a_prefix_in_the_path_outranks_the_cookie(self):
        # A shared link must open in the language it names.
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "fr"
        resp = self.client.get("/en/about/team")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'lang="en"')

    def test_arches_application_urls_resolve_under_en(self):
        # generateArchesURL() fills {language_code} from the document's lang,
        # so every Vue app shipped by an Arches application asks for /en/api/…
        # on an English page. Those are now real URLs, which is why the
        # redirect shim that used to rewrite them is gone.
        self.assertEqual(
            self.client.get("/en/api/get_frontend_i18n_data").status_code, 200
        )

    def test_project_machine_endpoints_stay_unprefixed(self):
        # The project's own machine endpoints sit below the language boundary,
        # so the bare path resolves and LocaleMiddleware never sees the 404 it
        # would rewrite. Arches core routes are deliberately NOT re-registered
        # that way: upstream wraps its whole URLconf, and following it is what
        # keeps installing an Arches application from becoming URL surgery.
        resource_id = "11111111-1111-4111-8111-111111111111"
        for name, args in (
            ("iiif-v3-annotation-collection", [resource_id]),
            ("iiif-v2-annotation", [resource_id]),
            ("biblissima-suggest", []),
            ("biblissima-search", []),
        ):
            url = reverse(name, args=args)
            self.assertFalse(
                url.startswith("/en/") or url.startswith("/fr/"),
                f"{name} reversed to a language-prefixed URL: {url}",
            )

    def test_robots_and_sitemap_stay_unprefixed(self):
        self.assertEqual(self.client.get("/robots.txt").status_code, 200)
        self.assertEqual(self.client.get("/sitemap.xml").status_code, 200)

    def test_hreflang_alternates_on_about_pages(self):
        html = self.client.get("/en/about/team").content.decode()
        self.assertIn('hreflang="fr"', html)
        self.assertIn("/fr/about/team", html)
        self.assertIn('hreflang="x-default"', html)

    def test_language_switcher_rendered_with_crawlable_links(self):
        html = self.client.get("/en/about/team").content.decode()
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
        # set_language lives INSIDE i18n_patterns: translate_url() runs with
        # the REQUEST's language, so the post has to carry the language it is
        # switching away from.
        resp = self.client.post(
            "/fr/i18n/setlang/",
            {"language": "en"},
            HTTP_REFERER="http://testserver/fr/about/team",
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith("/about/team"))
        self.assertNotIn("/fr/", resp["Location"])

        resp = self.client.post(
            "/en/i18n/setlang/",
            {"language": "fr"},
            HTTP_REFERER="http://testserver/en/about/team",
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/fr/about/team", resp["Location"])

    def test_robots_blocks_app_routes_in_every_language(self):
        body = self.client.get("/robots.txt").content.decode()
        for path in ("/search", "/en/search", "/fr/search", "/en/graph/"):
            self.assertIn(f"Disallow: {path}", body)

    def test_every_disallow_has_both_language_twins(self):
        # Robots rules match by path prefix from the root, so /search does not
        # cover /en/search. Assert the invariant for the whole file instead of
        # a hand-picked subset, so a new rule cannot reintroduce the gap.
        body = self.client.get("/robots.txt").content.decode()
        rules = [
            line[len("Disallow:") :].strip()
            for line in body.splitlines()
            if line.startswith("Disallow:")
        ]
        prefixes = tuple(f"/{code}/" for code, _label in settings.LANGUAGES)
        for path in rules:
            if path.startswith(prefixes):
                continue
            for code, _label in settings.LANGUAGES:
                self.assertIn(
                    f"/{code}{path}",
                    rules,
                    f"robots.txt: {path} has no /{code}/ twin",
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
