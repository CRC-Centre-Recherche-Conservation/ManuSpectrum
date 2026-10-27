"""Who opens the workflows and the Arches data-management tools (migration 0016).

Usage:
    python manage.py test tests.test_workflow_plugin_access --settings="tests.test_settings"
"""

import importlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from guardian.models import GroupObjectPermission

from arches.app.models.models import ETLModule, Plugin
from arches_controlled_lists.etl_modules.migrate_to_reference_datatype import (
    details as MIGRATE_TO_REFERENCE,
)

migration = importlib.import_module(
    "manuspectrum.migrations.0016_workflow_plugin_access"
)

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "manuspectrum" / "workflows"
SCHEMA_EDITOR = SimpleNamespace(connection=connection)

PLUGIN_GROUPS = {
    "init-workflow": {"Resource Editor"},
    "create-project-workflow": {"Resource Editor"},
    "import-biblissima-workflow": {"Resource Editor"},
    "bulk-data-manager": {"Resource Editor"},
    "image-service-manager": {
        "Guest",
        "Resource Editor",
        "Resource Reviewer",
        "Crowdsource Editor",
        "Resource Exporter",
        "Graph Editor",
        "RDM Administrator",
        "Application Administrator",
        "System Administrator",
        "Mobile Project Administrator",
    },
    "controlled-list-manager": {"RDM Administrator"},
}

ETL_GROUPS = {
    "branch-excel-importer": {"Resource Editor"},
    "tile-excel-importer": {"Resource Editor"},
    "import-single-csv": {"Resource Editor"},
    "jsonld-importer": {"Resource Editor"},
    "bulk-replace-editor": {"Resource Editor"},
    "bulk-trim-editor": {"Resource Editor"},
    "bulk-case-editor": {"Resource Editor"},
    "bulk_edit_concept": {"Resource Editor"},
    "migrate-to-reference-datatype": {"Resource Editor"},
    "branch-excel-exporter": {"Resource Exporter"},
    "tile-excel-exporter": {"Resource Exporter"},
    "bulk-data-deletion": set(),
}


def workflow_slugs():
    return sorted(
        json.loads(path.read_text(encoding="utf-8"))["slug"]
        for path in WORKFLOWS_DIR.glob("*.json")
    )


def granted_groups(obj, codename):
    return set(
        GroupObjectPermission.objects.filter(
            permission__codename=codename, object_pk=str(obj.pk)
        ).values_list("group__name", flat=True)
    )


def all_grants():
    return sorted(
        GroupObjectPermission.objects.filter(
            permission__codename__in=("view_plugin", "view_etlmodule")
        ).values_list("group__name", "permission__codename", "object_pk")
    )


def member(*groups, username="member"):
    user = User.objects.create_user(username=username, password=None)
    for name in groups:
        user.groups.add(Group.objects.get(name=name))
    return user


class GrantTests(TestCase):
    def test_every_workflow_plugin_is_granted_to_resource_editor(self):
        editor = member("Resource Editor")
        for slug in workflow_slugs():
            with self.subTest(workflow=slug):
                plugin = Plugin.objects.get(slug=slug)
                self.assertTrue(editor.has_perm("view_plugin", plugin))
                self.assertEqual(
                    granted_groups(plugin, "view_plugin"), PLUGIN_GROUPS[slug]
                )

    def test_each_tool_is_granted_to_its_groups_only(self):
        for slug, groups in PLUGIN_GROUPS.items():
            with self.subTest(plugin=slug):
                plugin = Plugin.objects.get(slug=slug)
                self.assertEqual(granted_groups(plugin, "view_plugin"), groups)

    def test_each_etl_module_is_granted_to_its_groups_only(self):
        for module in ETLModule.objects.all():
            with self.subTest(module=module.slug):
                self.assertEqual(
                    granted_groups(module, "view_etlmodule"), ETL_GROUPS[module.slug]
                )

    def test_running_twice_adds_nothing(self):
        before = all_grants()
        migration.grant_access(apps, SCHEMA_EDITOR)
        migration.grant_access(apps, SCHEMA_EDITOR)
        self.assertEqual(all_grants(), before)

    def test_a_missing_plugin_is_an_error(self):
        Plugin.objects.filter(slug="create-project-workflow").delete()
        with self.assertRaises(RuntimeError):
            migration.grant_access(apps, SCHEMA_EDITOR)

    def test_a_missing_arches_etl_module_is_an_error(self):
        ETLModule.objects.filter(slug="jsonld-importer").delete()
        with self.assertRaises(RuntimeError):
            migration.grant_access(apps, SCHEMA_EDITOR)

    def test_the_hand_registered_module_is_skipped_when_absent(self):
        ETLModule.objects.filter(slug="migrate-to-reference-datatype").delete()
        self.assertFalse(
            ETLModule.objects.filter(slug="migrate-to-reference-datatype").exists()
        )
        before = all_grants()
        migration.grant_access(apps, SCHEMA_EDITOR)
        self.assertEqual(all_grants(), before)

    def test_the_hand_registered_module_is_granted_when_present(self):
        ETLModule.objects.filter(slug="migrate-to-reference-datatype").delete()
        module = ETLModule.objects.create(
            etlmoduleid=MIGRATE_TO_REFERENCE["etlmoduleid"],
            name=MIGRATE_TO_REFERENCE["name"],
            description=MIGRATE_TO_REFERENCE["description"],
            etl_type=MIGRATE_TO_REFERENCE["etl_type"],
            component=MIGRATE_TO_REFERENCE["component"],
            componentname=MIGRATE_TO_REFERENCE["componentname"],
            modulename=MIGRATE_TO_REFERENCE["modulename"],
            classname=MIGRATE_TO_REFERENCE["classname"],
            config=MIGRATE_TO_REFERENCE["config"],
            icon=MIGRATE_TO_REFERENCE["icon"],
            slug=MIGRATE_TO_REFERENCE["slug"],
        )
        migration.grant_access(apps, SCHEMA_EDITOR)
        self.assertEqual(granted_groups(module, "view_etlmodule"), {"Resource Editor"})

    def test_a_missing_group_is_skipped(self):
        GroupObjectPermission.objects.filter(
            permission__codename__in=("view_plugin", "view_etlmodule")
        ).delete()
        Group.objects.filter(name="Resource Reviewer").delete()
        migration.grant_access(apps, SCHEMA_EDITOR)
        names = {name for name, _, _ in all_grants()}
        self.assertEqual(
            names, PLUGIN_GROUPS["image-service-manager"] - {"Resource Reviewer"}
        )


@override_settings(LANGUAGE_CODE="en")
class ArchesPageTests(TestCase):
    def plugin(self, slug):
        return reverse("plugins", kwargs={"slug": slug})

    def history(self):
        return reverse("workflow_history", kwargs={"workflowid": str(uuid.uuid4())})

    def test_a_resource_editor_opens_every_workflow_and_tool(self):
        self.client.force_login(member("Resource Editor"))
        for slug in workflow_slugs() + ["bulk-data-manager", "image-service-manager"]:
            with self.subTest(plugin=slug):
                self.assertEqual(self.client.get(self.plugin(slug)).status_code, 200)

    def test_a_resource_reviewer_opens_the_image_service_manager_only(self):
        self.client.force_login(member("Resource Reviewer"))
        self.assertEqual(
            self.client.get(self.plugin("image-service-manager")).status_code, 200
        )
        for slug in workflow_slugs() + ["bulk-data-manager"]:
            with self.subTest(plugin=slug):
                self.assertEqual(self.client.get(self.plugin(slug)).status_code, 302)

    def test_the_image_service_manager_page_is_open_to_everyone(self):
        url = self.plugin("image-service-manager")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(member("Guest"))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_the_visitor_is_sent_to_sign_in(self):
        response = self.client.get(self.plugin("import-biblissima-workflow"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/auth/"))

    def test_a_guest_and_a_crowdsource_editor_are_sent_to_sign_in(self):
        self.client.force_login(member("Guest", "Crowdsource Editor"))
        for slug in workflow_slugs():
            with self.subTest(plugin=slug):
                self.assertEqual(self.client.get(self.plugin(slug)).status_code, 302)

    def test_arches_keeps_workflow_history_for_resource_editors_only(self):
        self.client.force_login(member("Resource Reviewer", username="reviewer"))
        self.assertEqual(self.client.get(self.history()).status_code, 403)
        self.client.force_login(member("Resource Editor", username="editor"))
        self.assertEqual(self.client.get(self.history()).status_code, 200)

    def test_the_bulk_data_manager_lists_the_modules_of_its_groups(self):
        self.client.force_login(member("Resource Editor", "Resource Exporter"))
        response = self.client.get(reverse("etl_manager"), {"action": "modules"})
        self.assertEqual(response.status_code, 200)
        listed = {m["slug"] for m in response.json()}
        shown = {
            m.slug
            for m in ETLModule.objects.all()
            if m.config.get("show", True) is not False
        }
        expected = {
            slug for slug, groups in ETL_GROUPS.items() if groups and slug in shown
        }
        self.assertEqual(listed, expected)
        self.assertNotIn("bulk-data-deletion", listed)
