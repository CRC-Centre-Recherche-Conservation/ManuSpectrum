from django.template import Context, Template
from django.test import SimpleTestCase, override_settings


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
