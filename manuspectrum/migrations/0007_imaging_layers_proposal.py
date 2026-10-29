"""Register the « Imaging layers proposal » function and bind it to the Analysis graph."""

from django.db import migrations

from manuspectrum.constants.imaging_layers import (
    ANALYSIS_GRAPH_ID,
    IMAGING_MANIFEST_NODEGROUP_ID,
)
from manuspectrum.functions.imaging_layers_proposal import details

FUNCTION_ID = details["functionid"]


def register_function(apps, schema_editor):
    Function = apps.get_model("models", "Function")
    FunctionXGraph = apps.get_model("models", "FunctionXGraph")
    GraphModel = apps.get_model("models", "GraphModel")

    Function.objects.update_or_create(
        functionid=FUNCTION_ID,
        defaults={
            "name": details["name"],
            "functiontype": details["type"],
            "description": details["description"],
            "defaultconfig": details["defaultconfig"],
            "modulename": "imaging_layers_proposal.py",
            "classname": details["classname"],
            "component": details["component"],
        },
    )

    # A database that has not loaded the package yet has no Analysis graph.
    if GraphModel.objects.filter(graphid=ANALYSIS_GRAPH_ID).exists():
        FunctionXGraph.objects.update_or_create(
            function_id=FUNCTION_ID,
            graph_id=ANALYSIS_GRAPH_ID,
            defaults={
                "config": {"triggering_nodegroups": [IMAGING_MANIFEST_NODEGROUP_ID]}
            },
        )


def unregister_function(apps, schema_editor):
    Function = apps.get_model("models", "Function")
    FunctionXGraph = apps.get_model("models", "FunctionXGraph")

    FunctionXGraph.objects.filter(function_id=FUNCTION_ID).delete()
    Function.objects.filter(functionid=FUNCTION_ID).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0006_data_change_ledger"),
        ("models", "0001_initial"),
    ]

    operations = [migrations.RunPython(register_function, unregister_function)]
