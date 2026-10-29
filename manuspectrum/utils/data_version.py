"""Version of the data the Explorer reads, kept by PostgreSQL.

Statement-level triggers (``sql/triggers/ms_data_change.sql``, declared in
``sql_config.py``) write one row per writing transaction into the append-only
``ms_data_change`` table, whatever the write path: ORM saves, ``bulk_create``,
ETL, raw SQL, ``psql``. ``data_version()`` names the committed state; a write
becomes visible in it when its transaction commits, like the rows it wrote.
"""

from django.db import connection, transaction

DATA_CHANGE_TABLES = (
    "tiles",
    "resource_instances",
    "resource_x_resource",
    "iiif_manifests",
    "arches_controlled_lists_listitem",
    "arches_controlled_lists_listitemvalue",
    "graphs_x_published_graphs",
    "renderer_config",
    "guardian_userobjectpermission",
    "guardian_groupobjectpermission",
    "auth_user_groups",
    "auth_group_permissions",
    "auth_user_user_permissions",
)
PRUNE_AFTER_DAYS = 7

_VERSION_SQL = "SELECT count(*), coalesce(max(seq), 0) FROM ms_data_change"
_PRUNE_SQL = "DELETE FROM ms_data_change WHERE at < now() - make_interval(days => %s)"
_MARK_SQL = (
    "INSERT INTO ms_data_change (txid) VALUES (txid_current()) "
    "ON CONFLICT (txid) DO UPDATE SET seq = nextval('ms_data_change_seq_seq')"
)


def data_version():
    """``"<rows>.<last seq>"`` of the ledger: moves with every committed write to a watched table."""
    with connection.cursor() as cursor:
        cursor.execute(_VERSION_SQL)
        count, last = cursor.fetchone()
    return f"{count}.{last}"


def prune_data_changes(days=PRUNE_AFTER_DAYS):
    """Delete the ledger rows older than *days*; returns how many went.

    A prune that deletes rows also writes one, in the same transaction, so
    readers see the version before it or the one after it, which no earlier
    state had.
    """
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(_PRUNE_SQL, [days])
        deleted = cursor.rowcount
        if deleted:
            cursor.execute(_MARK_SQL)
    return deleted
