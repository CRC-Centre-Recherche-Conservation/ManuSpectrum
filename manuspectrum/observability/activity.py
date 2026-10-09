"""Activity of the platform read from the Arches journals: counts only.

One place holds the rules of the monthly report (`activity_summary`) and of the
hourly gauges (`manuspectrum.record_activity`). Every query is a SELECT in a
read-only transaction and returns aggregates per resource model, workflow or ETL
module; no user column is read and no resource id leaves this module.

Rules, over a window ``[start, end)`` of UTC instants (passed as ``timestamptz``:
the project keeps Arches' ``TIME_ZONE`` with ``USE_TZ = False``, so the
``timestamp`` columns hold local time and the session compares them in that zone):

- created: distinct resources with an ``edit_log`` row ``create`` (Arches writes one
  per ``Resource.save()``, not only the first) or a ``tile create`` noted
  ``resource creation`` (the Biblissima bulk path writes no ``create`` row);
- modified: distinct resources with another tile-level row, not created in the window;
- deleted: distinct resources with a ``delete`` row; ``created_deleted`` is the part of
  the created ones that were deleted in the same window;
- tile saves: tile-level rows that are not part of a creation;
- totals: ``resource_instances`` per model, whatever path wrote them;
- workflows: ``workflow_history`` rows, one per run; a run cancelled by its user is
  deleted by Arches and leaves no row; an open run is stale once older than
  ``WORKFLOW_STALE_AFTER_DAYS`` (a placeholder until the cleanup delay is decided);
- ETL: ``load_event`` rows started in the window, by module and outcome.
"""

import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from django.db import connection, transaction

from manuspectrum.observability import metrics

SYSTEM_GRAPH_SLUG = "arches_system_settings"
DELETED_MODEL = "deleted_model"
WORKFLOW_STALE_AFTER_DAYS = 30
ETL_OUTCOMES = ("succeeded", "failed", "unfinished")
ETL_SUCCEEDED_STATUSES = ("indexed", "completed")
RECENT_HOURS = 24
MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")

CHANGE_FIELDS = (
    "created",
    "created_deleted",
    "modified",
    "deleted",
    "tile_saves",
    "publication_changes",
)

CHANGES_SQL = """
WITH log AS (
    SELECT resourceclassid, resourceinstanceid, edittype, note
    FROM edit_log
    WHERE timestamp >= %(start)s::timestamptz AND timestamp < %(end)s::timestamptz
), created AS (
    SELECT DISTINCT resourceclassid, resourceinstanceid FROM log
    WHERE edittype = 'create'
       OR (edittype = 'tile create' AND note = 'resource creation')
), deleted AS (
    SELECT DISTINCT resourceclassid, resourceinstanceid FROM log
    WHERE edittype = 'delete'
), tile_saves AS (
    SELECT resourceclassid, resourceinstanceid FROM log
    WHERE edittype IN ('tile create', 'tile edit', 'tile delete')
      AND note IS DISTINCT FROM 'resource creation'
), modified AS (
    SELECT DISTINCT t.resourceclassid, t.resourceinstanceid FROM tile_saves t
    WHERE NOT EXISTS (
        SELECT 1 FROM created c WHERE c.resourceinstanceid = t.resourceinstanceid
    )
), counted AS (
    SELECT resourceclassid, 'created' AS field, count(*) AS n FROM created GROUP BY 1
    UNION ALL
    SELECT c.resourceclassid, 'created_deleted', count(*) FROM created c
    WHERE EXISTS (SELECT 1 FROM deleted d WHERE d.resourceinstanceid = c.resourceinstanceid)
    GROUP BY 1
    UNION ALL
    SELECT resourceclassid, 'modified', count(*) FROM modified GROUP BY 1
    UNION ALL
    SELECT resourceclassid, 'deleted', count(*) FROM deleted GROUP BY 1
    UNION ALL
    SELECT resourceclassid, 'tile_saves', count(*) FROM tile_saves GROUP BY 1
    UNION ALL
    SELECT resourceclassid, 'publication_changes', count(*) FROM log
    WHERE edittype = 'update_resource_instance_lifecycle_state' GROUP BY 1
)
SELECT g.slug, k.field, k.n
FROM counted k
LEFT JOIN graphs g ON g.graphid::text = k.resourceclassid
WHERE g.slug IS DISTINCT FROM %(system)s
"""

TOTALS_SQL = """
SELECT g.slug, count(*)
FROM resource_instances r
JOIN graphs g ON g.graphid = r.graphid
WHERE g.slug IS DISTINCT FROM %(system)s
GROUP BY g.slug
"""

WORKFLOWS_SQL = """
SELECT workflowname,
       count(*) FILTER (WHERE created >= %(start)s::timestamptz
                          AND created < %(end)s::timestamptz),
       count(*) FILTER (WHERE completed AND created >= %(start)s::timestamptz
                          AND created < %(end)s::timestamptz),
       count(*) FILTER (WHERE NOT completed),
       count(*) FILTER (WHERE NOT completed AND created < %(stale)s::timestamptz)
FROM workflow_history
GROUP BY workflowname
"""

ETL_SQL = """
SELECT m.slug,
       count(*),
       count(*) FILTER (WHERE l.status = ANY(%(done)s)),
       count(*) FILTER (WHERE l.status = 'failed')
FROM load_event l
JOIN etl_modules m ON m.etlmoduleid = l.etl_module_id
WHERE l.load_start_time >= %(start)s::timestamptz
  AND l.load_start_time < %(end)s::timestamptz
GROUP BY m.slug
"""


@contextmanager
def read_only_cursor():
    """A cursor in a read-only transaction that is always rolled back.

    ``SET LOCAL`` is undone by the rollback, so the setting does not outlive the
    block when it runs inside an enclosing transaction.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL transaction_read_only = on")
            try:
                yield cursor
            finally:
                transaction.set_rollback(True)


def month_window(label):
    """The UTC instants ``[start, end)`` of the calendar month *label* (``YYYY-MM``)."""
    if not MONTH.fullmatch(label or ""):
        raise ValueError("the month must be YYYY-MM")
    year, month = (int(part) for part in label.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    following = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
    return start, following


def _model(slug):
    return slug if slug else DELETED_MODEL


def resource_totals(cursor):
    cursor.execute(TOTALS_SQL, {"system": SYSTEM_GRAPH_SLUG})
    return {_model(slug): n for slug, n in cursor.fetchall()}


def resource_changes(cursor, start, end):
    """``{model: {field: n}}`` for the fields of ``CHANGE_FIELDS``."""
    cursor.execute(
        CHANGES_SQL, {"start": start, "end": end, "system": SYSTEM_GRAPH_SLUG}
    )
    changes = {}
    for slug, field, n in cursor.fetchall():
        changes.setdefault(_model(slug), dict.fromkeys(CHANGE_FIELDS, 0))[field] += n
    return changes


def workflow_runs(cursor, start, end, now):
    cursor.execute(
        WORKFLOWS_SQL,
        {
            "start": start,
            "end": end,
            "stale": now - timedelta(days=WORKFLOW_STALE_AFTER_DAYS),
        },
    )
    return {
        name: dict(zip(("started", "completed", "open", "stale"), counts))
        for name, *counts in cursor.fetchall()
    }


def etl_runs(cursor, start, end):
    cursor.execute(
        ETL_SQL,
        {"start": start, "end": end, "done": list(ETL_SUCCEEDED_STATUSES)},
    )
    runs = {}
    for slug, started, succeeded, failed in cursor.fetchall():
        runs[slug] = {
            "started": started,
            "succeeded": succeeded,
            "failed": failed,
            "unfinished": started - succeeded - failed,
        }
    return runs


def collect(start, end, now=None):
    """Every figure for the window, from one read-only transaction.

    Totals and open workflows describe the moment of the call; the rest the window.
    """
    now = now or datetime.now(timezone.utc)
    with read_only_cursor() as cursor:
        totals = resource_totals(cursor)
        changes = resource_changes(cursor, start, end)
        workflows = workflow_runs(cursor, start, end, now)
        etl = etl_runs(cursor, start, end)
    models = {}
    for model in sorted(set(totals) | set(changes)):
        models[model] = {
            "total": totals.get(model, 0),
            **changes.get(model, dict.fromkeys(CHANGE_FIELDS, 0)),
        }
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "models": models,
        "workflows": workflows,
        "workflow_stale_after_days": WORKFLOW_STALE_AFTER_DAYS,
        "etl": etl,
    }


def monthly_summary(label, now=None):
    start, end = month_window(label)
    return {"month": label, **collect(start, end, now)}


def publish_gauges(now=None):
    """Set the activity gauges: totals, the last 24 hours, open workflows."""
    now = now or datetime.now(timezone.utc)
    figures = collect(now - timedelta(hours=RECENT_HOURS), now, now)
    totals = dict.fromkeys(metrics.RESOURCE_MODELS + (metrics.OTHER,), 0)
    changes = {(model, kind): 0 for model in totals for kind in metrics.CHANGE_KINDS}
    for slug, row in figures["models"].items():
        model = metrics.bounded(slug, metrics.RESOURCE_MODELS)
        totals[model] += row["total"]
        for kind in metrics.CHANGE_KINDS:
            changes[(model, kind)] += row[kind]
    runs = {
        (kind, state): 0
        for kind in metrics.WORKFLOW_KINDS + (metrics.OTHER,)
        for state in metrics.WORKFLOW_STATES
    }
    for name, row in figures["workflows"].items():
        kind = metrics.bounded(name, metrics.WORKFLOW_KINDS)
        for state in metrics.WORKFLOW_STATES:
            runs[(kind, state)] += row[state]
    for model, n in totals.items():
        metrics.RESOURCES.labels(model=model).set(n)
    for (model, kind), n in changes.items():
        metrics.RESOURCE_CHANGES.labels(model=model, kind=kind).set(n)
    for (kind, state), n in runs.items():
        metrics.WORKFLOWS.labels(kind=kind, state=state).set(n)
    metrics.ACTIVITY_MEASURED.set(now.timestamp())
    return figures
