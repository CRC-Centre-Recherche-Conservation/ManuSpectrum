"""Align the Import Biblissima workflow UI gate with the API gate.

The api/biblissima/* endpoints are gated on EDITOR_GROUPS membership; opening
the workflow UI additionally requires the guardian object permission
``view_plugin`` on the Plugin row (arches PluginView). This command grants
that permission to every editor group so that "may call the API" implies
"may open the UI". Idempotent — safe to re-run on every deploy.
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from guardian.shortcuts import assign_perm

from arches.app.models.models import Plugin
from manuspectrum.views.permissions import EDITOR_GROUPS

PLUGIN_SLUG = "import-biblissima-workflow"


class Command(BaseCommand):
    help = (
        "Grant view_plugin on the Import Biblissima workflow plugin to every "
        "editor group (see manuspectrum.views.permissions.EDITOR_GROUPS). "
        "Idempotent; run after load_package and on each deploy."
    )

    def handle(self, *args, **options):
        try:
            plugin = Plugin.objects.get(slug=PLUGIN_SLUG)
        except Plugin.DoesNotExist:
            raise CommandError(
                f"Plugin '{PLUGIN_SLUG}' not found. Load the package first "
                "(python manage.py packages -o load_package -s pkg -db -y), "
                "then re-run this command."
            )

        for group_name in EDITOR_GROUPS:
            try:
                group = Group.objects.get(name=group_name)
            except Group.DoesNotExist:
                self.stderr.write(
                    self.style.WARNING(f"Group '{group_name}' not found — skipped.")
                )
                continue
            assign_perm("view_plugin", group, plugin)
            self.stdout.write(f"view_plugin -> {group_name}")

        self.stdout.write(self.style.SUCCESS("Import Biblissima UI permissions set."))
