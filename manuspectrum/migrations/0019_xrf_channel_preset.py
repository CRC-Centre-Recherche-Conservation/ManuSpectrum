"""Seed the « XRF — channel / counts » viewer preset on existing databases.

Only this preset is upserted; the reverse does nothing because tile data may
point at the row by id.
"""

from django.db import migrations

from manuspectrum.constants.xy_presets import XY_PRESETS, XY_RENDERER_ID


def seed_channel_preset(apps, schema_editor):
    RendererConfig = apps.get_model("manuspectrum", "RendererConfig")
    preset = XY_PRESETS["xrf_channel"]
    RendererConfig.objects.update_or_create(
        configid=preset["config_id"],
        defaults={
            "rendererid": XY_RENDERER_ID,
            "name": preset["name"],
            "description": preset["description"],
            "config": preset["config"],
        },
    )


class Migration(migrations.Migration):
    dependencies = [("manuspectrum", "0018_arches_json_importer_access")]

    operations = [migrations.RunPython(seed_channel_preset, migrations.RunPython.noop)]
