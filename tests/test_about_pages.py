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
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        for name in ("about-model", "about-explorer", "about-team", "about-contact"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
