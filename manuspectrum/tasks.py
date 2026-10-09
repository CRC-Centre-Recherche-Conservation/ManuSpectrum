"""Celery tasks for ManuSpectrum.

Thin async wrappers around Arches indexing operations. Tasks are registered
under explicit names so that callers can verify registration before dispatching
(see ``apps.py``'s startup assertion).

All tasks are idempotent: running them twice for the same resource/transaction
is safe and simply re-applies the same ES document.
"""

import logging
import time
import uuid

from celery import shared_task

from manuspectrum.observability import metrics

logger = logging.getLogger(__name__)


@shared_task(name="manuspectrum.index_resources")
def index_resources_async(transaction_id=None, resource_ids=None):
    """Idempotent ES re-index task. Called after DB commit.

    Two modes (mutually exclusive; ``transaction_id`` takes precedence):

    - **transaction_id**: resolves ALL resources that share this transaction via
      ``SELECT DISTINCT resourceinstanceid FROM edit_log WHERE transactionid=%s``
      and re-indexes them in one Elasticsearch batch. This is the canonical path
      for batch creates (``BiblissimaCreateAllView``) where many resources share a
      single ``batch_tx``.

    - **resource_ids**: re-indexes each id individually. Used by the unitary
      ``_create_resource`` path when there is no shared transaction id to batch on.

    ``recalculate_descriptors=True`` ensures that display names / descriptors
    (which may depend on related resources) are refreshed, not just the tile data.
    Matches what the synchronous fallback path does.
    """
    if transaction_id:
        from arches.app.utils.index_database import index_resources_by_transaction

        try:
            uuid.UUID(str(transaction_id))
        except ValueError:
            logger.error("index_resources_async: transaction id is not a uuid")
            metrics.INDEX_RESOURCES.labels(mode="transaction", outcome="failed").inc()
            return
        try:
            index_resources_by_transaction(transaction_id, recalculate_descriptors=True)
        except Exception:
            metrics.INDEX_RESOURCES.labels(mode="transaction", outcome="failed").inc()
            raise
        metrics.INDEX_RESOURCES.labels(mode="transaction", outcome="indexed").inc()
    elif resource_ids:
        from arches.app.models.resource import Resource

        for resource_id in resource_ids:
            try:
                resource = Resource.objects.get(pk=resource_id)
                resource.index()
                outcome = "indexed"
            except Resource.DoesNotExist:
                outcome = "not_found"
                logger.warning(
                    "index_resources_async: resource %s not found, skipping",
                    resource_id,
                )
            except Exception:
                outcome = "failed"
                logger.exception(
                    "index_resources_async: failed to index resource %s", resource_id
                )
            metrics.INDEX_RESOURCES.labels(mode="resource", outcome=outcome).inc()


@shared_task(name="manuspectrum.prune_data_changes")
def prune_data_changes_task():
    """Delete the data-version ledger rows older than ``PRUNE_AFTER_DAYS``.

    Records the ledger size and the prune time (``manuspectrum_data_change_*``).
    """
    from django.db import connection

    from manuspectrum.utils.data_version import prune_data_changes

    deleted = prune_data_changes()
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM ms_data_change")
        metrics.DATA_CHANGE_ROWS.set(cursor.fetchone()[0])
    metrics.DATA_CHANGE_PRUNED.set(time.time())
    return deleted


ACTIVE_ACCOUNT_DAYS = 30


def count_active_accounts():
    """Active accounts whose last login is within ``ACTIVE_ACCOUNT_DAYS`` days.

    Every active account counts, staff and superusers included; the Arches
    ``anonymous`` visitor never does. Only the number leaves this function.
    """
    from datetime import timedelta

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    since = timezone.now() - timedelta(days=ACTIVE_ACCOUNT_DAYS)
    return (
        get_user_model()
        .objects.filter(is_active=True, last_login__gte=since)
        .exclude(username="anonymous")
        .count()
    )


def publish_active_accounts():
    """Count the active accounts and export the count with its time."""
    total = count_active_accounts()
    metrics.ACTIVE_ACCOUNTS.set(total)
    metrics.ACTIVE_ACCOUNTS_MEASURED.set(time.time())
    return total


@shared_task(name="manuspectrum.record_active_accounts")
def record_active_accounts_task():
    """Refresh ``manuspectrum_active_accounts`` (a single aggregated count)."""
    return publish_active_accounts()


@shared_task(name="manuspectrum.record_activity")
def record_activity_task():
    """Refresh the activity gauges (resources, last 24 hours, open workflows)."""
    from manuspectrum.observability import activity

    activity.publish_gauges()
