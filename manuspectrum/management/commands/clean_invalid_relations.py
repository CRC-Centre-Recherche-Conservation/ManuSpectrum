"""
CLEAN INVALID RELATIONSHIPS IN TILES

CONTEXT & PROBLEM:
Over time, tiles can accumulate references to resources that no longer exist
(deletion, failed migration, bugs). These "ghost" UUIDs pollute exports and
prevent synchronization with ResourceXResource.

COMMON CAUSES:
1. Resource deletion without cleaning referencing tiles
2. Incomplete data migrations
3. CSV imports with incorrect UUIDs
4. Bugs in the creation/editing interface

OBJECTIVE:
Remove invalid references from tiles to:
- Clean the database
- Enable clean relationship exports
- Improve performance (less useless data)
- Avoid errors in APIs

HOW IT WORKS:
1. Reads export CSV to identify INVALID_TARGET relationships
2. For each affected tile:
   a. Locates invalid UUIDs in tile.data
   b. Removes them based on their format:
      - Simple string: deletes dictionary key
      - List: removes element from list
      - Dict with resourceId: removes object from list
3. Saves modified tile
4. Option: Completely deletes heavily corrupted tiles (--delete-tiles)

HANDLED FORMATS:
- String: {"node_id": "invalid-uuid"}
- List: {"node_id": ["valid-uuid", "invalid-uuid"]}
- Dict: {"node_id": [{"resourceId": "invalid-uuid", ...}]}

OPTIONS:
--dry-run: Simulates without modification (MANDATORY first!)
--delete-tiles: Deletes tiles with 3+ invalid references

CLEANING STRATEGY:
- CONSERVATIVE (default): Removes only invalid values
- AGGRESSIVE (--delete-tiles): Deletes entire tiles if too corrupted

RISKS:
⚠️  WARNING: Directly modifies tiles! Always:
1. Backup database before
2. Test with --dry-run
3. Carefully review logs
4. Re-export after to validate

WORKFLOW:
1. python manage.py export_relations_csv --output relations.csv
2. python manage.py clean_invalid_relations --input relations.csv --dry-run
3. Review output, decide strategy
4. python manage.py clean_invalid_relations --input relations.csv
5. python manage.py export_relations_csv --output relations_clean.csv
6. Verify INVALID_TARGET entries are gone

IMPACT:
- Affected resources lose their invalid references
- Future exports will be cleaner
- No impact on valid data
- May require Elasticsearch reindexing for full effect
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from arches.app.models.tile import Tile
from arches.app.models.models import Node
import csv


class Command(BaseCommand):
    help = "Nettoie les relations invalides depuis un CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            type=str,
            required=True,
            help="Fichier CSV exporté avec les relations",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simule le nettoyage sans modifier",
        )
        parser.add_argument(
            "--delete-tiles",
            action="store_true",
            help="Supprime les tiles entièrement corrompus",
        )

    def handle(self, *args, **options):
        input_file = options["input"]
        dry_run = options["dry_run"]
        delete_tiles = options["delete_tiles"]

        self.stdout.write("=" * 80)
        self.stdout.write("NETTOYAGE DES RELATIONS INVALIDES")
        self.stdout.write("=" * 80)

        if dry_run:
            self.stdout.write(self.style.WARNING("MODE DRY RUN\n"))

        # Lire le CSV et grouper par tile
        tiles_to_clean = {}

        with open(input_file, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                if row["status"] in ["INVALID_TARGET", "ERROR"]:
                    tile_id = row["tile_id"]
                    node_id = row["node_id"]
                    invalid_uuid = row["target_id"]

                    if tile_id not in tiles_to_clean:
                        tiles_to_clean[tile_id] = []

                    tiles_to_clean[tile_id].append(
                        {"node_id": node_id, "invalid_uuid": invalid_uuid}
                    )

        self.stdout.write(f"Tiles à nettoyer: {len(tiles_to_clean)}\n")

        # Safety: only allow cleaning resource-instance nodes
        # Prevents accidentally deleting concept/concept-list values
        resource_instance_node_ids = set(
            str(n.nodeid)
            for n in Node.objects.filter(datatype__startswith="resource-instance")
        )

        cleaned_count = 0
        deleted_count = 0
        error_count = 0

        for tile_id, invalid_items in tiles_to_clean.items():
            try:
                tile = Tile.objects.get(tileid=tile_id)
                resource = tile.resourceinstance

                self.stdout.write(f"\nTile: {tile_id}")
                self.stdout.write(
                    f"  Ressource: {resource.name if callable(resource.name) else str(resource.name)}"
                )
                self.stdout.write(f"  Valeurs invalides: {len(invalid_items)}")

                if not tile.data:
                    self.stdout.write(self.style.WARNING("  ⚠️  Pas de données"))
                    continue

                # Décider de l'action
                if len(invalid_items) >= 3 and delete_tiles:
                    # Trop corrompu, supprimer le tile entier
                    if not dry_run:
                        with transaction.atomic():
                            tile.delete()
                    deleted_count += 1
                    self.stdout.write(
                        self.style.ERROR(f"  ✗ TILE SUPPRIMÉ (trop corrompu)")
                    )

                else:
                    # Nettoyer juste les valeurs invalides
                    modified = False

                    for invalid_item in invalid_items:
                        node_id = invalid_item["node_id"]
                        invalid_uuid = invalid_item["invalid_uuid"]

                        # Safety: skip nodes that aren't resource-instance
                        if node_id not in resource_instance_node_ids:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"    ⚠️  Ignoré node {node_id[:8]}... (pas resource-instance, probablement concept)"
                                )
                            )
                            continue

                        if node_id in tile.data:
                            value = tile.data[node_id]

                            # Cas 1: Valeur simple (string)
                            if isinstance(value, str) and value == invalid_uuid:
                                if not dry_run:
                                    del tile.data[node_id]
                                modified = True
                                self.stdout.write(
                                    f"    ✓ Supprimé node {node_id[:8]}... (valeur simple)"
                                )

                            # Cas 2: Liste
                            elif isinstance(value, list):
                                new_list = []
                                for item in value:
                                    if (
                                        isinstance(item, dict)
                                        and item.get("resourceId") == invalid_uuid
                                    ):
                                        modified = True
                                        self.stdout.write(
                                            f"    ✓ Supprimé {invalid_uuid[:8]}... de la liste"
                                        )
                                    elif isinstance(item, str) and item == invalid_uuid:
                                        modified = True
                                        self.stdout.write(
                                            f"    ✓ Supprimé {invalid_uuid[:8]}... de la liste"
                                        )
                                    else:
                                        new_list.append(item)

                                if modified and not dry_run:
                                    if new_list:
                                        tile.data[node_id] = new_list
                                    else:
                                        del tile.data[node_id]

                    if modified:
                        if not dry_run:
                            with transaction.atomic():
                                tile.save()
                        cleaned_count += 1
                        self.stdout.write(self.style.SUCCESS(f"  ✓ Tile nettoyé"))
                    else:
                        self.stdout.write(self.style.WARNING(f"  ⚠️  Rien à nettoyer"))

            except Tile.DoesNotExist:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Tile introuvable: {tile_id}"))
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Erreur: {str(e)}"))

        # Résumé
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("RÉSUMÉ DU NETTOYAGE")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Tiles nettoyés: {cleaned_count}")
        self.stdout.write(f"Tiles supprimés: {deleted_count}")
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"Erreurs: {error_count}"))

        if dry_run:
            self.stdout.write("\n⚠️  MODE DRY RUN - Aucune modification effectuée")
            self.stdout.write("Pour nettoyer réellement, relancez sans --dry-run")
