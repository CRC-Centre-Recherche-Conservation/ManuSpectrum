"""The relations cap and page size reach the report model (media/js/models/report.js).

Usage:
    python manage.py test tests.test_related_resources_settings --settings="tests.test_settings"
"""

import re

from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.utils import translation


class RelatedResourcesSettingsTests(TestCase):
    @override_settings(
        RELATED_RESOURCES_EXPORT_LIMIT=321, RELATED_RESOURCES_PER_PAGE=17
    )
    def test_javascript_htm_hands_the_cap_and_the_page_size_to_arches_data(self):
        request = RequestFactory().get("/en/")
        request.user = AnonymousUser()
        with translation.override("en"):
            html = render_to_string("javascript.htm", {}, request=request)

        block = re.search(
            r"<div class='arches-data'\s+style=\"display: none;\"(.*?)></div>",
            html,
            re.S,
        )
        self.assertIsNotNone(block)
        self.assertIn('related-resources-export-limit="321"', block[1])
        self.assertIn('related-resources-per-page="17"', block[1])
        self.assertIn("class='arches-data'\n        celery-running", html)
