"""
REPUBLISH GRAPH TRANSLATIONS

    manage.py republish_graph_translations [--dry-run]

Rewrites, for every published graph that is not a draft (resource models and
branches), the per-language rows (``published_graphs``) of its CURRENT
publication from the graph tables, one language of ``settings.LANGUAGES`` at a
time.

WHY:
Arches' ``i18n synclanguages`` (and ``packages`` before each graph import)
writes the strings of one language into every language's row: under /fr/ the
models show their English card names, help texts and widget labels although
the tables hold the French ones. ``manuspectrum/utils/graph_translations.py``
has the details.

WHAT IT KEEPS:
The publication itself. No ``graphs_x_published_graphs`` row is created,
``graphs.publicationid`` and ``resource_instances.graphpublicationid`` do not
change, so every existing resource stays editable. A missing language row is
created in the same publication. The write is Arches' own
``Graph.update_published_graphs()``, called on the graph loaded from its
tables, so it also records a ``published_graph_edits`` entry in the
publication's history and refreshes every language row of a graph that has a
differing one.

SKIPPED:
A graph with unpublished changes: its tables hold edits that its publication
does not, and rewriting the publication from them would publish those edits.
Publish it from the Graph Designer.

OPTIONS:
--dry-run: lists the rows that differ from the graph tables (with the parts of
           the serialised graph that differ), writes nothing.

Idempotent: a graph whose rows all equal their rebuild is not written. Each
graph is handled in one transaction that locks its ``graphs`` row, so its
unpublished-changes flag and current publication are read where they are used
and a concurrent publish from the Graph Designer waits. An error (a graph that
cannot be serialised) exits 1, leaves that graph as it was and keeps the graphs
already rewritten.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import translation

from arches.app.models import models
from arches.app.utils.i18n import LanguageSynchronizer

from manuspectrum.utils.graph_translations import (
    language_codes,
    load_from_tables,
    published_graphs,
    rebuild,
)

# Recorded in the publication's history (published_graph_edits) for each graph
# whose rows were rewritten.
EDIT_NOTES = "republish_graph_translations: {languages} rebuilt from the graph tables"


def differing_parts(stored, rebuilt):
    """The top-level keys whose values differ, or ``["no row"]``."""
    if stored is None:
        return ["no row"]
    keys = sorted(set(stored) | set(rebuilt))
    return [key for key in keys if stored.get(key) != rebuilt.get(key)]


class Command(BaseCommand):
    help = (
        "Rewrite the per-language rows of the current graph publications from "
        "the graph tables, in place (no new publication)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="List the rows that differ from the graph tables, write nothing",
        )

    def handle_graph(self, graph_id, codes, dry_run):
        """Compare, and unless ``dry_run`` rewrite, one graph's current publication.

        Returns ``(rows that differ, rows compared)``, or the label of the graph
        when it is skipped. Runs inside the caller's transaction; the graph row
        is locked unless ``dry_run``.
        """
        graphs = models.GraphModel.objects
        graph = (graphs if dry_run else graphs.select_for_update()).get(pk=graph_id)
        label = f"{graph.name} ({graph.graphid})"
        if graph.publication_id is None:
            return None
        if graph.has_unpublished_changes:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {label}: it has unpublished changes; publish "
                    "it from the Graph Designer."
                )
            )
            return label
        stored = dict(
            models.PublishedGraph.objects.filter(
                publication_id=graph.publication_id
            ).values_list("language_id", "serialized_graph")
        )
        load_language = next((code for code in codes if code in stored), None)
        if load_language is None:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {label}: its publication {graph.publication_id} "
                    "has no row in any language of LANGUAGES; run "
                    "`manage.py i18n synclanguages`, then this command."
                )
            )
            return label

        rebuilt = rebuild(graph.graphid, codes, load_language)
        changed = [code for code, ser in rebuilt.items() if stored.get(code) != ser]
        if changed and not dry_run:
            with translation.override(load_language):
                load_from_tables(graph.graphid, load_language).update_published_graphs(
                    notes=EDIT_NOTES.format(languages=", ".join(changed))
                )
        for code in changed:
            parts = ", ".join(differing_parts(stored.get(code), rebuilt[code]))
            verb = "Differs" if dry_run else "Rewrote"
            self.stdout.write(f"{verb}: {code} of {label}: {parts}")
        return len(changed), len(rebuilt)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        codes = language_codes()
        if not dry_run:
            # The Language rows the published_graphs rows point at, as
            # Graph.publish() ensures them; it does not touch the publications.
            LanguageSynchronizer.synchronize_settings_with_db(
                update_published_graphs=False
            )

        differing = up_to_date = 0
        skipped = []
        graph_ids = list(published_graphs().values_list("graphid", flat=True))
        for graph_id in graph_ids:
            with transaction.atomic():
                outcome = self.handle_graph(graph_id, codes, dry_run)
            if outcome is None:
                continue
            if isinstance(outcome, str):
                skipped.append(outcome)
                continue
            changed, count = outcome
            differing += changed
            up_to_date += count - changed

        if dry_run:
            summary = (
                f"Dry run: {differing} publication row(s) differ from the graph "
                f"tables, {up_to_date} up to date, {len(skipped)} graph(s) "
                "skipped. Nothing was written."
            )
        else:
            summary = (
                f"{differing} publication row(s) rewritten, {up_to_date} up to "
                f"date, {len(skipped)} graph(s) skipped. No publication was "
                "created; resources keep theirs."
            )
        self.stdout.write(
            self.style.WARNING(summary) if skipped else self.style.SUCCESS(summary)
        )
