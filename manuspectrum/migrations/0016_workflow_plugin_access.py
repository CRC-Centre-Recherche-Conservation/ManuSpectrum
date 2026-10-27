"""Who opens the workflows and the Arches data-management tools.

Arches opens a plugin page only for a holder of the object permission
`view_plugin` on that plugin, and lists a bulk data manager module only for a
holder of `view_etlmodule` on that module (`ETLManagerView.get`,
`action=modules`); a superuser holds both everywhere. Behind those pages,
Arches lets only the group « Resource Editor » write tiles, keep a workflow's
history (`api/workflow.WorkflowHistoryView`) and run the bulk data manager
(`ETLManagerView`), all through `group_required("Resource Editor")`. The grants
follow that rule:

- `view_plugin`: the workflows (launcher `init-workflow`, `create-project-workflow`,
  `import-biblissima-workflow`, registered by `0008_workflow_plugins`) and the
  Bulk Data Manager → Resource Editor; the Image Service Manager → Resource
  Editor and Resource Reviewer. The Controlled List Manager keeps the grant
  `arches_controlled_lists` gives it (RDM Administrator).
- `view_etlmodule`: the import and edit modules → Resource Editor; the
  exporters → Resource Exporter; the bulk deletion module → nobody.

`view_etlmodule` decides which modules the bulk data manager shows; Arches does
not check it again when a module runs, so any Resource Editor can still run the
deletion module or an exporter by a direct request.

Rows are written the way `arches_controlled_lists.0001_initial`
(`assign_view_plugin`) grants its plugin: a `GroupObjectPermission` saved
through the historical model (guardian's `assign_perm` cannot run in a
migration, django-guardian#751), the content type from
`guardian.ctypes.get_content_type`, `object_pk` the row id as text.

Plugin and module ids are frozen here, with the slug of each. A plugin is
found by its id, else by its slug, as 0008 matches it. A plugin or module that
an Arches or project migration creates and that is missing is an error. The
module `migrate-to-reference-datatype` (`arches_controlled_lists`) is
registered by `manage.py etl_module register`, not by a migration: it is
granted when present and skipped otherwise; registered after this migration
has run, it needs a new data migration for its grant. A group missing from the
database is skipped (Arches creates them: `models.0001_initial`, Resource Reviewer in
`models.2891_tile_qa_schema`, Resource Exporter in
`models.8010_export_permissions`).

A new workflow plugin needs a new migration that registers it and grants
`view_plugin` to Resource Editor; `tests/test_workflow_plugin_access.py` fails
until one does. Running this again adds nothing. The reverse does nothing:
it cannot tell its rows from grants made in the admin.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations
from guardian.ctypes import get_content_type

EDITOR = "Resource Editor"
REVIEWER = "Resource Reviewer"
EXPORTER = "Resource Exporter"

# (pluginid, slug, groups)
PLUGINS = (
    ("49507fb0-89c6-47b7-b506-9b2b29a3b8d8", "init-workflow", (EDITOR,)),
    ("3ed8bd97-c00e-492d-94c0-01d34e150aef", "create-project-workflow", (EDITOR,)),
    ("a7f3b2c1-8d4e-4f5a-b6c7-9e0d1f2a3b4c", "import-biblissima-workflow", (EDITOR,)),
    ("7720e9fa-876c-4127-a77a-b099cd2a5d45", "bulk-data-manager", (EDITOR,)),
    (
        "6f707d86-d49c-4ece-9883-8cbb2ecda1b5",
        "image-service-manager",
        (EDITOR, REVIEWER),
    ),
)

# (etlmoduleid, slug, groups, required)
ETL_MODULES = (
    ("3b19a76a-0b09-450e-bee1-65accb096eaf", "branch-excel-importer", (EDITOR,), True),
    ("b96b8078-23b7-484f-b9d0-8ca304a5f7b6", "tile-excel-importer", (EDITOR,), True),
    ("0a0cea7e-b59a-431a-93d8-e9f8c41bdd6b", "import-single-csv", (EDITOR,), True),
    ("1ae62c48-7e56-4df7-a433-2042c6acdf0c", "jsonld-importer", (EDITOR,), True),
    ("9079b83c-e22b-4fdc-a22e-74487ee7b7f3", "bulk-replace-editor", (EDITOR,), True),
    ("80fc7aab-cbd8-4dc0-b55b-5facac4cd157", "bulk-trim-editor", (EDITOR,), True),
    ("e4169b44-124a-4ff6-bd11-5521901f98a7", "bulk-case-editor", (EDITOR,), True),
    ("87ce44cd-3935-49fb-a9ff-37b256d23ec9", "bulk_edit_concept", (EDITOR,), True),
    (
        "b0d3c7e0-7b6f-4a4e-8c8c-1f8a3b9d4d20",
        "migrate-to-reference-datatype",
        (EDITOR,),
        False,
    ),
    (
        "357d11c8-ca38-40ec-926f-1946ccfceb92",
        "branch-excel-exporter",
        (EXPORTER,),
        True,
    ),
    ("63ae4bd2-404a-402f-9917-b18b21215cf2", "tile-excel-exporter", (EXPORTER,), True),
    ("db0e9807-b254-458d-bd62-cfb1da21fe95", "bulk-data-deletion", (), True),
)


def object_permission(apps, using, model, codename):
    # Permissions are otherwise created after the last migration (post_migrate).
    config = apps.get_app_config("models")
    previous = getattr(config, "models_module", None)
    config.models_module = True
    try:
        create_permissions(config, verbosity=0, using=using, apps=apps)
    finally:
        config.models_module = previous
    Permission = apps.get_model("auth", "Permission")
    return Permission.objects.get(
        content_type__app_label="models", content_type__model=model, codename=codename
    )


def grant_rows(apps, permission, content_type_id, targets):
    """Grant ``permission`` on each (object, groups) of ``targets``."""
    Group = apps.get_model("auth", "Group")
    GroupObjectPermission = apps.get_model("guardian", "GroupObjectPermission")
    groups = {g.name: g for g in Group.objects.all()}
    for obj, names in targets:
        for name in names:
            if name not in groups:
                continue
            GroupObjectPermission.objects.get_or_create(
                group=groups[name],
                permission=permission,
                content_type_id=content_type_id,
                object_pk=str(obj.pk),
            )


def grant_plugins(apps, schema_editor):
    Plugin = apps.get_model("models", "Plugin")
    permission = object_permission(
        apps, schema_editor.connection.alias, "plugin", "view_plugin"
    )
    targets = []
    for pluginid, slug, groups in PLUGINS:
        plugin = (
            Plugin.objects.filter(pluginid=pluginid).first()
            or Plugin.objects.filter(slug=slug).first()
        )
        if plugin is None:
            raise RuntimeError(f"Plugin {slug} ({pluginid}) is not registered.")
        targets.append((plugin, groups))
    grant_rows(apps, permission, get_content_type(Plugin).pk, targets)


def grant_etl_modules(apps, schema_editor):
    ETLModule = apps.get_model("models", "ETLModule")
    permission = object_permission(
        apps, schema_editor.connection.alias, "etlmodule", "view_etlmodule"
    )
    targets = []
    for moduleid, slug, groups, required in ETL_MODULES:
        module = ETLModule.objects.filter(pk=moduleid).first()
        if module is None:
            if required:
                raise RuntimeError(f"ETL module {slug} ({moduleid}) is not registered.")
            continue
        targets.append((module, groups))
    grant_rows(apps, permission, get_content_type(ETLModule).pk, targets)


def grant_access(apps, schema_editor):
    grant_plugins(apps, schema_editor)
    grant_etl_modules(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("guardian", "0002_generic_permissions_index"),
        # The last Arches migration creating one of the ETL modules above.
        ("models", "11117_add_bulk_concept_editor"),
        ("manuspectrum", "0008_workflow_plugins"),
        ("manuspectrum", "0015_site_managers_group"),
    ]

    operations = [migrations.RunPython(grant_access, migrations.RunPython.noop)]
