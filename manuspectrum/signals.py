"""Signal receivers of the project, connected by ``ManuspectrumConfig.ready()``.

Every receiver drops a cache entry once the writing transaction commits: a
reader landing between the write and the commit would otherwise memoise the
old rows again.
"""

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver
from guardian.models import GroupObjectPermission, UserObjectPermission

from arches.app.models.models import File, FunctionXGraph, GraphXPublishedGraph

from manuspectrum.functions.resource_summary import SUMMARY_FUNCTION_ID, forget_config
from manuspectrum.utils.public_visibility import forget_visibility
from manuspectrum.views.spectrum_preview import file_record_key
from manuspectrum.views.summary_service import SLUG_CACHE_KEY


@receiver([post_save, post_delete], sender=GraphXPublishedGraph)
def drop_summary_graph_slugs(sender, **kwargs):
    """Drop the memoised slug map when a publication is written or removed."""
    transaction.on_commit(lambda: cache.delete(SLUG_CACHE_KEY))


@receiver([post_save, post_delete], sender=UserObjectPermission)
@receiver([post_save, post_delete], sender=GroupObjectPermission)
def drop_summary_restriction_counts(sender, **kwargs):
    """Drop the restriction counts and the visibility memos when an object grant changes."""
    transaction.on_commit(forget_visibility)


@receiver(m2m_changed, sender=User.groups.through)
@receiver(m2m_changed, sender=User.user_permissions.through)
@receiver(m2m_changed, sender=Group.permissions.through)
def drop_visibility_on_membership(sender, action, **kwargs):
    """Drop the visibility memos when a reader's groups or model permissions change.

    A group carries the model permissions behind ``read_nodegroup`` and the
    object grants its members inherit.
    """
    if action in ("post_add", "post_remove", "post_clear"):
        transaction.on_commit(forget_visibility)


@receiver(post_delete, sender=FunctionXGraph)
def drop_detached_summary_config(sender, instance, **kwargs):
    """Drop the configuration and the stamp once a summary attachment is gone.

    Attachment rows are deleted by the ``summary-config`` DELETE, the
    function manager's delete, the deletion of a graph (a draft included)
    or of a function, and the restoration of a graph from a serialized
    state (designer publish, model-history restore, graph or package
    import), which deletes each attachment and writes it again
    (arches/app/models/graph.py:571-592, 674-675). ``Graph.save()`` on a
    graph loaded from the database leaves the rows in place.
    """
    if str(instance.function_id) == str(SUMMARY_FUNCTION_ID):
        graph_id = instance.graph_id
        transaction.on_commit(lambda: forget_config(graph_id))


@receiver(post_delete, sender=File)
def drop_deleted_file_record(sender, instance, **kwargs):
    """Stop serving the preview of a file once its row is gone.

    Covers a file removed from a file-list, and a tile or a resource deleted
    with its files: the ORM cascade sends ``post_delete`` for each row.
    """
    key = file_record_key(instance.pk)
    transaction.on_commit(lambda: cache.delete(key))
