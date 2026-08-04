"""
NORMALIZE CONTROLLED LIST ITEM LANGUAGES

CONTEXT & PROBLEM:
The thesauri imported into the RDM label their concepts with regional variants
— `fr-FR`, `en-US`, `en-UK` — while this site runs on `fr` and `en`. When those
collections were converted to controlled lists, the conversion copied the source
language codes verbatim.

The reference-select widget resolves a label for the ACTIVE language and has no
fallback to a regional sibling, so an item labelled only in `fr-FR` and `en-US`
renders as "Unlabeled Item" in both French and English. Measured before this
command was written: 4148 of 6461 items, i.e. 64% of the vocabulary.

OBJECTIVE:
Fold the regional variants onto the two languages the site actually serves, so
every item resolves a label in `fr` and/or `en`.

    fr-FR  ->  fr
    en-US  ->  en
    en-UK  ->  en

Languages that are not variants of the site's two (de, es, it, nl, ar, ru…) are
left untouched: they carry genuine translations, they are not duplicates, and
dropping them would lose thesaurus content.

HOW IT WORKS:
1. Selects ListItemValue rows whose language is one of the mapped variants
2. Refuses to move a row when the target language would then hold two prefLabels
   for the same item — `unique_item_preflabel_language` forbids it, and picking
   a winner is a curatorial decision this command has no basis to make. Such
   rows are reported and skipped.
3. Rewrites the language of the rest, in one transaction

Measured on the full dataset when introduced: 8404 rows to move — 6121 of them
prefLabels, the rest altLabels and scopeNotes — and 0 conflicts.

SAFETY:
Only `language_id` changes. No row is created or deleted, no text is altered,
and no item can lose a label. Re-running is a no-op once folded.

OPTIONS:
--dry-run: reports what would move, changes nothing (run this first)
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from arches_controlled_lists.models import ListItemValue

LANGUAGE_FOLDING = {"fr-FR": "fr", "en-US": "en", "en-UK": "en"}


class Command(BaseCommand):
    help = "Fold regional language variants on controlled list item labels onto fr/en"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report what would move without touching the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        candidates = list(
            ListItemValue.objects.filter(language_id__in=LANGUAGE_FOLDING).values(
                "id", "list_item_id", "language_id", "valuetype_id"
            )
        )
        if not candidates:
            self.stdout.write("No regional variants left to fold. Nothing to do.")
            return

        # Which (item, language) pairs already hold a prefLabel, so we can detect
        # the collisions the unique constraint would reject.
        taken = defaultdict(set)
        for row in ListItemValue.objects.filter(
            valuetype_id="prefLabel",
            list_item_id__in={row["list_item_id"] for row in candidates},
        ).values("list_item_id", "language_id"):
            taken[str(row["list_item_id"])].add(row["language_id"])

        movable = []
        conflicts = []
        for row in candidates:
            target = LANGUAGE_FOLDING[row["language_id"]]
            if row["valuetype_id"] == "prefLabel":
                item_languages = taken[str(row["list_item_id"])]
                if target in item_languages:
                    conflicts.append(row)
                    continue
                item_languages.discard(row["language_id"])
                item_languages.add(target)
            movable.append((row["id"], target))

        self.stdout.write(f"Regional variants found: {len(candidates)}")
        self.stdout.write(f"  safe to fold: {len(movable)}")
        self.stdout.write(
            f"  kept — target language already holds a prefLabel: {len(conflicts)}"
        )
        for row in conflicts[:5]:
            self.stdout.write(
                f"    [conflict] item {row['list_item_id']}: "
                f"{row['language_id']} -> {LANGUAGE_FOLDING[row['language_id']]}"
            )

        if dry_run:
            self.stdout.write("Dry run — nothing was changed.")
            return

        by_target = defaultdict(list)
        for value_id, target in movable:
            by_target[target].append(value_id)

        with transaction.atomic():
            moved = 0
            for target, value_ids in by_target.items():
                moved += ListItemValue.objects.filter(id__in=value_ids).update(
                    language_id=target
                )

        self.stdout.write(f"Folded {moved} labels onto fr/en.")
