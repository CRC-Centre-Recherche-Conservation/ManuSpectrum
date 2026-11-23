"""The project's text widget template: core form, replaced report blocks.

Usage:
    python manage.py test tests.test_lang_fallback_templates --settings="tests.test_settings"
"""

import re

from django.template.loader import get_template
from django.test import SimpleTestCase
from django.utils import translation

TEXT = "views/components/widgets/text.htm"


def render():
    return get_template(TEXT).render({})


class TextWidgetTemplateTests(SimpleTestCase):
    def test_the_text_template_extends_the_core_one(self):
        html = render()
        self.assertIn("widget-inline-tools-collapser", html)
        self.assertIn("ms-lang-fallback", html)

    def test_the_core_report_expression_is_replaced(self):
        self.assertNotIn("['value'] : $root.translations.none", render())

    def test_no_template_tag_is_left(self):
        html = render()
        self.assertNotIn("{%", html)
        self.assertNotIn("{{", html)

    def test_the_marker_title_is_translated(self):
        with translation.override("fr"):
            html = render()
        self.assertIn("Non saisi dans cette langue, affiché en", html)

    def test_the_let_expression_has_no_double_dash(self):
        html = render()
        for match in re.finditer(r"ko let:(.*?)-->", html, re.S):
            self.assertNotIn("--", match.group(1))
        self.assertIn("msShown", html)
