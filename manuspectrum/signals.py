"""Signal receivers of the project, connected by ``ManuspectrumConfig.ready()``.

Every model receiver drops a cache entry once the writing transaction
commits: a reader landing between the write and the commit would otherwise
memoise the old rows again. The logout receiver revokes the IIIF tokens of
the session at once.
"""

from django.contrib.auth.models import Group, User
from django.contrib.auth.signals import user_logged_out
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from guardian.models import GroupObjectPermission, UserObjectPermission

from arches.app.models.models import File, FunctionXGraph, GraphXPublishedGraph

from manuspectrum.accounts.embargo import record_grant
from manuspectrum.accounts.lockout import current_request
from manuspectrum.functions.resource_summary import SUMMARY_FUNCTION_ID, forget_config
from manuspectrum.accounts.retention import send_deactivation_notice
from manuspectrum.iiif.tokens import revoke
from manuspectrum.utils.public_visibility import ANONYMOUS_USERNAME, forget_visibility
from manuspectrum.views.spectrum_preview import file_record_key
from manuspectrum.views.summary_service import SLUG_CACHE_KEY, graph_index_key


@receiver([post_save, post_delete], sender=GraphXPublishedGraph)
def drop_summary_graph_slugs(sender, instance, **kwargs):
    """Drop the memoised slug map and the graph's index when a publication is written or removed."""
    keys = [SLUG_CACHE_KEY, graph_index_key(instance.graph_id)]
    transaction.on_commit(lambda: cache.delete_many(keys))


@receiver([post_save, post_delete], sender=UserObjectPermission)
@receiver([post_save, post_delete], sender=GroupObjectPermission)
def drop_summary_restriction_counts(sender, **kwargs):
    """Drop the restriction counts and the visibility memos when an object grant changes."""
    transaction.on_commit(forget_visibility)


@receiver(post_save, sender=UserObjectPermission)
@receiver(post_save, sender=GroupObjectPermission)
def record_restriction_on_grant(sender, instance, created, **kwargs):
    """Record who restricted a resource, once the grant's transaction commits.

    Only a grant to the visitor or to one of its groups on a resource instance
    can restrict it. The request user is the one who set it; the daily pass
    records restrictions written outside a request with no setter.
    """
    if not created or instance.content_type.model != "resourceinstance":
        return
    grantee = getattr(instance, "user", None) or getattr(instance, "group", None)
    transaction.on_commit(
        lambda: record_grant(instance.object_pk, grantee, current_request())
    )


@receiver(pre_save, sender=User)
def remember_user_was_active(sender, instance, update_fields=None, **kwargs):
    """Capture whether the account was active before this save."""
    instance._was_active = None
    if instance.pk is None or (update_fields and "is_active" not in update_fields):
        return
    instance._was_active = (
        User.objects.filter(pk=instance.pk).values_list("is_active", flat=True).first()
    )


@receiver(post_save, sender=User)
def notify_user_deactivated(sender, instance, created, **kwargs):
    """Mail the user once their account goes from active to inactive.

    The retention pass marks its own save (`skip_deactivation_notice`) and
    sends nothing here; `anonymous` and accounts without an address are
    skipped by the mail itself. `QuerySet.update()` sends no signal.
    """
    was_active, instance._was_active = getattr(instance, "_was_active", None), None
    if (
        created
        or not was_active
        or instance.is_active
        or getattr(instance, "skip_deactivation_notice", False)
        or instance.username == ANONYMOUS_USERNAME
    ):
        return
    transaction.on_commit(lambda: send_deactivation_notice(instance))


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


@receiver(user_logged_out)
def revoke_iiif_tokens(sender, request=None, **kwargs):
    """End the IIIF tokens and access cookie of the session signing out of Arches."""
    session = getattr(request, "session", None)
    revoke(getattr(session, "session_key", None))
