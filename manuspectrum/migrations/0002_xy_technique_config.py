"""Seed the XY viewer presets and wire up the technique -> config function.

This is the **only** migration that writes preset rows, and it reads
``XY_PRESETS`` live rather than a frozen copy. Two consequences worth knowing
before touching it:

* **Adding or changing a preset needs no migration.** Edit ``xy_presets.py``;
  a database created afterwards is seeded with the new shape. Only a database
  that already ran this migration needs the seed re-running by hand, and until
  the first production deploy there is exactly one of those.
* **The reasoning does not live here.** Three migrations used to re-derive
  these same rows — one seeding them, one collapsing the two multi-Y settings
  into a single exclusive choice, one stamping ``presetKey``. The last two were
  squashed away once their result was the shape this seed already produces;
  their rationale is in ``xy_presets.py``, next to the constants it explains,
  where it is read rather than archived.
"""

from django.db import migrations

from manuspectrum.constants.xy_presets import (
    ANALYSIS_GRAPH_ID,
    DATA_FILE_NODEGROUP_ID,
    TECHNIQUE_NODEGROUP_ID,
    XY_PRESETS,
    XY_RENDERER_ID,
)

FUNCTION_ID = "0f5a9c74-8e21-4c3d-b6f7-91d2ae4c5b08"


def seed_presets(apps, schema_editor):
    RendererConfig = apps.get_model("manuspectrum", "RendererConfig")
    for preset in XY_PRESETS.values():
        RendererConfig.objects.update_or_create(
            configid=preset["config_id"],
            defaults={
                "rendererid": XY_RENDERER_ID,
                # RendererConfig has a plain TextField name and no i18n
                # machinery, so a French label could only replace the English
                # one, never sit beside it. Both stay English; the description
                # describes rather than translates.
                "name": preset["name"],
                "description": preset["description"],
                "config": preset["config"],
            },
        )


def drop_presets(apps, schema_editor):
    RendererConfig = apps.get_model("manuspectrum", "RendererConfig")
    RendererConfig.objects.filter(
        configid__in=[p["config_id"] for p in XY_PRESETS.values()]
    ).delete()


def register_function(apps, schema_editor):
    Function = apps.get_model("models", "Function")
    FunctionXGraph = apps.get_model("models", "FunctionXGraph")
    GraphModel = apps.get_model("models", "GraphModel")

    triggering = [TECHNIQUE_NODEGROUP_ID, DATA_FILE_NODEGROUP_ID]

    Function.objects.update_or_create(
        functionid=FUNCTION_ID,
        defaults={
            "name": "XY Technique Configuration",
            "functiontype": "node",
            "description": (
                "Applies a default XY viewer configuration to measurement "
                "files, derived from the analysis technique, without ever "
                "overwriting a configuration chosen by a curator."
            ),
            "defaultconfig": {"triggering_nodegroups": triggering},
            "modulename": "xy_technique_config.py",
            "classname": "XYTechniqueConfig",
            "component": "views/components/functions/xy-technique-config",
        },
    )

    # Only attach when the Analysis graph is present, so a fresh database that
    # has not yet loaded the package still migrates cleanly.
    if GraphModel.objects.filter(graphid=ANALYSIS_GRAPH_ID).exists():
        FunctionXGraph.objects.update_or_create(
            function_id=FUNCTION_ID,
            graph_id=ANALYSIS_GRAPH_ID,
            defaults={"config": {"triggering_nodegroups": triggering}},
        )


def unregister_function(apps, schema_editor):
    Function = apps.get_model("models", "Function")
    FunctionXGraph = apps.get_model("models", "FunctionXGraph")

    FunctionXGraph.objects.filter(function_id=FUNCTION_ID).delete()
    Function.objects.filter(functionid=FUNCTION_ID).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0001_initial"),
        # Function / FunctionXGraph / GraphModel have existed since the first
        # Arches migration; depending on the tip would break on every upgrade.
        ("models", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_presets, drop_presets),
        migrations.RunPython(register_function, unregister_function),
    ]
