"""Collapse the two multi-Y settings into one exclusive choice.

A configuration used to carry two independent settings that answered the same
question — "several Y columns remain, what do we plot?":

* ``transformation: "mean"``, applied at parse time, collapsing every Y column
  into a single averaged series;
* a ``transforms`` chain, applied afterwards, which could hold
  ``reference-normalize`` — dividing the measurements by the column tagged as
  the white reference.

Both could be set at once, and together they silently did nothing: ``mean``
leaves a single series, which carries no ``reference`` role, so the
normalisation found nothing to divide by and handed the data back untouched. A
curator saw the same two curves either way, with no way to tell the step had
been skipped.

As a single enum that state cannot be written down at all, which is a stronger
guarantee than validating against it after the fact.

The chain also stops being free-form: only corrective steps may live in a
stored configuration, and today ``reference-normalize`` is the only one. A way
of *looking* at correct data — a derivative, smoothing, log(1/R) — belongs to
the reader, not to a row every analysis of that technique shares.
"""

from django.db import migrations

from manuspectrum.constants.xy_presets import (
    MULTI_Y_MEAN,
    MULTI_Y_REFERENCE,
    MULTI_Y_SEPARATE,
    TRANSFORM_REFERENCE_NORMALIZE,
    XY_PRESETS,
)

LEGACY_KEYS = ("transformation", "transforms")


def choice_from_legacy(config):
    """Read the single answer out of the two settings that used to encode it.

    ``mean`` wins when both are present: it ran first, at parse time, and left
    the normalisation nothing to work with. Reproducing what the curator
    actually saw beats honouring an intent the old code never carried out.
    """
    if config.get("transformation") == MULTI_Y_MEAN:
        return MULTI_Y_MEAN
    for step in config.get("transforms") or []:
        step_type = step if isinstance(step, str) else (step or {}).get("type")
        if step_type == TRANSFORM_REFERENCE_NORMALIZE:
            return MULTI_Y_REFERENCE
    return MULTI_Y_SEPARATE


def to_single_choice(apps, schema_editor):
    RendererConfig = apps.get_model("manuspectrum", "RendererConfig")
    seeded = {preset["config_id"]: preset for preset in XY_PRESETS.values()}

    for row in RendererConfig.objects.all():
        config = row.config or {}
        preset = seeded.get(str(row.configid))
        if preset:
            # Seeded rows are re-derived rather than converted: the constants
            # are the source of truth for them.
            row.config = preset["config"]
        else:
            config = dict(config)
            config["multiYHandling"] = choice_from_legacy(config)
            for key in LEGACY_KEYS:
                config.pop(key, None)
            row.config = config
        row.save(update_fields=["config"])


def back_to_two_settings(apps, schema_editor):
    RendererConfig = apps.get_model("manuspectrum", "RendererConfig")
    for row in RendererConfig.objects.all():
        config = dict(row.config or {})
        choice = config.pop("multiYHandling", MULTI_Y_SEPARATE)
        config["transformation"] = MULTI_Y_MEAN if choice == MULTI_Y_MEAN else None
        config["transforms"] = (
            [{"type": TRANSFORM_REFERENCE_NORMALIZE}]
            if choice == MULTI_Y_REFERENCE
            else []
        )
        row.config = config
        row.save(update_fields=["config"])


class Migration(migrations.Migration):

    dependencies = [("manuspectrum", "0002_xy_technique_config")]

    operations = [migrations.RunPython(to_single_choice, back_to_two_settings)]
