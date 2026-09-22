"""Signal receivers of the project, connected by ``ManuspectrumConfig.ready()``."""

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from arches.app.models.models import GraphXPublishedGraph

from manuspectrum.views.summary_service import SLUG_CACHE_KEY


@receiver([post_save, post_delete], sender=GraphXPublishedGraph)
def drop_summary_graph_slugs(sender, **kwargs):
    """Drop the memoised slug map when a publication is written or removed.

    A model published under a new slug, or deleted, reaches the rollup paths on
    the next popup instead of when the hour-long entry expires.
    """
    cache.delete(SLUG_CACHE_KEY)
