"""Register the workflow plugins of `manuspectrum/workflows/*.json`.

Does what `manage.py plugin register` does for each file, once and without
touching a plugin that is already there (same id or same slug).
"""

import json
from pathlib import Path

from django.db import migrations

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"


def register_plugins(apps, schema_editor):
    Plugin = apps.get_model("models", "Plugin")

    for source in sorted(WORKFLOWS_DIR.glob("*.json")):
        with open(source, encoding="utf-8") as f:
            details = json.load(f)

        if Plugin.objects.filter(pluginid=details["pluginid"]).exists():
            continue
        if Plugin.objects.filter(slug=details["slug"]).exists():
            continue

        Plugin.objects.create(
            pluginid=details["pluginid"],
            name=details["name"],
            icon=details["icon"],
            component=details["component"],
            componentname=details["componentname"],
            config=details["config"],
            slug=details["slug"],
            sortorder=details["sortorder"],
            helptemplate=details.get("helptemplate"),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0007_imaging_layers_proposal"),
        ("models", "9558_add_plugin_help"),
    ]

    operations = [migrations.RunPython(register_plugins, migrations.RunPython.noop)]
