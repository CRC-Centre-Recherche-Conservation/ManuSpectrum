"""The Biblissima concept widget on the Component node « Iconographic representation » (#289).

The data package gives the node the generic URL widget; this assigns the
project's `biblissima-concept-widget` on databases that already hold the
package, in place: the card-node-widget row and the entry of that row in every
language of the graph's current publication. No new publication, so existing
Component resources keep theirs and stay editable. The details, and what is
left alone, are in `manuspectrum/utils/iconographic_widget.py`, frozen for this
migration.

A fresh `setup_db` runs this before the package is loaded: the node is absent
and nothing is done; `init` (and the development setup in README.md) then runs
`manage.py repair_iconographic_widget` after `load_package`. On a database
where the widget is not registered nothing is done and a line says how to
finish by hand. Running it again changes nothing. The reverse does nothing:
the URL widget's placeholders are not kept.
"""

from django.db import migrations

from manuspectrum.utils.iconographic_widget import repair


def assign_concept_widget(apps, schema_editor):
    outcome = repair(schema_editor.connection)
    if outcome.status == "unregistered":
        print(
            "\n  biblissima-concept-widget is not registered: Iconographic "
            "representation keeps the URL widget; run manage.py project update, "
            "then manage.py repair_iconographic_widget"
        )


class Migration(migrations.Migration):

    dependencies = [
        # cards_x_nodes_x_widgets with its draft rows (source_identifier),
        # published_graphs and published_graph_edits.
        ("models", "11959_unique_node_source_widget"),
        ("manuspectrum", "0016_workflow_plugin_access"),
    ]

    operations = [
        migrations.RunPython(assign_concept_widget, migrations.RunPython.noop)
    ]
