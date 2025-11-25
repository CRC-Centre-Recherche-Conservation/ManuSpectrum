"""
DIAGNOSE TILES WITH INVALID RELATIONSHIPS

CONTEXT & PROBLEM:
Before cleaning invalid relationships, it's crucial to understand:
- How many tiles are affected
- What the tile.data structure looks like
- Where invalid UUIDs are located
- Whether they can be safely cleaned

OBJECTIVE:
Provide detailed diagnostic information about tiles containing invalid
resource references to inform cleaning strategy.

HOW IT WORKS:
1. Reads CSV export to identify tiles with INVALID_TARGET status
2. For a sample of tiles (default: 10):
   a. Retrieves full tile data
   b. Displays JSON structure
   c. Locates invalid UUIDs within the data
   d. Shows which nodes contain invalid references
3. Generates statistics:
   - Total affected tiles
   - Unique invalid UUIDs
   - Average invalid references per tile

OUTPUT:
Detailed report for each tile including:
- Resource information (ID, name, graph)
- Nodegroup ID
- Complete tile.data JSON
- Location of each invalid UUID (node_id, format)
- Whether UUID is found in current data (may be cleaned already)

USE CASES:
- Before running clean_invalid_relations.py
- Understanding data corruption patterns
- Deciding between conservative vs aggressive cleaning
- Debugging why certain UUIDs are invalid

OPTIONS:
--sample: Number of tiles to analyze in detail (default: 10)
         Increase for comprehensive analysis, decrease for quick check

INTERPRETING RESULTS:
"✓ Found in node X (string)": Invalid UUID is stored as simple string
"✓ Found in node X (list/dict)": Invalid UUID is in list/object structure
"⚠️  NOT FOUND in tile.data": UUID may be cleaned, or format is unexpected

RECOMMENDED BEFORE:
- export_relations_csv.py (to generate input CSV)

RECOMMENDED AFTER:
- clean_invalid_relations.py (to fix identified issues)
"""

from django.core.management.base import BaseCommand
from arches.app.models.tile import Tile
from uuid import UUID
import csv


class Command(BaseCommand):
    help = 'Analyse les relations invalides et propose des solutions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--input',
            type=str,
            required=True,
            help='Fichier CSV exporté avec les relations',
        )
        parser.add_argument(
            '--output',
            type=str,
            default='invalid_relations_analysis.csv',
            help='Fichier CSV de sortie avec analyse',
        )

    def handle(self, *args, **options):
        input_file = options['input']
        output_file = options['output']

        self.stdout.write("=" * 80)
        self.stdout.write("ANALYSE DES RELATIONS INVALIDES")
        self.stdout.write("=" * 80)

        invalid_relations = []
        invalid_uuids_count = {}
        tiles_with_invalid = set()

        # Lire le CSV
        with open(input_file, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                if row['status'] in ['INVALID_TARGET', 'ERROR']:
                    target_id = row['target_id']
                    tile_id = row['tile_id']

                    # Compter les occurrences
                    invalid_uuids_count[target_id] = invalid_uuids_count.get(target_id, 0) + 1
                    tiles_with_invalid.add(tile_id)

                    invalid_relations.append(row)

        self.stdout.write(f"\nRelations invalides trouvées: {len(invalid_relations)}")
        self.stdout.write(f"UUIDs invalides uniques: {len(invalid_uuids_count)}")
        self.stdout.write(f"Tiles affectés: {len(tiles_with_invalid)}")

        # Analyser les tiles
        self.stdout.write("\n" + "-" * 80)
        self.stdout.write("ANALYSE DES TILES AFFECTÉS")
        self.stdout.write("-" * 80)

        analysis = []

        for tile_id in tiles_with_invalid:
            try:
                tile = Tile.objects.get(tileid=tile_id)
                resource = tile.resourceinstance

                # Compter combien de valeurs invalides dans ce tile
                invalid_count = 0
                invalid_nodes = []

                if tile.data:
                    for node_id, value in tile.data.items():
                        # Extraire les UUIDs
                        uuids_in_value = []
                        if isinstance(value, str):
                            try:
                                UUID(value)
                                uuids_in_value.append(value)
                            except:
                                pass
                        elif isinstance(value, list):
                            for item in value:
                                if isinstance(item, dict) and 'resourceId' in item:
                                    uuids_in_value.append(item['resourceId'])
                                elif isinstance(item, str):
                                    try:
                                        UUID(item)
                                        uuids_in_value.append(item)
                                    except:
                                        pass

                        # Vérifier si ces UUIDs sont invalides
                        for uuid_val in uuids_in_value:
                            if uuid_val in invalid_uuids_count:
                                invalid_count += 1
                                invalid_nodes.append({
                                    'node_id': node_id,
                                    'invalid_uuid': uuid_val
                                })

                analysis.append({
                    'tile_id': tile_id,
                    'resource_id': str(resource.resourceinstanceid),
                    'resource_name': resource.displayname() if callable(resource.displayname) else str(
                        resource.displayname),
                    'graph_name': str(resource.graph.name) if resource.graph else 'Unknown',
                    'invalid_count': invalid_count,
                    'invalid_nodes': invalid_nodes,
                    'recommendation': 'DELETE_TILE' if invalid_count > 2 else 'CLEAN_NODE'
                })

            except Tile.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"  ✗ Tile introuvable: {tile_id}"))

        # Écrire le rapport
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'tile_id', 'resource_id', 'resource_name', 'graph_name',
                'invalid_count', 'recommendation', 'invalid_uuids'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for item in analysis:
                writer.writerow({
                    'tile_id': item['tile_id'],
                    'resource_id': item['resource_id'],
                    'resource_name': item['resource_name'],
                    'graph_name': item['graph_name'],
                    'invalid_count': item['invalid_count'],
                    'recommendation': item['recommendation'],
                    'invalid_uuids': ', '.join([n['invalid_uuid'] for n in item['invalid_nodes']])
                })

        # Top UUIDs invalides
        self.stdout.write("\n" + "-" * 80)
        self.stdout.write("TOP 10 UUIDs INVALIDES LES PLUS FRÉQUENTS")
        self.stdout.write("-" * 80)

        sorted_uuids = sorted(invalid_uuids_count.items(), key=lambda x: x[1], reverse=True)[:10]
        for uuid_val, count in sorted_uuids:
            self.stdout.write(f"  {uuid_val}: {count} occurrences")

        # Recommandations
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("RECOMMANDATIONS")
        self.stdout.write("=" * 80)

        tiles_to_clean = sum(1 for a in analysis if a['recommendation'] == 'CLEAN_NODE')
        tiles_to_delete = sum(1 for a in analysis if a['recommendation'] == 'DELETE_TILE')

        self.stdout.write(f"Tiles à nettoyer (supprimer juste les valeurs invalides): {tiles_to_clean}")
        self.stdout.write(f"Tiles à supprimer entièrement (trop corrompus): {tiles_to_delete}")

        self.stdout.write(f"\n✓ Rapport détaillé: {output_file}")
        self.stdout.write("\nProchaines étapes:")
        self.stdout.write("1. Examinez le rapport pour comprendre l'ampleur du problème")
        self.stdout.write("2. Lancez: python manage.py clean_invalid_relations --input relations_export.csv --dry-run")
        self.stdout.write("3. Si OK, lancez sans --dry-run")