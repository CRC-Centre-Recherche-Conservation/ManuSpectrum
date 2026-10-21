"""Give the workflow launcher plugin its current name from `workflows/init_workflow.json`.

0008 registers a plugin only when it is missing, so a database migrated before
the French name changed keeps the old one. Only the name is written. The
reverse does nothing: the new name stays.
"""

import json
from pathlib import Path

from django.db import migrations

SOURCE = Path(__file__).resolve().parent.parent / "workflows" / "init_workflow.json"


def rename_launcher(apps, schema_editor):
    Plugin = apps.get_model("models", "Plugin")
    with open(SOURCE, encoding="utf-8") as f:
        details = json.load(f)
    Plugin.objects.filter(pluginid=details["pluginid"]).update(name=details["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0014_site_notice"),
    ]

    operations = [migrations.RunPython(rename_launcher, migrations.RunPython.noop)]
