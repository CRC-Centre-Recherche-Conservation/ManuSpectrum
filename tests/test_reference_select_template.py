"""The report of a reference never links a URI that is not an http(s) URL (#294).

arches-controlled-lists binds ``href: uri`` as is in the report block of its
reference widget, so a bare thesaurus id became a link relative to the report
page. The project's template replaces that block through Django's recursive
``{% extends %}``. The block is bound to the unchanged arches-controlled-lists
view model (its JS module loads before any project copy), so it must not read
anything from the view model that the original block does not read. The
Knockout behaviour of the block is covered by
``media/js/views/components/widgets/reference-select-template.spec.js``.

Usage:
    python manage.py test tests.test_reference_select_template --settings="tests.test_settings"
"""

import os
import re

import arches_controlled_lists
from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase

NAME = "views/components/widgets/reference-select.htm"
UPSTREAM = os.path.join(
    os.path.dirname(arches_controlled_lists.__file__), "templates", *NAME.split("/")
)

#: The http(s) guard the block computes the link with (see the template).
HTTP_GUARD = r"/^https?:\/\/[^\/\s?#]+/i.test("


def report_block(html):
    """The markup of the report state of a rendered widget template."""
    start = html.index("state === 'report'")
    end = html.index("state === 'display_value'")
    return html[start:end]


def view_model_names(markup):
    """The names *markup* reads through ``$parent`` and ``$root``."""
    return set(re.findall(r"\$(?:parent|root)\.(\w+)", markup))


class ReferenceSelectTemplateTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = get_template(NAME)
        cls.html = cls.template.render({})

    def test_the_project_template_wins(self):
        templates_dir = os.path.join(settings.APP_ROOT, "templates")
        self.assertTrue(
            self.template.origin.name.startswith(templates_dir + os.sep),
            self.template.origin.name,
        )

    def test_the_report_never_binds_href_to_the_raw_uri(self):
        report = report_block(self.html)
        self.assertNotRegex(report, r"['\"]?href['\"]?\s*:\s*(\$data\.)?uri\b")
        hrefs = re.findall(r"['\"]?href['\"]?\s*:\s*([^,}]+)", report)
        self.assertEqual(hrefs, ["referenceHref"])

    def test_the_link_is_computed_with_the_http_guard(self):
        report = report_block(self.html)
        lets = re.findall(r"<!-- ko let: \{referenceHref: (.*?)\} -->", report)
        self.assertEqual(len(lets), 1, report)
        self.assertTrue(lets[0].startswith(HTTP_GUARD), lets[0])
        self.assertTrue(lets[0].endswith(" : null"), lets[0])

    def test_a_reference_without_a_link_still_shows_its_label(self):
        report = report_block(self.html)
        self.assertIn("<!-- ko ifnot: referenceHref -->", report)
        self.assertIn(
            '<span data-bind="text: $parent.getPrefLabel(labels)"></span>', report
        )

    def test_the_report_reads_only_what_the_original_reads_on_the_view_model(self):
        with open(UPSTREAM, encoding="utf-8") as upstream:
            original = re.search(
                r"\{% block report %\}(.*?)\{% endblock report %\}",
                upstream.read(),
                re.S,
            ).group(1)
        self.assertLessEqual(
            view_model_names(report_block(self.html)), view_model_names(original)
        )

    def test_the_editor_of_arches_controlled_lists_is_kept(self):
        self.assertEqual(self.html.count("select2Config: select2Config"), 2)
        self.assertIn("$root.translations.defaultValue", self.html)
