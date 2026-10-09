"""Application order in `INSTALLED_APPS`."""

import os

from django.conf import settings
from django.core.management import call_command, get_commands
from django.template.loader import get_template
from django.test import SimpleTestCase

# Template names that the project, arches_vue_components and
# arches_controlled_lists all provide; the project copy must keep winning.
SHADOWED_TEMPLATES = (
    "javascript.htm",
    "index.htm",
    "arches_urls.htm",
    "custom_email_css.htm",
    "custom_email_footer.htm",
    "custom_email_header.htm",
    "email/general_notification.htm",
    "email/download_ready_email_notification.htm",
    "email/package_load_complete_email_notification.htm",
    "html_export/example-000000-0000-0000-0000-0000001.htm",
)


class InstalledAppsOrderTests(SimpleTestCase):
    databases = {"default"}

    def test_controlled_lists_precede_arches(self):
        apps = list(settings.INSTALLED_APPS)
        self.assertLess(apps.index("arches_controlled_lists"), apps.index("arches"))

    def test_packages_command_is_the_controlled_lists_subclass(self):
        self.assertEqual(get_commands()["packages"], "arches_controlled_lists")

    def test_project_templates_still_win(self):
        templates_dir = os.path.join(settings.APP_ROOT, "templates")
        for name in SHADOWED_TEMPLATES:
            with self.subTest(template=name):
                origin = get_template(name).origin.name
                self.assertTrue(origin.startswith(templates_dir + os.sep), origin)

    def test_no_pending_model_change(self):
        call_command("makemigrations", check=True, dry_run=True, verbosity=0)
