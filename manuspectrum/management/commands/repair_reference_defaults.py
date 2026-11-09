"""
REPAIR REFERENCE DEFAULTS

Gives the default value of every reference widget the labels of its list item
in every language of `settings.LANGUAGES` (issue #290).

CONTEXT & PROBLEM:
The reference-select widget renders the prefLabel stored in the value for the
active language, with no fallback: a default carrying only the English
prefLabel shows "Unlabeled Item" under /fr/, and a resource saved with it keeps
the English-only value in its tile. The data package shipped 22 such defaults
(« preferred terms », « PeriodO », « count (sum total) »), although their list
items have both `en` and `fr`.

WHAT IT DOES:
Every default that lacks a prefLabel in a site language is replaced by its list
item's labels (`ListItem.build_tile_value()` shape: every prefLabel and
altLabel), in place, in `cards_x_nodes_x_widgets` and in the serialized graphs
of the CURRENT publication of each graph, for every language. No new
publication is made, so resources stay on the publication they are pinned to
and stay editable. See `manuspectrum.utils.reference_labels`.

WHEN IT RUNS:
- `init` (deploy/docker/entrypoint.sh) runs it after `load_package` and
  `i18n synclanguages`, for a fresh installation; the local installation
  steps of README.md run it after `load_package`;
- migration `0017_reference_default_labels` runs the same repair once on an
  existing database;
- by hand after loading a package or graph some other way: the system check
  `manuspectrum.W007` (shown by `migrate`) names the defaults still incomplete.

SAFETY:
Idempotent; a complete default is never touched. A default whose list item is
gone is reported and left alone; a list item that itself lacks a language is
reported (add the label in the Controlled List Manager, then run it again).
Values already saved in tiles are `refresh_reference_labels`' job.

OPTIONS:
--dry-run: reports what would change, changes nothing
"""

from django.core.management.base import BaseCommand

from manuspectrum.utils.reference_labels import (
    repair_reference_defaults,
    site_languages,
)


class Command(BaseCommand):
    help = (
        "Give reference widget defaults the labels of their list item in every "
        "site language (cards_x_nodes_x_widgets and current published graphs)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report what would change without touching the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        languages = site_languages()
        report = repair_reference_defaults(languages=languages, dry_run=dry_run)

        verb = "would be repaired" if dry_run else "repaired"
        self.stdout.write(f"Site languages: {', '.join(languages)}")
        self.stdout.write(f"  widget default rows {verb}: {report.widget_rows}")
        self.stdout.write(
            f"  published graphs (current publication) {verb}: "
            f"{report.published_graphs}"
        )
        for item_id in sorted(report.unresolved, key=str):
            self.stdout.write(
                f"  [unresolved] list item {item_id or '(none named)'} not found: "
                "default left as it is"
            )
        for item_id, missing in sorted(report.still_missing.items()):
            self.stdout.write(
                f"  [list item] {item_id} has no prefLabel in {', '.join(missing)}: "
                "add it in the Controlled List Manager, then run this again"
            )
        if dry_run:
            self.stdout.write("Dry run: nothing was changed.")
        elif not (report.widget_rows or report.published_graphs):
            self.stdout.write("Every reference default is complete. Nothing to do.")
