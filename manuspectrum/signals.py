"""Signal receivers of the project, connected by ``ManuspectrumConfig.ready()``.

Every receiver drops a cache entry once the writing transaction commits: a
reader landing between the write and the commit would otherwise memoise the
old rows again.
"""

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from guardian.models import GroupObjectPermission, UserObjectPermission

from arches.app.models.models import GraphXPublishedGraph

from manuspectrum.views.summary_service import (
    RESTRICTED_CACHE_KEY,
    RESTRICTED_NODEGROUPS_CACHE_KEY,
    SLUG_CACHE_KEY,
)


@receiver([post_save, post_delete], sender=GraphXPublishedGraph)
def drop_summary_graph_slugs(sender, **kwargs):
    """Drop the memoised slug map when a publication is written or removed."""
    transaction.on_commit(lambda: cache.delete(SLUG_CACHE_KEY))


@receiver([post_save, post_delete], sender=UserObjectPermission)
@receiver([post_save, post_delete], sender=GroupObjectPermission)
def drop_summary_restriction_counts(sender, **kwargs):
    """Drop the memoised restriction counts when an object grant changes."""
    transaction.on_commit(
        lambda: cache.delete_many(
            [RESTRICTED_CACHE_KEY, RESTRICTED_NODEGROUPS_CACHE_KEY]
        )
    )
