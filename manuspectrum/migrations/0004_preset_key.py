"""Stamp each seeded configuration with the preset it came from.

The reader-side view control offers the lenses that make sense for an
instrument family — pseudo-absorbance and derivatives for reflectance, total-ion
normalisation for mass spectra — and it needs to know which family a file
belongs to.

The key is an identifier, not a transform. The invariant holds: a configuration
still stores only what turns a file's columns into the physical quantity its
technique measures. The views themselves live in the frontend
(``media/js/utils/xy-views.js``) and are never written to a configuration, so a
lens can never become the stored default for every reader.
"""

from django.db import migrations

from manuspectrum.constants.xy_presets import XY_PRESETS


def stamp_preset_key(apps, schema_editor):
    RendererConfig = apps.get_model("manuspectrum", "RendererConfig")
    for key, preset in XY_PRESETS.items():
        row = RendererConfig.objects.filter(configid=preset["config_id"]).first()
        if not row:
            continue
        config = dict(row.config or {})
        config["presetKey"] = key
        row.config = config
        row.save(update_fields=["config"])


def drop_preset_key(apps, schema_editor):
    RendererConfig = apps.get_model("manuspectrum", "RendererConfig")
    for row in RendererConfig.objects.all():
        config = dict(row.config or {})
        if config.pop("presetKey", None) is not None:
            row.config = config
            row.save(update_fields=["config"])


class Migration(migrations.Migration):

    dependencies = [("manuspectrum", "0003_multi_y_handling")]

    operations = [migrations.RunPython(stamp_preset_key, drop_preset_key)]
