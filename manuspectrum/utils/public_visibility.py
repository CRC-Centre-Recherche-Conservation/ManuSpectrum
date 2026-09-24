"""What a reader may see, decided by the Arches permission framework.

The single entry point for the project surfaces that list or serve
resources outside the Arches UI: thumbnails, the IIIF annotation collection
and the sitemap. Arches core routes (``files/``,
``manifest/``, ``iiifannotations``, the querysets API) keep core behaviour.

``hidden_resource_ids(user)`` is the set of resource ids carrying an
instance-level restriction that ``user_can_read_resource`` resolves against
the reader: a ``no_access_to_resourceinstance`` grant on the reader or one of
its groups, and equally a grant set that leaves ``view_resourceinstance``
out (``check_resource_instance_permissions``,
arches/app/permissions/arches_default_allow.py:256-333). The candidates are
the resources carrying any object grant, plus every resource of a graph named
in ``PERMISSION_DEFAULTS`` (``get_default_permissions``,
arches_permission_base.py:576-632); the decision on each is Arches' own.

``get_filtered_instances`` is not used: for one reader it reads
``permissions.users_with_no_access`` off Elasticsearch
(arches_default_allow.py:236-255), which misses a grant set without ``view``
(``get_restricted_users`` puts those readers in ``cannot_read`` only,
:168-175) and any grant written without ``resource.index()``; with
``allresources=True`` it returns every resource restricted for anyone.

A resource without any grant falls back to the reader's nodegroup rights on
its model and is never in the set: a surface serving one resource still asks
``user_can_read_resource``.

Both sets are memoised per reader for ``PERM_SCOPE_TTL`` under a permission
epoch. ``manuspectrum.signals`` drops the epoch once a transaction writing an
object grant, a group membership or a model permission commits, so every
memo starts over. Guardian's bulk ``assign_perm`` on a queryset
(``bulk_create``) sends no signal; the TTL bounds that case.
"""

import logging
import uuid

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from guardian.models import GroupObjectPermission, UserObjectPermission

from arches.app.models.models import ResourceInstance
from arches.app.utils.permission_backend import user_can_read_resource

from manuspectrum.utils.cache import get_or_build

logger = logging.getLogger(__name__)

PERM_SCOPE_TTL = 60
RESTRICTED_CACHE_KEY = "summary-restricted-resources"
RESTRICTED_NODEGROUPS_CACHE_KEY = "summary-restricted-nodegroups"
EPOCH_CACHE_KEY = "public-visibility-epoch"

_ON_RESOURCE = {
    "content_type__app_label": "models",
    "content_type__model": "resourceinstance",
}


def anonymous_user():
    """The ``anonymous`` row ``SetAnonymousUser`` installs on a visitor.

    Without that row the Django ``AnonymousUser`` stands in, which Arches
    lets read nothing.
    """
    return User.objects.filter(username="anonymous").first() or AnonymousUser()


def granted_resource_ids():
    """Ids of the resources carrying an object grant, users and groups together."""
    ids = set()
    for model in (UserObjectPermission, GroupObjectPermission):
        ids.update(
            str(pk)
            for pk in model.objects.filter(**_ON_RESOURCE).values_list(
                "object_pk", flat=True
            )
        )
    return ids


def resource_grant_count():
    """Object grants on resource instances, any codename, plus default-permission graphs.

    Any grant can take a resource away from someone: ``no_access`` does, and
    so does a grant set that leaves ``view`` out, which denies read to its
    holder without naming ``no_access``.
    """
    grants = sum(
        model.objects.filter(**_ON_RESOURCE).count()
        for model in (UserObjectPermission, GroupObjectPermission)
    )
    return grants + len(getattr(settings, "PERMISSION_DEFAULTS", None) or {})


def hidden_resource_ids(user):
    """Ids of the resources carrying a grant that denies ``user`` read access.

    Empty for a superuser. Memoised per reader and permission epoch.
    """
    if getattr(user, "is_superuser", False):
        return frozenset()
    key = f"public-visibility:hidden:{_epoch()}:{getattr(user, 'id', None)}"
    return get_or_build(key, lambda: _hidden_for(user), PERM_SCOPE_TTL)


def readable_nodegroup_ids(user):
    """Ids of the nodegroups ``user`` may read, as strings.

    Arches' ``viewable_nodegroups`` (``get_nodegroups_by_perm`` on
    ``models.read_nodegroup``, arches/app/models/models.py:2183-2191),
    memoised per reader and permission epoch. A reader without a profile
    reads none, and that answer is not memoised.
    """
    key = f"public-visibility:nodegroups:{_epoch()}:{getattr(user, 'id', None)}"
    return get_or_build(key, lambda: _nodegroups_of(user), PERM_SCOPE_TTL) or (
        frozenset()
    )


def forget_visibility():
    """Start every visibility memo over."""
    cache.delete_many(
        [EPOCH_CACHE_KEY, RESTRICTED_CACHE_KEY, RESTRICTED_NODEGROUPS_CACHE_KEY]
    )


def _epoch():
    epoch = cache.get(EPOCH_CACHE_KEY)
    if epoch is None:
        cache.add(EPOCH_CACHE_KEY, uuid.uuid4().hex, None)
        epoch = cache.get(EPOCH_CACHE_KEY)
    return epoch


def _hidden_for(user):
    candidates = ResourceInstance.objects.filter(pk__in=granted_resource_ids())
    defaults = getattr(settings, "PERMISSION_DEFAULTS", None) or {}
    if defaults:
        candidates = candidates | ResourceInstance.objects.filter(
            graph_id__in=list(defaults)
        )
    return frozenset(
        str(resource.pk)
        for resource in candidates.distinct()
        if not user_can_read_resource(user, resource=resource)
    )


def _nodegroups_of(user):
    try:
        return frozenset(user.userprofile.viewable_nodegroups)
    except (AttributeError, ObjectDoesNotExist) as error:
        logger.warning("visibility: no profile for reader %s: %s", user, error)
        return None


def is_connected(user):
    """Whether *user* is a signed-in account, not the visitor.

    ``SetAnonymousUser`` installs the ``anonymous`` database row on a visitor,
    whose ``is_authenticated`` is True, so the test compares primary keys.
    """
    if (
        not getattr(user, "is_authenticated", False)
        or getattr(user, "pk", None) is None
    ):
        return False
    anonymous = anonymous_user()
    return user.pk != getattr(anonymous, "pk", None)


def reader_scope(user):
    """``"anonymous"`` for a visitor, else the user id: the key of what a reader sees."""
    return str(user.pk) if is_connected(user) else "anonymous"


def draft_state_id_set():
    """Ids, as strings, of the lifecycle states that mean "not published yet"."""
    from arches.app.models.models import ResourceInstanceLifecycleState

    from manuspectrum.views.model_graph_service import draft_state_ids

    return frozenset(
        str(state_id)
        for state_id in draft_state_ids(
            ResourceInstanceLifecycleState.objects.values(
                "id", "is_initial_state", "resource_instance_lifecycle_id"
            )
        )
    )
