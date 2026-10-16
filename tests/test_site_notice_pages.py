from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

MODULE_TAG = (
    '<script type="module" src="/static/js/utils/site-notice/banner.js" '
    'id="ms-site-notice" data-url="/api/site-notice"></script>'
)


class SiteNoticeIncludeTests(TestCase):
    """Every page family loads the banner module exactly once."""

    def assertIncluded(self, response):
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('id="ms-site-notice"'), 1)
        self.assertEqual(html.count(MODULE_TAG), 1)

    def test_homepage(self):
        self.assertIncluded(self.client.get(reverse("root")))

    def test_about_page(self):
        self.assertIncluded(self.client.get(reverse("about-team")))

    def test_explorer(self):
        self.assertIncluded(self.client.get(reverse("analysis-explorer")))

    def test_login(self):
        self.assertIncluded(self.client.get(reverse("auth")))

    def test_signed_in_arches_page(self):
        user = User.objects.create_superuser("notice-admin", password="x")
        self.client.force_login(user)
        self.assertIncluded(self.client.get(reverse("search_home")))

    def test_endpoint_url_is_language_neutral(self):
        self.assertEqual(reverse("site-notice"), "/api/site-notice")
