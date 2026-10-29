"""The project ``makemessages`` never scans the gitignored notes or node_modules.

Usage:
    python manage.py test tests.test_makemessages_command --settings=tests.test_settings
"""

from unittest import mock

from django.core.management import call_command
from django.core.management.commands import makemessages as django_makemessages
from django.test import SimpleTestCase


class MakemessagesIgnoreTests(SimpleTestCase):
    def ignore_patterns(self, given=()):
        with mock.patch.object(
            django_makemessages.Command, "handle", return_value=""
        ) as parent:
            call_command(
                "makemessages", locale=["en"], ignore_patterns=list(given), verbosity=0
            )
        return parent.call_args.kwargs["ignore_patterns"]

    def test_notes_and_node_modules_are_always_ignored(self):
        self.assertEqual(
            set(self.ignore_patterns()),
            {"node_modules/*", "docs/*", "docs_claude/*"},
        )

    def test_a_given_ignore_pattern_is_kept_next_to_the_fixed_ones(self):
        patterns = self.ignore_patterns(["app/*", "docs/*"])
        self.assertEqual(patterns[0], "app/*")
        self.assertEqual(sorted(patterns), sorted(set(patterns)))
        self.assertTrue({"node_modules/*", "docs/*", "docs_claude/*"} <= set(patterns))

    def test_the_iiif_language_helpers_are_extraction_keywords(self):
        from manuspectrum.management.commands.makemessages import Command

        self.assertIn("--keyword=gettext_map", Command.xgettext_options)
        self.assertIn("--keyword=ngettext_map:1,2", Command.xgettext_options)
