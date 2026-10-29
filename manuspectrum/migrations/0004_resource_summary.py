"""Registers the Resource Summary function (and attaches it with starting
configurations) and guarantees the descriptor function row exists before any
package load.

``details`` and ``SEED_CONFIGS`` are imported rather than copied: a function id
and its registration metadata have a single source. Each summary attachment is
guarded by the graph's presence, so a database that has not loaded the package
still migrates — its rows appear when the migration is replayed after
``load_package``, and that replay overwrites whatever a curator has configured
since.

The descriptor function was registered by hand and no migration owned it, so a
fresh database had none: ``load_package`` drops a ``functions_x_graphs`` entry
whose Function is unknown without a word (arches/app/models/graph.py:571-592),
which would have taken the ten descriptor attachments with it.
"""

from django.db import migrations

from manuspectrum.constants.summary_configs import SEED_CONFIGS
from manuspectrum.functions.multi_descriptor import details as descriptor_details
from manuspectrum.functions.resource_summary import SUMMARY_FUNCTION_ID, details


def register(apps, schema_editor):
    """Write both Function rows, and the summary attachments only.

    The descriptor function gets its row and nothing else: its per-graph
    templates are curated data, so no ``functions_x_graphs`` row of it is
    created, read or rewritten here.
    """
    Function = apps.get_model("models", "Function")
    FunctionXGraph = apps.get_model("models", "FunctionXGraph")
    GraphModel = apps.get_model("models", "GraphModel")

    Function.objects.update_or_create(
        functionid=descriptor_details["functionid"],
        defaults={
            "name": descriptor_details["name"],
            "functiontype": descriptor_details["type"],
            "description": descriptor_details["description"],
            "defaultconfig": descriptor_details["defaultconfig"],
            "modulename": "multi_descriptor.py",
            "classname": descriptor_details["classname"],
            "component": descriptor_details["component"],
        },
    )

    Function.objects.update_or_create(
        functionid=SUMMARY_FUNCTION_ID,
        defaults={
            "name": details["name"],
            "functiontype": details["type"],
            "description": details["description"],
            "defaultconfig": details["defaultconfig"],
            "modulename": "resource_summary.py",
            "classname": details["classname"],
            "component": details["component"],
        },
    )

    for slug, config in SEED_CONFIGS.items():
        graph = GraphModel.objects.filter(slug=slug, isresource=True).first()
        if graph is None:
            continue
        FunctionXGraph.objects.update_or_create(
            function_id=SUMMARY_FUNCTION_ID,
            graph_id=graph.graphid,
            defaults={"config": config},
        )


def unregister(apps, schema_editor):
    """Undo the summary registration only.

    The descriptor function row predates this migration and is left in place;
    deleting it would cascade its ten curated attachments away.
    """
    Function = apps.get_model("models", "Function")
    FunctionXGraph = apps.get_model("models", "FunctionXGraph")

    FunctionXGraph.objects.filter(function_id=SUMMARY_FUNCTION_ID).delete()
    Function.objects.filter(functionid=SUMMARY_FUNCTION_ID).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0003_xy_config_triggers"),
        # Function / FunctionXGraph / GraphModel have existed since the first
        # Arches migration; depending on the tip would break on every upgrade.
        ("models", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(register, unregister),
    ]
