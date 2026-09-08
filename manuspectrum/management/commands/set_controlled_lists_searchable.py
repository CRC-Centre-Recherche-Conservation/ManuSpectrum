"""
SET CONTROLLED LISTS SEARCHABLE

CONTEXT:
`List.searchable` decides whether a list's labels are pushed to the `references`
Elasticsearch index, which is what feeds the "References" bucket of the search
bar. The conversion from RDM collections leaves every list at the default,
`False`, so the index stays empty and the bucket returns nothing however well
the vocabulary is populated.

WHY A COMMAND:
The indexing happens inside `List.save()` — `if self.searchable: self.index()`.
A `bulk_update` flips the column without ever indexing anything, which leaves
the flag and the index disagreeing in a way nothing later corrects. This walks
the lists and saves them one by one so the index follows.

OPTIONS:
--dry-run: reports what would change, changes nothing
--off:     the reverse, unindexing the lists it turns off
--list-id: restrict to one or more list ids (repeatable); default is every list

Idempotent: a list already in the requested state is skipped, so no pointless
reindexing happens.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from arches_controlled_lists.models import List


class Command(BaseCommand):
    help = "Flip controlled lists searchable so their labels reach the references index"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report what would change without touching anything",
        )
        parser.add_argument(
            "--off",
            action="store_true",
            dest="off",
            help="Turn searchable off instead of on, dropping the lists from the index",
        )
        parser.add_argument(
            "--list-id",
            action="append",
            dest="list_ids",
            default=[],
            help="Restrict to this list id; repeat for several",
        )

    def handle(self, *args, **options):
        target = not options["off"]

        queryset = List.objects.all()
        if options["list_ids"]:
            queryset = queryset.filter(pk__in=options["list_ids"])
            missing = set(options["list_ids"]) - {
                str(pk) for pk in queryset.values_list("pk", flat=True)
            }
            if missing:
                self.stderr.write(f"Unknown list ids, ignored: {sorted(missing)}")

        to_change = [
            controlled_list
            for controlled_list in queryset
            if controlled_list.searchable != target
        ]

        self.stdout.write(f"Lists considered: {queryset.count()}")
        self.stdout.write(f"  to set searchable={target}: {len(to_change)}")
        for controlled_list in to_change[:10]:
            self.stdout.write(f"    {controlled_list.name}")
        if len(to_change) > 10:
            self.stdout.write(f"    … and {len(to_change) - 10} more")

        if options["dry_run"]:
            self.stdout.write("Dry run — nothing was changed.")
            return

        if not to_change:
            self.stdout.write("Nothing to do.")
            return

        with transaction.atomic():
            for controlled_list in to_change:
                controlled_list.searchable = target
                # save(), not bulk_update: this is what indexes or unindexes the list.
                controlled_list.save()

        self.stdout.write(f"Set searchable={target} on {len(to_change)} lists.")
