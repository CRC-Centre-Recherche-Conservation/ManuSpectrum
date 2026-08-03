"""
PURGE DUPLICATE CONCEPT IDENTIFIERS

CONTEXT & PROBLEM:
A large share of the RDM concepts carry TWO `identifier` values instead of one:
the real URI, plus a Python dict that was serialised with repr() and stored as
a string:

    {'id': 'ea65c2dc-e2d7-4906-b88b-ae864f53aecd', 'value': 'https://ark.frantiq.fr/…'}
    https://ark.frantiq.fr/ark:/26678/pcrt6g08f8rkk4d8xdx76wnc

Somewhere in the thesaurus import chain the whole value object was written
instead of its `value` field. The stray row carries no information the URI does
not already hold.

WHY IT MATTERS:
Beyond being noise in the RDM, it blocks the migration to controlled lists.
`__arches_migrate_collections_to_clm()` joins identifiers without deduplicating:

    left join (select conceptid, value from values where valuetype = 'identifier')
        identifier on legacy_list_item_id = identifier.conceptid

A concept with two identifiers therefore yields two rows sharing one
`list_item_id`, and the insert dies on a duplicate primary key. Any collection
containing such a concept cannot be converted.

OBJECTIVE:
Remove the serialised-dict rows so every concept holds exactly one identifier,
which both cleans the RDM and unblocks the conversion — without waiting for the
upstream join to be fixed.

HOW IT WORKS:
1. Selects `identifier` values whose text starts with "{"
2. For each one, refuses to touch it unless ALL of these hold:
   a. the string parses as a Python literal exposing a `value` key
   b. the concept also holds a plain (non-dict) identifier
   c. that plain identifier equals the dict's inner `value`
   Anything else is reported and left alone — a divergent dict may carry
   information this command has no business discarding.
3. Deletes the rows that passed, in one transaction

SAFETY:
Verified before writing this command, on the full dataset: tiles reference
prefLabel values, never identifiers, and ResourceXResource.relationshiptype
does not point at any of these rows. Deleting them cannot orphan a concept
because (b) guarantees a surviving identifier.

OPTIONS:
--dry-run: reports what would be deleted, changes nothing (run this first)

The command is idempotent: once purged, a second run finds nothing to do.
"""

import ast

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from arches.app.models.models import Value


class Command(BaseCommand):
    help = "Remove serialised-dict duplicates from concept identifier values"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report what would be deleted without touching the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        candidates = list(
            Value.objects.filter(
                valuetype_id="identifier", value__startswith="{"
            ).values("valueid", "concept_id", "value")
        )
        if not candidates:
            self.stdout.write("No serialised-dict identifiers found. Nothing to do.")
            return

        concept_ids = {str(row["concept_id"]) for row in candidates}
        plain_by_concept = defaultdict(set)
        for row in Value.objects.filter(
            valuetype_id="identifier", concept_id__in=concept_ids
        ).values("concept_id", "value"):
            text = str(row["value"]).strip()
            if not text.startswith("{"):
                plain_by_concept[str(row["concept_id"])].add(text)

        deletable = []
        unparsable = []
        divergent = []
        sole_identifier = []

        for row in candidates:
            concept_id = str(row["concept_id"])
            surviving = plain_by_concept.get(concept_id)
            if not surviving:
                sole_identifier.append(row)
                continue
            try:
                inner = ast.literal_eval(str(row["value"]))
                inner_value = str(inner["value"]).strip()
            except (ValueError, SyntaxError, TypeError, KeyError):
                unparsable.append(row)
                continue
            if inner_value in surviving:
                deletable.append(row["valueid"])
            else:
                divergent.append(row)

        self.stdout.write(f"Serialised-dict identifiers found: {len(candidates)}")
        self.stdout.write(f"  redundant, safe to delete: {len(deletable)}")
        self.stdout.write(f"  kept — dict is unparsable: {len(unparsable)}")
        self.stdout.write(
            f"  kept — inner value differs from the URI: {len(divergent)}"
        )
        self.stdout.write(
            f"  kept — concept holds no other identifier: {len(sole_identifier)}"
        )

        for label, rows in (
            ("unparsable", unparsable),
            ("divergent", divergent),
            ("sole identifier", sole_identifier),
        ):
            for row in rows[:5]:
                self.stdout.write(
                    f"    [{label}] concept {row['concept_id']}: "
                    f"{str(row['value'])[:90]}"
                )

        if dry_run:
            self.stdout.write("Dry run — nothing was deleted.")
            return

        if not deletable:
            self.stdout.write("Nothing safe to delete.")
            return

        with transaction.atomic():
            deleted, _ = Value.objects.filter(valueid__in=deletable).delete()

        self.stdout.write(f"Deleted {deleted} value rows.")
