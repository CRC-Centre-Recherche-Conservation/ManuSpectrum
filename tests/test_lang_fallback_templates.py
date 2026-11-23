"""The project's text and rich-text widget templates: core form, replaced blocks,
marker title and the comment-safe expression.

Usage:
    python manage.py test tests.test_lang_fallback_templates --settings="tests.test_settings"
"""

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


class RichTextWidgetTemplateTests(SimpleTestCase):
    def render(self):
        return get_template("views/components/widgets/rich-text.htm").render({})

    def test_the_rich_text_template_extends_the_core_one(self):
        html = self.render()
        self.assertIn("views/components/rich-text-editor", html)
        self.assertIn("ms-lang-fallback", html)

    def test_the_core_rich_text_report_expression_is_replaced(self):
        self.assertNotIn("html: currentText || $root.translations.none", self.render())

    def test_no_template_tag_is_left(self):
        html = self.render()
        self.assertNotIn("{%", html)
        self.assertNotIn("{{", html)


class SharedBehaviourTests(SimpleTestCase):
    TEMPLATES = (TEXT, "views/components/widgets/rich-text.htm")
    SHOWN = "views/components/widgets/ms-lang-fallback/shown.htm"

    def test_the_marker_title_is_translated(self):
        for name in self.TEMPLATES:
            with self.subTest(template=name), translation.override("fr"):
                html = get_template(name).render({})
            self.assertIn("Non saisi dans cette langue, affiché en", html)

    def test_the_pick_expression_cannot_close_a_knockout_comment(self):
        for language in ("en", "fr"):
            with self.subTest(language=language), translation.override(language):
                html = get_template(self.SHOWN).render({})
            for sequence in ("-->", "--!>", "--"):
                self.assertNotIn(sequence, html)
            self.assertIn("msShown", html)

    def test_the_templates_carry_their_core_header_as_a_django_comment(self):
        for name in self.TEMPLATES:
            with self.subTest(template=name):
                html = get_template(name).render({})
                self.assertNotIn("{% comment %}", html)
                self.assertNotIn("Extends Arches", html)

    def test_the_marker_is_spelled_out_for_screen_readers(self):
        html = get_template(TEXT).render({})
        self.assertIn('aria-hidden="true"', html)
        self.assertIn("sr-only", html)
