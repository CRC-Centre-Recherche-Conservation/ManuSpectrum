"""Show the Arches JSON importer (Arches 8.2) to Resource Editor.

The Bulk Data Manager module `arches-json-importer` ("Import Arches JSON") is an
import module: it follows the rule of `0016_workflow_plugin_access` for the
other imports and is shown to « Resource Editor » only (`view_etlmodule`).
The grant is written the way 0016 writes its own, through the same helpers; the
module is created by Arches' `12946_arches_json_importer`, and its absence is an
error. Running this again adds nothing; the reverse does nothing, as 0016's.
"""

from importlib import import_module

from django.db import migrations

access = import_module("manuspectrum.migrations.0016_workflow_plugin_access")

ARCHES_JSON_IMPORTER = (
    "0a1c9d67-8b4e-4f2a-9d31-6c5b2e7a4f18",
    "arches-json-importer",
    (access.EDITOR,),
)


def grant_arches_json_importer(apps, schema_editor):
    ETLModule = apps.get_model("models", "ETLModule")
    permission = access.object_permission(
        apps, schema_editor.connection.alias, "etlmodule", "view_etlmodule"
    )
    moduleid, slug, groups = ARCHES_JSON_IMPORTER
    module = ETLModule.objects.filter(pk=moduleid).first()
    if module is None:
        raise RuntimeError(f"ETL module {slug} ({moduleid}) is not registered.")
    access.grant_rows(
        apps,
        permission,
        access.get_content_type(ETLModule).pk,
        [(module, groups)],
    )


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0017_openfreemap_basemap_on_arches_82"),
        ("models", "12946_arches_json_importer"),
    ]

    operations = [
        migrations.RunPython(grant_arches_json_importer, migrations.RunPython.noop)
    ]
