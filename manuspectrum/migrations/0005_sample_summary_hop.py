"""The Sample summary follows ``analysis.sample_used`` instead of ``analysis_observed``.

Rewrites that single hop in the stored ``functions_x_graphs`` row of the live
Sample model (the graph without ``source_identifier``, never a draft copy), and
nothing else in it: the rest of the row is curated. Idempotent; a
database without the Sample model or without the row is left alone, and a fresh
database gets the corrected seed from 0004.
"""

from django.db import migrations

from manuspectrum.functions.resource_summary import SUMMARY_FUNCTION_ID

OLD_HOP = {
    "graph_slug": "analysis",
    "alias": "analysis_observed",
    "direction": "incoming",
}
NEW_ALIAS = "sample_used"


def fix_sample_hop(apps, schema_editor):
    FunctionXGraph = apps.get_model("models", "FunctionXGraph")
    GraphModel = apps.get_model("models", "GraphModel")
    graphs = list(
        GraphModel.objects.filter(
            slug="sample", isresource=True, source_identifier__isnull=True
        )
    )
    if len(graphs) != 1:
        return
    graph = graphs[0]
    for row in FunctionXGraph.objects.filter(
        function_id=SUMMARY_FUNCTION_ID, graph_id=graph.graphid
    ):
        config = row.config or {}
        changed = False
        for rollup in config.get("rollups") or []:
            for hop in rollup.get("path") or []:
                if hop == OLD_HOP:
                    hop["alias"] = NEW_ALIAS
                    changed = True
        if changed:
            row.config = config
            row.save(update_fields=["config"])


class Migration(migrations.Migration):
    dependencies = [
        ("manuspectrum", "0004_resource_summary"),
        ("models", "9053_add_future_graphs"),
    ]

    operations = [migrations.RunPython(fix_sample_hop, migrations.RunPython.noop)]
