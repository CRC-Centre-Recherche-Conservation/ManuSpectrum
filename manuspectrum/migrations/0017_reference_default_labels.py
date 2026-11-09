"""Give the reference widget defaults the labels of their list item (#290).

The data package shipped 22 reference widget defaults (« preferred terms »,
« PeriodO », « count (sum total) ») with the English prefLabel only. The
reference-select widget renders the prefLabel of the active language with no
fallback, so under /fr/ these fields show "Unlabeled Item", and a resource saved
with the default stores the English-only value.

This runs `manuspectrum.utils.reference_labels.repair_reference_defaults` once
on an existing database: every default lacking a prefLabel in a language of
`settings.LANGUAGES` is replaced, in place, by its list item's labels, in
`cards_x_nodes_x_widgets` and in the serialized graphs of the current
publication of each graph. No new publication is made: resources stay on the
publication they are pinned to and stay editable (#288, #289).

On a fresh database (`setup_db`) there is no graph yet and nothing to do: `init`
(deploy/docker/entrypoint.sh) and the local installation steps of README.md
run the `repair_reference_defaults` command after `load_package`. The repair
reads named columns only, so a column added later by Arches or
arches-controlled-lists does not break this migration on a fresh database.

The values already saved in tiles are left to `refresh_reference_labels`, which
also recomputes the descriptors of the resources it changes and reindexes them.

Reverse is a no-op: the English-only defaults are not worth restoring.
"""

from django.db import migrations


def complete_defaults(apps, schema_editor):
    from manuspectrum.utils.reference_labels import repair_reference_defaults

    repair_reference_defaults(using=schema_editor.connection.alias)


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0016_workflow_plugin_access"),
        # The last Arches 8.1 migration: graphs, nodes, cards_x_nodes_x_widgets
        # and published graphs exist in the form the repair reads.
        ("models", "12586_tile_cardinality_check"),
        ("arches_controlled_lists", "0011_add_reference_select_widget_mapping"),
    ]

    operations = [migrations.RunPython(complete_defaults, migrations.RunPython.noop)]
