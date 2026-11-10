"""Rewrite the per-language rows of the current graph publications from the graph tables.

Arches 8.1.5 (`arches/app/models/graph.py`, `arches/app/utils/i18n.py`):
`i18n synclanguages` and `packages` call `Graph.update_published_graphs()` on
graphs loaded from their publication in the active language, so every language
row receives that language's card names, help texts and widget labels. Each
graph is loaded from its tables, as `Graph.publish()` does, and Arches'
`update_published_graphs()` rewrites the rows of its CURRENT publication: no new
publication, resources keep theirs. Drafts and graphs with unpublished changes
are skipped. Each run adds one `published_graph_edits` row per graph.

Drop this command when core loads published graphs from their tables.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import translation

from arches.app.models.graph import Graph
from arches.app.models.models import GraphModel


class Command(BaseCommand):
    help = "Rewrite the language rows of each current graph publication from the graph tables"

    def handle(self, *args, **options):
        rewritten = skipped = 0
        graphs = GraphModel.objects.filter(
            publication__isnull=False, source_identifier__isnull=True
        ).order_by("slug", "graphid")
        for row in graphs:
            label = f"{row.name} ({row.graphid})"
            if row.has_unpublished_changes:
                self.stdout.write(f"Skipped {label}: unpublished changes")
                skipped += 1
                continue
            # The graph is read from the row of the active language, which
            # must exist in its publication.
            with translation.override(settings.LANGUAGE_CODE):
                graph = Graph.objects.get(pk=row.graphid)
                graph.refresh_from_database()
                # refresh_from_database() raises the flag in memory.
                graph.has_unpublished_changes = False
                graph.update_published_graphs(
                    notes="republish_graph_translations: rebuilt from the graph tables"
                )
            self.stdout.write(f"Rewrote {label}")
            rewritten += 1
        self.stdout.write(f"{rewritten} graph(s) rewritten, {skipped} skipped")
