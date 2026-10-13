import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
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


class SiteOriginTagTests(SimpleTestCase):
    def render(self, host):
        request = RequestFactory().get("/", HTTP_HOST=host)
        tpl = Template("{% load manuspectrum_settings %}{% site_origin %}")
        return tpl.render(Context({"request": request}))

    @override_settings(ALLOWED_HOSTS=["manuspectrum.test"])
    def test_scheme_and_allowed_host(self):
        self.assertEqual(self.render("manuspectrum.test"), "http://manuspectrum.test")

    @override_settings(ALLOWED_HOSTS=["manuspectrum.test"])
    def test_empty_for_a_disallowed_host(self):
        # The 400 page of a disallowed Host must render, not raise again.
        self.assertEqual(self.render("evil.example"), "")

    def test_empty_without_a_request(self):
        tpl = Template("{% load manuspectrum_settings %}{% site_origin %}")
        self.assertEqual(tpl.render(Context({})), "")


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


class JsonLdHostEscapingTests(SimpleTestCase):
    """Every JSON-LD block stays valid JSON whatever `request.get_host()` returns."""

    TEMPLATES = (
        "index.htm",
        "views/pages/contact.htm",
        "views/pages/graph-explorer.htm",
        "views/pages/conceptual-model.htm",
        "views/pages/team.htm",
    )
    HOSTILE_HOST = 'example.org"</script><script>alert(1)</script>'

    def render(self, name):
        """Render a public page outside the request cycle.

        `render_to_string` is called without `request=`, so no context processor
        runs: the header and footer read a bare `user`, supplied here.
        """
        from django.contrib.auth.models import AnonymousUser
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        from django.utils import translation

        request = RequestFactory().get("/")
        request.get_host = lambda: self.HOSTILE_HOST
        with translation.override("en"):
            return render_to_string(
                name,
                {
                    "request": request,
                    "user": AnonymousUser(),
                    "seo_description": "d",
                },
            )

    def test_json_ld_blocks_survive_a_host_carrying_quotes(self):
        import json
        import re

        for name in self.TEMPLATES:
            with self.subTest(template=name):
                html = self.render(name)
                blocks = re.findall(
                    r'<script type="application/ld\+json">(.*?)</script>', html, re.S
                )
                self.assertTrue(blocks, f"{name}: no JSON-LD")
                for block in blocks:
                    self.assertIn("\\u0022", block)
                    self.assertNotIn("<script>", block)
                    json.loads(block)


LEGAL_NAMES = ("about-legal", "about-privacy", "about-terms")


class LegalPagesTests(TestCase):
    def get(self, name, lang="en"):
        resp = self.client.get(f"/{lang}{reverse(name)[3:]}")
        self.assertEqual(resp.status_code, 200, name)
        return resp.content.decode()

    def test_routes_live_under_the_language_prefix(self):
        self.assertEqual(reverse("about-legal"), "/en/about/legal")
        self.assertEqual(reverse("about-privacy"), "/en/about/privacy")
        self.assertEqual(reverse("about-terms"), "/en/about/terms")

    def test_each_page_answers_in_its_language(self):
        headings = {
            "about-legal": ("Legal notice", "Mentions légales"),
            "about-privacy": ("Privacy policy", "Politique de confidentialité"),
            "about-terms": ("Terms of use", "Conditions d'utilisation"),
        }
        for name, (en, fr) in headings.items():
            en_html = self.get(name, "en")
            fr_html = self.get(name, "fr")
            self.assertIn('lang="en"', en_html)
            self.assertIn('lang="fr"', fr_html)
            self.assertIn(f'<h1 class="ms-page-hero__title">{en}</h1>', en_html)
            self.assertIn(fr, fr_html.replace("&#x27;", "'"))

    def test_legal_notice_headings_and_names(self):
        html = self.get("about-legal")
        for heading in (
            "Publisher",
            "Publication director",
            "Scientific lead and editorial lead",
            "Host",
            "Contact",
        ):
            self.assertIn(f"<h2>{heading}</h2>", html)
        for needle in (
            "UAR 3224",
            "Anne Michelin",
            "UAR Huma-Num (UAR 3598)",
            "14 cours des humanités, 93322 Aubervilliers cedex",
        ):
            self.assertIn(needle, html)

    def test_supervisory_bodies_keep_their_french_names_on_the_english_page(self):
        html = self.get("about-legal", "en").replace("&#x27;", "'")
        for name in (
            "Centre national de la recherche scientifique (CNRS)",
            "Muséum national d'Histoire naturelle (MNHN)",
            "Ministère de la Culture",
        ):
            self.assertIn(name, html)

    @override_settings(CONTACT_EMAIL="legal@manuspectrum.test")
    def test_legal_notice_prints_the_contact_setting(self):
        self.assertIn("legal@manuspectrum.test", self.get("about-legal"))

    def test_privacy_headings_and_cookies(self):
        html = self.get("about-privacy")
        for heading in (
            "Data controller",
            "Data protection officer",
            "Purposes",
            "Legal bases",
            "Data we keep",
            "Retention periods",
            "Recipients",
            "Transfers outside the European Union",
            "Your rights",
            "Cookies and browser storage",
            "Restricted resources",
            "Abandoned workflows",
        ):
            self.assertIn(f"<h2>{heading}</h2>", html)
        for cookie in ("manuspectrum", "csrftoken", "django_language"):
            self.assertIn(f"<code>{cookie}</code>", html)
        self.assertIn("no tracker", html.lower())

    def test_privacy_names_the_map_third_parties_under_a_stable_anchor(self):
        for lang, heading in (("en", "Third-party services"), ("fr", "Services tiers")):
            html = self.get("about-privacy", lang)
            self.assertIn(f'<h2 id="third-party-services">{heading}</h2>', html)
            for host in ("tiles.openfreemap.org", "vtiles.openhistoricalmap.org"):
                self.assertIn(host, html)

    def test_privacy_third_party_section_lists_every_external_host(self):
        for lang in ("en", "fr"):
            html = self.get("about-privacy", lang)
            for host in (
                "iiif.unicaen.fr",
                "tiles.openfreemap.org",
                "vtiles.openhistoricalmap.org",
                "cke4.ckeditor.com",
                "svc.webspellchecker.net",
                "fonts.googleapis.com",
            ):
                self.assertIn(host, html, f"{lang}: {host}")
            self.assertNotIn("No other page and no other Explorer view", html)
            self.assertNotIn("Aucune autre page", html)

    def test_privacy_access_log_is_listed_with_the_logrotate_retention(self):
        rule = (
            Path(settings.APP_ROOT).parent
            / "deploy"
            / "logrotate"
            / "manuspectrum-nginx.in"
        ).read_text()
        days = re.search(r"^\s*maxage (\d+)", rule, re.M).group(1)
        for lang, label, text in (
            ("en", "Access log", f"{days} days, then deleted."),
            ("fr", "Journal d", f"{days} jours"),
        ):
            html = self.get("about-privacy", lang)
            self.assertIn(label, html)
            self.assertIn(text, html)

    def test_privacy_printed_durations_follow_the_settings(self):
        with override_settings(
            LOGIN_RECORDS_RETENTION_DAYS=61,
            EMBARGO_MAX_MONTHS=7,
            EMBARGO_NOTICE_DAYS=(40, 9),
            WORKFLOW_CLEANUP_AFTER_DAYS=45,
            WORKFLOW_NOTICE_DAYS=(14, 3),
            ACCOUNT_RETENTION_MONTHS=18,
            ACCOUNT_RETENTION_NOTICE_DAYS=21,
        ):
            html = self.get("about-privacy")
        self.assertIn("without a sign-in for 18 months", html)
        self.assertIn("is anonymised, 21 days after a notice", html)
        self.assertIn("2 months (61 days)", html)
        self.assertIn("7 months at most", html)
        self.assertIn("40 and 9 days before", html)
        self.assertIn("45 days", html)
        self.assertIn("14 and 3 days before", html)

    def test_privacy_durations_default_to_the_shipped_settings(self):
        html = self.get("about-privacy")
        self.assertIn(f"({settings.LOGIN_RECORDS_RETENTION_DAYS} days)", html)
        self.assertIn(f"{settings.EMBARGO_MAX_MONTHS} months at most", html)
        self.assertIn("without a sign-in for 24 months", html)
        self.assertIn("e-mail address is erased and the name stays as credit", html)

    def test_terms_open_with_the_warning_and_follow_the_settings(self):
        with override_settings(EMBARGO_MAX_MONTHS=9, WORKFLOW_CLEANUP_AFTER_DAYS=33):
            html = self.get("about-terms")
        warning = html.split('class="ms-legal-warning"')[1].split("</div>")[0]
        for needle in (
            "not a data repository",
            "FAIR",
            "Recherche Data Gouv",
            "Nakala",
            "9 months at most",
            "33 days",
        ):
            self.assertIn(needle, warning)
        self.assertLess(html.index("Read this first"), html.index("Words we use"))

    def test_terms_show_the_version_constant(self):
        from manuspectrum.accounts.terms import TERMS_VERSION

        self.assertIn(
            f'id="ms-terms-version">{TERMS_VERSION}</span>', self.get("about-terms")
        )

    def test_privacy_names_the_cnrs_dpo_and_the_cnil(self):
        for lang in ("en", "fr"):
            html = self.get("about-privacy", lang)
            self.assertIn("dpd.demandes@cnrs.fr", html)
            self.assertIn("2 rue Jean Zay, 54519 Vandœuvre-lès-Nancy", html)
            self.assertIn("https://www.cnil.fr/", html)

    def test_legal_pages_leave_no_pending_marker(self):
        for name in LEGAL_NAMES:
            self.assertNotIn("[À CONFIRMER]", self.get(name))

    def test_no_third_party_asset_and_only_the_pages_stylesheet(self):
        import re

        for name in LEGAL_NAMES:
            html = self.get(name)
            urls = re.findall(r"<script[^>]+src=\"([^\"]+)\"", html)
            urls += re.findall(r"<link[^>]+href=\"([^\"]+)\"", html)
            urls += re.findall(r"<iframe[^>]+src=\"([^\"]+)\"", html)
            for url in urls:
                self.assertFalse(
                    re.match(r"(https?:)?//", url) and "testserver" not in url,
                    f"{name}: third-party {url}",
                )
            self.assertNotIn("<iframe", html)
            self.assertNotIn("bootstrap", html.lower())
            self.assertNotIn("css/project", html)

    def test_footer_legal_column_links_resolve(self):
        import re

        html = self.get("about-contact")
        for name in LEGAL_NAMES:
            self.assertIn(f'href="{reverse(name)}"', html)
        for name in LEGAL_NAMES:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertTrue(re.search(r"<h4>Legal</h4>", html))

    def test_sitemap_lists_the_legal_pages_in_both_languages(self):
        xml = self.client.get("/sitemap.xml").content.decode()
        for slug in ("legal", "privacy", "terms"):
            self.assertIn(f"/en/about/{slug}", xml)
            self.assertIn(f"/fr/about/{slug}", xml)

    def test_robots_does_not_block_the_legal_pages(self):
        body = self.client.get("/robots.txt").content.decode()
        self.assertNotIn("/about", body)


class LegalPagesProductionCheckTests(SimpleTestCase):
    def run_check(self, environment, app_root=None):
        from unittest import mock

        from manuspectrum.checks import check_legal_pages_complete

        env = {"DEPLOY_ENVIRONMENT": environment}
        with mock.patch.dict("os.environ", env):
            if app_root is None:
                return check_legal_pages_complete(None)
            with override_settings(APP_ROOT=app_root):
                return check_legal_pages_complete(None)

    def make_pages(self, root, privacy):
        from pathlib import Path

        pages = Path(root, "templates", "views", "pages")
        pages.mkdir(parents=True)
        for name in ("legal.htm", "terms.htm"):
            (pages / name).write_text("done", encoding="utf-8")
        (pages / "privacy.htm").write_text(privacy, encoding="utf-8")

    def test_production_refuses_the_pending_marker(self):
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            self.make_pages(root, "DPO: [À CONFIRMER]")
            (error,) = self.run_check("production", root)
            self.assertEqual(error.id, "manuspectrum.E003")
            self.assertIn("privacy.htm", error.msg)
            self.assertEqual(self.run_check("development", root), [])

    def test_the_shipped_templates_pass_in_production(self):
        self.assertEqual(self.run_check("production"), [])

    def test_production_accepts_pages_without_the_marker(self):
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            self.make_pages(root, "done")
            self.assertEqual(self.run_check("production", root), [])

    def test_other_environments_accept_the_marker(self):
        self.assertEqual(self.run_check("development"), [])
        self.assertEqual(self.run_check(""), [])


class ContactAccessRequestTests(TestCase):
    def test_contact_page_lists_what_to_include_and_offers_the_access_reason(self):
        html = self.client.get(reverse("about-contact")).content.decode()
        self.assertIn('id="ms-contact-include"', html)
        for item in ("your institutional e-mail address", "your position"):
            self.assertIn(item, html)
        self.assertIn('<option value="access">', html)

    def test_footer_links_to_the_access_request(self):
        html = self.client.get(reverse("about-team")).content.decode()
        self.assertIn(f'href="{reverse("about-contact")}?reason=access"', html)


class TermsDigestTests(SimpleTestCase):
    @staticmethod
    def compute_digest():
        import hashlib
        from pathlib import Path

        import polib

        root = Path(settings.APP_ROOT)
        template = root / "templates" / "views" / "pages" / "terms.htm"
        sha = hashlib.sha256(template.read_bytes())
        catalogue = polib.pofile(
            str(root / "locale" / "fr" / "LC_MESSAGES" / "django.po")
        )
        for entry in sorted(catalogue, key=lambda e: e.msgid):
            if any("views/pages/terms.htm" in path for path, _ in entry.occurrences):
                sha.update(entry.msgid.encode())
                sha.update(entry.msgid_plural.encode())
                sha.update(entry.msgstr.encode())
                for index in sorted(entry.msgstr_plural):
                    sha.update(entry.msgstr_plural[index].encode())
        return sha.hexdigest()

    def test_terms_digest_matches_the_template_and_its_french_text(self):
        from manuspectrum.accounts.terms import TERMS_DIGEST

        self.assertEqual(
            self.compute_digest(),
            TERMS_DIGEST,
            "The terms changed: bump TERMS_VERSION if users must accept them "
            "again, then update TERMS_DIGEST (for a typo fix, update "
            "TERMS_DIGEST only).",
        )
