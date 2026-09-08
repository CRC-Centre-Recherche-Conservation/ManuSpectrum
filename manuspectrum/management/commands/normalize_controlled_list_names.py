"""
NORMALIZE CONTROLLED LIST NAMES

CONTEXT & PROBLEM:
`__arches_migrate_collections_to_clm` names the list it creates after whichever
prefLabel of the source collection matched the name passed on the command line.
Since a collection has to be targeted by a label that is unique among
collections, that label is often not the English one — which is how the
Controlled List Manager ended up showing lists called
"10.1. offizielle Berufe und Funktionen", "volkeren", "entità sociali
collettive" or "procesos que alteran las condiciones".

Unlike list item labels, `List.name` is a plain CharField: it holds one string,
with no per-language variant. So there is nothing for the i18n machinery to
resolve, and the name has to be picked once.

OBJECTIVE:
Rename every list after the English prefLabel of its source collection, falling
back to French and then to any available label when English is missing.

The list id IS the source collection's conceptid — the conversion sets it that
way — so the labels can be looked up directly, with no mapping table.

HOW IT WORKS:
1. For each list, reads the prefLabels of the concept sharing its id
2. Picks the first available in order: en, en-US, en-UK, fr, fr-FR, then any
3. Skips the list when the chosen label already is its name, or when the source
   concept has no prefLabel at all
4. Reports any rename that would leave two lists sharing a name — the manager
   lists them side by side, and two identical entries are unusable

OPTIONS:
--dry-run: reports the renames without applying them (run this first)

Re-running is a no-op once every list carries its English label.
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from arches.app.models.models import Value
from arches_controlled_lists.models import List

LANGUAGE_PREFERENCE = ["en", "en-US", "en-UK", "fr", "fr-FR"]
NAME_MAX_LENGTH = 127


class Command(BaseCommand):
    help = "Rename controlled lists after the English label of their source collection"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report the renames without applying them",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        lists = list(List.objects.all())
        labels_by_concept = {}
        for row in Value.objects.filter(
            concept_id__in=[controlled_list.pk for controlled_list in lists],
            valuetype_id="prefLabel",
        ).values("concept_id", "language_id", "value"):
            labels_by_concept.setdefault(str(row["concept_id"]), {})[
                row["language_id"]
            ] = row["value"]

        renames = []
        unlabelled = []
        for controlled_list in lists:
            labels = labels_by_concept.get(str(controlled_list.pk))
            if not labels:
                unlabelled.append(controlled_list)
                continue
            chosen = next(
                (labels[code] for code in LANGUAGE_PREFERENCE if code in labels),
                next(iter(labels.values())),
            )
            chosen = str(chosen)[:NAME_MAX_LENGTH]
            if chosen != controlled_list.name:
                renames.append((controlled_list, chosen))

        final_names = Counter(
            {controlled_list.pk: controlled_list.name for controlled_list in lists}
            | {controlled_list.pk: name for controlled_list, name in renames}
        )
        duplicates = [
            name for name, count in Counter(final_names.values()).items() if count > 1
        ]

        self.stdout.write(f"Lists: {len(lists)}")
        self.stdout.write(f"  to rename: {len(renames)}")
        self.stdout.write(f"  source concept has no prefLabel: {len(unlabelled)}")
        for controlled_list, name in renames:
            self.stdout.write(f"    {controlled_list.name!r} -> {name!r}")
        if duplicates:
            self.stdout.write(
                self.style.WARNING(
                    f"  WARNING — these names would be shared by several lists: {duplicates}"
                )
            )

        if dry_run:
            self.stdout.write("Dry run — nothing was renamed.")
            return

        if not renames:
            self.stdout.write("Nothing to rename.")
            return

        with transaction.atomic():
            for controlled_list, name in renames:
                controlled_list.name = name
                # save() re-indexes the list when it is searchable, which is what
                # keeps the name shown in search results in step with this change.
                controlled_list.save()

        self.stdout.write(f"Renamed {len(renames)} lists.")
