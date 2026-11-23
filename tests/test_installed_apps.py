"""Application order in `INSTALLED_APPS`."""

import os

from django.conf import settings
from django.core.management import call_command, get_commands
from django.template.loader import get_template
from django.test import SimpleTestCase

# Template names that the project, arches.extensions.vue_components and
# arches.extensions.controlled_lists all provide; the project copy must keep winning.
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

    def test_bundled_apps_precede_arches_in_their_required_order(self):
        apps = list(settings.INSTALLED_APPS)
        bundled = [
            "arches.extensions.querysets",
            "arches.extensions.vue_components",
            "arches.extensions.controlled_lists",
        ]
        positions = [apps.index(name) for name in [*bundled, "arches"]]
        self.assertEqual(positions, sorted(positions))

    def test_packages_command_is_the_controlled_lists_subclass(self):
        self.assertEqual(
            get_commands()["packages"], "arches.extensions.controlled_lists"
        )

    def test_validate_command_is_the_vue_components_override(self):
        self.assertEqual(get_commands()["validate"], "arches.extensions.vue_components")

    def test_project_templates_still_win(self):
        templates_dir = os.path.join(settings.APP_ROOT, "templates")
        for name in SHADOWED_TEMPLATES:
            with self.subTest(template=name):
                origin = get_template(name).origin.name
                self.assertTrue(origin.startswith(templates_dir + os.sep), origin)

    def test_no_pending_model_change(self):
        call_command("makemigrations", check=True, dry_run=True, verbosity=0)
