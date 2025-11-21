=============================================================================
ARCHES RELATIONSHIP SYNCHRONIZATION TOOLKIT (ResourceXResource)
=============================================================================

OVERVIEW:
This toolkit solves a critical issue in Arches: the desynchronization between
tile data (resource-instance references) and the ResourceXResource table.

THE PROBLEM:
When you modify a graph in Arches (change nodegroups, restructure nodes),
the system does NOT automatically update ResourceXResource relationships.
Result: Your data still has the relationships (in tiles) but queries and
APIs can't see them (ResourceXResource is empty/outdated).

IMPACT:
- IIIF APIs return incomplete annotation collections
- Related resources don't appear in the UI
- Performance queries fail to find relationships
- Data appears "lost" even though it's still in the database

THE SOLUTION:
This toolkit provides 4 scripts that work together:

1. [export_relations_csv.py](commands/export_relations_csv.py)
   Extracts ALL relationships from tiles → CSV
   Use: After graph changes, for audits

2. [import_relations_csv.py](commands/import_relations_csv.py)
   Imports validated relationships CSV → ResourceXResource
   Use: After manual CSV validation

3. [clean_invalid_relations.py](commands/clean_invalid_relations.py)
   Removes "ghost" UUIDs from tiles
   Use: When tiles reference deleted resources

4. [analyze_invalid_relations.py](commands/analyze_invalid_relations.py)
   Analyzes corrupted tiles in detail
   Use: Before cleaning, to understand scope

TYPICAL WORKFLOW:

Scenario A: After Graph Modification
------------------------------------
1. python manage.py export_relations_csv --graph-id <UUID> --output rels.csv
2. Open rels.csv in Excel, review 'status' column
3. python manage.py import_relations_csv --input rels.csv --dry-run
4. python manage.py import_relations_csv --input rels.csv
5. Verify in UI that relationships are restored

Scenario B: Corrupted Database Cleanup
--------------------------------------
1. python manage.py export_relations_csv --output rels.csv
2. python manage.py analyze_invalid_relations --input rels.csv --sample 20
3. python manage.py clean_invalid_relations --input rels.csv --dry-run
4. python manage.py clean_invalid_relations --input rels.csv
5. python manage.py export_relations_csv --output rels_clean.csv
6. python manage.py import_relations_csv --input rels_clean.csv

SAFETY RECOMMENDATIONS:
- ⚠️  ALWAYS backup database before running these scripts
- ⚠️  ALWAYS use --dry-run first
- ⚠️  Test on development environment before production
- ⚠️  Review CSV exports in Excel before importing
TECHNICAL DETAILS:
See individual script headers for detailed documentation.