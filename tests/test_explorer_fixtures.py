"""The Explorer test fixtures leave the settings as they found them.

Usage:
    python manage.py test tests.test_explorer_fixtures --settings="tests.test_settings"
"""

from django.conf import settings
from django.test import override_settings

from tests.explorer_fixtures import ExplorerCase


class StoredFileSettingsTests(ExplorerCase):
    def test_a_stored_file_in_a_decorated_test_does_not_leak_the_decoration(self):
        before = settings.SPECTRUM_PREVIEW_MAX_BYTES

        @override_settings(SPECTRUM_PREVIEW_MAX_BYTES=before + 1)
        def decorated_test():
            self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n3,4\n")

        decorated_test()
        self.doCleanups()

        self.assertEqual(settings.SPECTRUM_PREVIEW_MAX_BYTES, before)

    def test_the_media_root_of_a_test_does_not_outlive_it(self):
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n3,4\n")
        during = settings.MEDIA_ROOT

        self.doCleanups()

        self.assertNotEqual(settings.MEDIA_ROOT, during)
