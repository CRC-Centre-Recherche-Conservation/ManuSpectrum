"""
EXPORT RESOURCE-INSTANCE RELATIONS TO CSV

CONTEXT & PROBLEM:
In Arches, relationships between resources can be stored in two ways:
1. ResourceXResource table (legacy method, performant for queries)
2. Tiles with 'resource-instance' datatype (modern method, flexible)

When modifying graphs (nodegroup changes, restructuring), Arches does NOT
automatically synchronize relationships from tiles to ResourceXResource.
Result: relationships exist in the data (tiles) but are invisible to
optimized queries and APIs that use ResourceXResource.

OBJECTIVE:
This script extracts ALL relationships stored in tiles and exports them to
CSV for manual validation before importing into ResourceXResource.

HOW IT WORKS:
1. Iterates through all resources in specified graph(s)
2. Reads tiles for each resource
3. Extracts UUIDs referenced in 'resource-instance' type nodes
4. Verifies if these UUIDs correspond to valid resources
5. Compares with current ResourceXResource state
6. Generates CSV with:
   - Existing relationships (status=OK, action=SKIP)
   - Missing relationships (status=MISSING, action=CREATE)
   - Invalid relationships (status=INVALID_TARGET, action=ERROR)

CSV FORMAT:
- relation_type: Relationship type (e.g., "Analysis→Component")
- source_id/target_id: Technical UUIDs
- source_name/target_name: Human-readable names for validation
- rxr_exists: YES/NO (presence in ResourceXResource)
- action: CREATE/SKIP/ERROR (what import will do)
- status: OK/MISSING/INVALID_TARGET

USE CASES:
- After graph modifications in the Graph Designer
- Data migration between environments
- Periodic relationship integrity audits
- Detection of orphaned or corrupted resources
"""

from django.core.management.base import BaseCommand
from arches.app.models.tile import Tile
from arches.app.models.resource import Resource
from arches.app.models.models import Node, ResourceXResource
import csv
from uuid import UUID
from collections import defaultdict


class Command(BaseCommand):
    help = "Exporte TOUTES les relations depuis les tiles vers un CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default="relations_export.csv",
            help="Chemin du fichier CSV de sortie",
        )
        parser.add_argument(
            "--graph-id",
            type=str,
            required=False,
            help="UUID du graph source (optionnel, sinon tous les graphs)",
        )

    def handle(self, *args, **options):
        output_file = options["output"]
        graph_id = options.get("graph_id")

        # TOUS les graphs de ton système
        GRAPHS = {
            "Document": "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b",
            "Analysis": "60c85aba-f079-45bc-997f-21cdd4f77b6d",
            "Alteration": "7554cd18-3cb9-4754-b5d2-a27631997385",
            "Characterization": "af6eed4f-04a3-40d8-baef-1ad37b86c4dd",
            "Component": "d47595b4-f8a6-419c-8f33-b388206280c4",
            "Group": "4f447dca-dbb3-48d0-bc90-3f2935db8b8c",
            "Instrument": "e203beaf-da83-4b8d-b52c-936f04aa2152",
            "Modification": "bfe5ab65-67ed-44b1-a5f8-301a614e625f",
            "Person": "5bf45c85-84cd-4a76-b64a-3ffe86eea1b8",
            "Place": "3f2b036a-b65d-474d-b692-0b21903655c5",
            "Project": "87a4319d-3ca5-43f6-88cc-a7379fba67f6",
            "Sample": "7a5eda79-6b48-49d0-826d-931d5681e84e",
        }

        # Mapping inverse
        GRAPH_ID_TO_NAME = {v: k for k, v in GRAPHS.items()}

        self.stdout.write("=" * 80)
        self.stdout.write(f"EXPORT DES RELATIONS VERS CSV")
        self.stdout.write("=" * 80)

        if graph_id:
            self.stdout.write(f"Graph source filtré: {graph_id}")
            graph_filter = [graph_id]
        else:
            self.stdout.write("Tous les graphs seront analysés")
            graph_filter = list(GRAPHS.values())

        self.stdout.write(f"Fichier de sortie: {output_file}\n")

        def extract_resource_ids(value):
            uuids = []
            if isinstance(value, str):
                try:
                    UUID(value)
                    uuids.append(value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "resourceId" in item:
                        try:
                            UUID(item["resourceId"])
                            uuids.append(item["resourceId"])
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(item, str):
                        try:
                            UUID(item)
                            uuids.append(item)
                        except (ValueError, TypeError):
                            pass
            return uuids

        def get_graph_name(graph_uuid):
            """Retourne le nom du graph depuis son UUID"""
            return GRAPH_ID_TO_NAME.get(
                str(graph_uuid), f"Unknown({str(graph_uuid)[:8]})"
            )

        # Afficher les nodes resource-instance par graph
        self.stdout.write("Nodes resource-instance par graph:")
        for graph_name, gid in GRAPHS.items():
            nodes = Node.objects.filter(graph_id=gid, datatype="resource-instance")
            if nodes.count() > 0:
                self.stdout.write(f"\n  {graph_name}:")
                for node in nodes:
                    self.stdout.write(f"    - {node.name} ({node.nodeid})")

        # Build set of resource-instance node IDs for filtering
        # This prevents treating concept/concept-list UUIDs as resource references
        resource_instance_node_ids = set(
            str(n.nodeid)
            for n in Node.objects.filter(datatype__startswith="resource-instance")
        )
        self.stdout.write(
            f"\nNodes resource-instance à analyser: {len(resource_instance_node_ids)}"
        )

        # Collecter toutes les relations
        relations = []
        stats_by_type = defaultdict(lambda: {"missing": 0, "ok": 0, "error": 0})

        self.stdout.write(f"\n{'=' * 80}")
        self.stdout.write("Analyse des ressources...")
        self.stdout.write("=" * 80)

        for gid in graph_filter:
            graph_name = get_graph_name(gid)
            resources = Resource.objects.filter(graph_id=gid)
            count = resources.count()

            if count == 0:
                continue

            self.stdout.write(f"\n{graph_name}: {count} ressources")

            for idx, resource in enumerate(resources, 1):
                if idx % 50 == 0:
                    self.stdout.write(f"  Traité {idx}/{count}...")

                # Display name de la source
                try:
                    source_name = (
                        resource.displayname()
                        if callable(resource.displayname)
                        else str(resource.displayname)
                    )
                except:
                    source_name = str(resource.resourceinstanceid)[:8]

                source_graph_name = get_graph_name(resource.graph_id)

                tiles = Tile.objects.filter(
                    resourceinstance_id=resource.resourceinstanceid
                )

                for tile in tiles:
                    if not tile.data:
                        continue

                    for node_id, value in tile.data.items():
                        # Only process resource-instance nodes, skip concepts etc.
                        if node_id not in resource_instance_node_ids:
                            continue
                        target_uuids = extract_resource_ids(value)

                        for target_uuid in target_uuids:
                            try:
                                target_resource = Resource.objects.get(
                                    resourceinstanceid=target_uuid
                                )

                                # Display name de la cible
                                try:
                                    target_name = (
                                        target_resource.displayname()
                                        if callable(target_resource.displayname)
                                        else str(target_resource.displayname)
                                    )
                                except:
                                    target_name = str(target_uuid)[:8]

                                target_graph_name = get_graph_name(
                                    target_resource.graph_id
                                )

                                # Vérifier si la relation existe dans ResourceXResource
                                rxr_exists = ResourceXResource.objects.filter(
                                    from_resource_id=resource.resourceinstanceid,
                                    to_resource_id=target_uuid,
                                ).exists()

                                # Type de relation
                                relation_type = (
                                    f"{source_graph_name}→{target_graph_name}"
                                )

                                status = "OK" if rxr_exists else "MISSING"
                                stats_by_type[relation_type][status.lower()] += 1

                                relations.append(
                                    {
                                        "source_id": str(resource.resourceinstanceid),
                                        "source_name": source_name,
                                        "source_graph": source_graph_name,
                                        "target_id": target_uuid,
                                        "target_name": target_name,
                                        "target_graph": target_graph_name,
                                        "relation_type": relation_type,
                                        "tile_id": str(tile.tileid),
                                        "node_id": node_id,
                                        "nodegroup_id": str(tile.nodegroup_id),
                                        "rxr_exists": "OUI" if rxr_exists else "NON",
                                        "action": "SKIP" if rxr_exists else "CREATE",
                                        "status": status,
                                    }
                                )

                            except Resource.DoesNotExist:
                                relation_type = f"{source_graph_name}→???"
                                stats_by_type[relation_type]["error"] += 1

                                relations.append(
                                    {
                                        "source_id": str(resource.resourceinstanceid),
                                        "source_name": source_name,
                                        "source_graph": source_graph_name,
                                        "target_id": target_uuid,
                                        "target_name": "⚠️ RESOURCE NOT FOUND",
                                        "target_graph": "???",
                                        "relation_type": relation_type,
                                        "tile_id": str(tile.tileid),
                                        "node_id": node_id,
                                        "nodegroup_id": str(tile.nodegroup_id),
                                        "rxr_exists": "N/A",
                                        "action": "ERROR",
                                        "status": "INVALID_TARGET",
                                    }
                                )

                            except Exception as e:
                                relation_type = f"{source_graph_name}→???"
                                stats_by_type[relation_type]["error"] += 1

                                relations.append(
                                    {
                                        "source_id": str(resource.resourceinstanceid),
                                        "source_name": source_name,
                                        "source_graph": source_graph_name,
                                        "target_id": target_uuid,
                                        "target_name": f"⚠️ ERROR: {str(e)[:50]}",
                                        "target_graph": "???",
                                        "relation_type": relation_type,
                                        "tile_id": str(tile.tileid),
                                        "node_id": node_id,
                                        "nodegroup_id": str(tile.nodegroup_id),
                                        "rxr_exists": "N/A",
                                        "action": "ERROR",
                                        "status": "ERROR",
                                    }
                                )

        # Écrire dans le CSV
        with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "relation_type",  # Ajouté en premier pour faciliter le tri
                "source_id",
                "source_name",
                "source_graph",
                "target_id",
                "target_name",
                "target_graph",
                "tile_id",
                "node_id",
                "nodegroup_id",
                "rxr_exists",
                "action",
                "status",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            # Trier par relation_type puis par source_name
            sorted_relations = sorted(
                relations, key=lambda x: (x["relation_type"], x["source_name"])
            )
            for rel in sorted_relations:
                writer.writerow(rel)

        # Statistiques détaillées
        total = len(relations)
        total_missing = sum(1 for r in relations if r["status"] == "MISSING")
        total_invalid = sum(1 for r in relations if r["status"] == "INVALID_TARGET")
        total_errors = sum(1 for r in relations if r["status"] == "ERROR")
        total_ok = sum(1 for r in relations if r["status"] == "OK")

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("STATISTIQUES GLOBALES")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Total relations trouvées: {total}")
        self.stdout.write(
            self.style.SUCCESS(f"✓ Déjà dans ResourceXResource: {total_ok}")
        )
        self.stdout.write(self.style.WARNING(f"⚠️  Manquantes: {total_missing}"))
        self.stdout.write(self.style.ERROR(f"✗ Cibles invalides: {total_invalid}"))
        if total_errors > 0:
            self.stdout.write(self.style.ERROR(f"✗ Autres erreurs: {total_errors}"))

        self.stdout.write("\n" + "-" * 80)
        self.stdout.write("STATISTIQUES PAR TYPE DE RELATION")
        self.stdout.write("-" * 80)

        for rel_type in sorted(stats_by_type.keys()):
            stats = stats_by_type[rel_type]
            total_for_type = stats["ok"] + stats["missing"] + stats["error"]
            self.stdout.write(f"\n{rel_type}: {total_for_type} relations")
            if stats["ok"] > 0:
                self.stdout.write(self.style.SUCCESS(f"  ✓ OK: {stats['ok']}"))
            if stats["missing"] > 0:
                self.stdout.write(
                    self.style.WARNING(f"  ⚠️  Manquantes: {stats['missing']}")
                )
            if stats["error"] > 0:
                self.stdout.write(self.style.ERROR(f"  ✗ Erreurs: {stats['error']}"))

        self.stdout.write(f"\n{'=' * 80}")
        self.stdout.write(f"✓ Export terminé: {output_file}")
        self.stdout.write("=" * 80)
        self.stdout.write("\nProchaines étapes:")
        self.stdout.write("1. Ouvrez le CSV dans Excel/LibreOffice")
        self.stdout.write(
            "2. Triez par 'relation_type' pour voir les types de relations"
        )
        self.stdout.write("3. Filtrez sur 'status' = 'MISSING' pour voir ce qui manque")
        self.stdout.write("4. Pour chaque ligne:")
        self.stdout.write("   - 'CREATE' = sera créé à l'import")
        self.stdout.write("   - 'SKIP' = sera ignoré")
        self.stdout.write("   - 'ERROR' = à corriger ou supprimer")
        self.stdout.write(
            "5. Testez: python manage.py import_relations_csv --input relations_export.csv --dry-run"
        )
        self.stdout.write(
            "6. Lancez: python manage.py import_relations_csv --input relations_export.csv"
        )
