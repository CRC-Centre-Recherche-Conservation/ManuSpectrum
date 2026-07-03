"""Celery tasks for ManuSpectrum.

Thin async wrappers around Arches indexing operations. Tasks are registered
under explicit names so that callers can verify registration before dispatching
(see ``apps.py``'s startup assertion).

All tasks are idempotent: running them twice for the same resource/transaction
is safe and simply re-applies the same ES document.
"""

import logging

from celery import shared_task

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

        index_resources_by_transaction(transaction_id, recalculate_descriptors=True)
    elif resource_ids:
        from arches.app.models.resource import Resource

        for resource_id in resource_ids:
            try:
                resource = Resource.objects.get(pk=resource_id)
                resource.index()
            except Resource.DoesNotExist:
                logger.warning(
                    "index_resources_async: resource %s not found, skipping", resource_id
                )
            except Exception:
                logger.exception(
                    "index_resources_async: failed to index resource %s", resource_id
                )
