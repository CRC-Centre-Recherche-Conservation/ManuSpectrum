import importlib
import json
from pathlib import Path

from django.apps import apps
from django.db import connection
from django.test import TestCase

from arches.app.models.models import Plugin

migration = importlib.import_module("manuspectrum.migrations.0008_workflow_plugins")

WORKFLOWS = sorted(Path(migration.WORKFLOWS_DIR).glob("*.json"))


def snapshot():
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM plugins ORDER BY pluginid")
        return [tuple(str(v) for v in row) for row in cursor.fetchall()]


def details():
    return [json.loads(p.read_text(encoding="utf-8")) for p in WORKFLOWS]


class WorkflowPluginsTests(TestCase):
    def test_the_migration_depends_on_the_core_migration_adding_the_help_field(self):
        self.assertIn(
            ("models", "9558_add_plugin_help"), migration.Migration.dependencies
        )

    def test_three_workflow_files(self):
        self.assertEqual(len(WORKFLOWS), 3)

    def test_plugins_registered_with_json_ids_slugs_names(self):
        for d in details():
            plugin = Plugin.objects.get(pluginid=d["pluginid"])
            self.assertEqual(plugin.slug, d["slug"])
            self.assertEqual(plugin.componentname, d["componentname"])
            self.assertEqual(plugin.name.serialize(use_raw_i18n_json=True), d["name"])
            self.assertEqual(plugin.component, d["component"])

    def test_forward_on_empty_table_creates_them(self):
        Plugin.objects.filter(pluginid__in=[d["pluginid"] for d in details()]).delete()
        migration.register_plugins(apps, None)
        self.assertEqual(
            Plugin.objects.filter(
                pluginid__in=[d["pluginid"] for d in details()]
            ).count(),
            3,
        )

    def test_running_twice_changes_nothing(self):
        before = snapshot()
        migration.register_plugins(apps, None)
        migration.register_plugins(apps, None)
        self.assertEqual(snapshot(), before)

    def test_existing_row_is_not_modified(self):
        d = details()[0]
        Plugin.objects.filter(pluginid=d["pluginid"]).update(icon="fa fa-custom")
        migration.register_plugins(apps, None)
        self.assertEqual(
            Plugin.objects.get(pluginid=d["pluginid"]).icon, "fa fa-custom"
        )
