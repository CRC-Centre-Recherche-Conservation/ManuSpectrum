import importlib
import json
import tempfile
from pathlib import Path
from unittest import mock

from arches.app.models.models import Plugin
from django.apps import apps
from django.test import TestCase

migration = importlib.import_module("manuspectrum.migrations.0015_init_workflow_name")

OLD_NAME = {"en": "Workflows", "fr": "Assistants"}


def launcher():
    details = json.loads(Path(migration.SOURCE).read_text(encoding="utf-8"))
    return Plugin.objects.get(pluginid=details["pluginid"])


def name_of(plugin):
    plugin.refresh_from_db()
    return plugin.name.serialize(use_raw_i18n_json=True)


class InitWorkflowRenameTests(TestCase):
    def old_name(self):
        plugin = launcher()
        plugin.name = OLD_NAME
        plugin.save()
        self.assertEqual(name_of(plugin)["fr"], "Assistants")
        return plugin

    def test_the_old_french_name_becomes_the_one_of_the_json(self):
        plugin = self.old_name()
        migration.rename_launcher(apps, None)
        self.assertEqual(name_of(plugin)["fr"], "Workflows")

    def test_only_the_name_is_written(self):
        plugin = self.old_name()
        before = (plugin.slug, plugin.component, plugin.icon)
        migration.rename_launcher(apps, None)
        plugin.refresh_from_db()
        self.assertEqual((plugin.slug, plugin.component, plugin.icon), before)

    def test_the_reverse_keeps_the_new_name(self):
        plugin = self.old_name()
        migration.rename_launcher(apps, None)
        migration.Migration.operations[0].reverse_code(apps, None)
        self.assertEqual(name_of(plugin)["fr"], "Workflows")

    def test_a_json_still_holding_the_old_name_leaves_the_old_name(self):
        plugin = self.old_name()
        details = json.loads(Path(migration.SOURCE).read_text(encoding="utf-8"))
        details["name"] = OLD_NAME
        with tempfile.TemporaryDirectory() as folder:
            copy = Path(folder) / "init_workflow.json"
            copy.write_text(json.dumps(details), encoding="utf-8")
            with mock.patch.object(migration, "SOURCE", copy):
                migration.rename_launcher(apps, None)
        self.assertEqual(name_of(plugin)["fr"], "Assistants")
