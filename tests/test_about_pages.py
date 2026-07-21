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


class SitemapTests(TestCase):
    def test_static_sitemap_lists_about_pages_not_index_htm(self):
        xml = self.client.get("/sitemap.xml").content.decode()
        for name in ("about-model", "about-explorer", "about-team", "about-contact"):
            self.assertIn(reverse(name), xml)
        self.assertNotIn("/index.htm", xml)


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
