"""The project ``makemessages`` never scans the gitignored notes or node_modules.

Usage:
    python manage.py test tests.test_makemessages_command --settings=tests.test_settings
"""

import os
import tempfile
from pathlib import Path

import polib
from django.core.management import call_command
from django.test import SimpleTestCase


class MakemessagesIgnoreTests(SimpleTestCase):
    def extract(self, ignore=()):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "locale" / "en" / "LC_MESSAGES").mkdir(parents=True)
            for folder in ("docs_claude", "docs", "node_modules", "app"):
                (base / folder).mkdir()
                text = f"{folder}_only"
                (base / folder / "mod.py").write_text(
                    f"from django.utils.translation import gettext as _\n_('{text}')\n"
                )
            previous = os.getcwd()
            os.chdir(base)
            try:
                call_command(
                    "makemessages",
                    locale=["en"],
                    extensions=["py"],
                    ignore_patterns=list(ignore),
                    verbosity=0,
                )
            finally:
                os.chdir(previous)
            path = base / "locale" / "en" / "LC_MESSAGES" / "django.po"
            if not path.exists() or not path.read_text().strip():
                return set()
            return {entry.msgid for entry in polib.pofile(str(path))}

    def test_notes_and_node_modules_are_never_extracted(self):
        self.assertEqual(self.extract(), {"app_only"})

    def test_a_given_ignore_pattern_is_kept_next_to_the_fixed_ones(self):
        self.assertEqual(self.extract(ignore=["app/*"]), set())
