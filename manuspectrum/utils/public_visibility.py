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

import hashlib
import logging
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from guardian.models import GroupObjectPermission, UserObjectPermission

from arches.app.models.models import Node, ResourceInstance
from arches.app.utils.permission_backend import user_can_read_resource

from manuspectrum.utils.cache import get_or_build
from manuspectrum.utils.data_version import data_version

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


def readable_graph_ids(user):
    """Ids of the resource models ``user`` may read, as strings.

    A model is readable when at least one of its nodegroups is in
    ``readable_nodegroup_ids(user)``: the rule ``user_can_read_resource``
    applies to a resource without an object grant
    (``user_has_resource_model_permissions``,
    arches/app/permissions/arches_permission_base.py:277-302, 322-326).
    Memoised per reader and permission epoch.
    """
    key = f"public-visibility:graphs:{_epoch()}:{getattr(user, 'id', None)}"
    return get_or_build(key, lambda: _graphs_of(user), PERM_SCOPE_TTL) or (frozenset())


def _graphs_of(user):
    readable = readable_nodegroup_ids(user)
    if not readable:
        return frozenset()
    return frozenset(
        str(graph_id)
        for graph_id in Node.objects.filter(nodegroup_id__in=list(readable))
        .values_list("graph_id", flat=True)
        .distinct()
    )


def forget_visibility():
    """Start every visibility memo over."""
    cache.delete_many(
        [EPOCH_CACHE_KEY, RESTRICTED_CACHE_KEY, RESTRICTED_NODEGROUPS_CACHE_KEY]
    )


def permission_epoch():
    """The token every visibility memo key carries; ``forget_visibility`` replaces it."""
    return _epoch()


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


def explorer_scope(user):
    """Scope of the Explorer's memos: ``"public"`` shared by every reader, else ``reader_scope``.

    Shared only while ``perm_scope`` finds no restriction in the deployment
    and the reader has readable nodegroups: a reader without a profile never
    lands on the shared entry.
    """
    from manuspectrum.views.summary_service import perm_scope

    if perm_scope(user) == "public" and readable_nodegroup_ids(user):
        return "public"
    return reader_scope(user)


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


EXPLORER_MODELS = (
    "document",
    "component",
    "analysis",
    "project",
    "sample",
    "characterization",
)


@dataclass(frozen=True)
class VisibleSet:
    """What one reader may see through the Explorer and the project IIIF collection."""

    documents: frozenset = frozenset()
    components: frozenset = frozenset()
    analyses: frozenset = frozenset()
    projects: frozenset = frozenset()
    samples: frozenset = frozenset()
    characterizations: frozenset = frozenset()
    unpublished: frozenset = frozenset()
    evidence: dict = field(default_factory=dict)
    digest: str = ""

    @property
    def ids(self):
        return (
            self.documents
            | self.components
            | self.analyses
            | self.projects
            | self.samples
            | self.characterizations
        )


def visible_set(user, version=None):
    """The resources *user* may see in the Explorer, decided once (spec §4, D33, D37, D50).

    A resource is hidden only by a read restriction: it is in
    ``hidden_resource_ids(user)``, its model is outside
    ``readable_graph_ids(user)``, or a link it needs runs through a nodegroup
    outside ``readable_nodegroup_ids(user)``. A resource in a Draft lifecycle
    state is visible to every reader, the visitor included, and belongs to
    ``unpublished``; an analysis whose visible objects observed are all
    unpublished is unpublished too. A Component needs a visible Document, an
    Analysis a visible Component or Document through a readable relation
    nodegroup and no hidden Project (a Draft Project hides nothing), a Sample
    a visible Analysis using it, an identified material a visible object
    observed and at least one visible analysis cited in evidence. Links are
    read off the tiles.

    Memoised per reader, permission epoch and data version (*version*, a
    ``data_version()`` the caller already read, else read here) for
    ``PERM_SCOPE_TTL``: a lifecycle change or a new link shows at the next
    request, a grant written without a signal within that delay. ``digest``
    names the sets and the reader's gates they were decided with (hidden
    resources, readable nodegroups and models): two readers with the same
    digest see the same thing.
    """
    version = data_version() if version is None else version
    key = f"public-visibility:visible:{_epoch()}:{version}:{reader_scope(user)}"
    return get_or_build(key, lambda: _visible_for(user), PERM_SCOPE_TTL)


def _visible_for(user):
    from manuspectrum.utils.role_links import graph_id_of, readable_links

    hidden = hidden_resource_ids(user)
    nodegroups = readable_nodegroup_ids(user)
    graphs = readable_graph_ids(user)
    drafts = draft_state_id_set()
    slug_of = {graph_id_of(slug): slug for slug in EXPLORER_MODELS}
    slug_of.pop(None, None)

    existing = {slug: set() for slug in EXPLORER_MODELS}
    candidates = {slug: set() for slug in EXPLORER_MODELS}
    unpublished = set()
    for rid, graph_id, state in ResourceInstance.objects.filter(
        graph_id__in=list(slug_of)
    ).values_list(
        "resourceinstanceid", "graph_id", "resource_instance_lifecycle_state_id"
    ):
        rid, slug = str(rid), slug_of[str(graph_id)]
        existing[slug].add(rid)
        if rid in hidden or str(graph_id) not in graphs:
            continue
        if state is not None and str(state) in drafts:
            unpublished.add(rid)
        candidates[slug].add(rid)

    def links(slug, alias, readable_only=True):
        return readable_links(slug, alias, nodegroups if readable_only else None)

    documents = candidates["document"]
    part_of = links("component", "item_visual_is_part_of_document")
    components = {c for c in candidates["component"] if part_of[c] & documents}
    projects = candidates["project"]
    observed = links("analysis", "component_observed")
    project_of = links("analysis", "analysis_by_project", readable_only=False)
    objects = documents | components
    analyses = {
        a
        for a in candidates["analysis"]
        if observed[a] & objects
        and not ((project_of[a] & existing["project"]) - projects)
    }
    sample_of = links("analysis", "sample_used")
    samples = {s for a in analyses for s in sample_of[a] if s in candidates["sample"]}
    observed_by = links("characterization", "object_observed")
    evidence_of = links("characterization", "evidence_analyses")
    evidence = {}
    for c in candidates["characterization"]:
        cited = evidence_of[c] & analyses
        if observed_by[c] & objects and cited:
            evidence[c] = tuple(sorted(cited))

    published_objects = {d for d in documents if d not in unpublished} | {
        c
        for c in components
        if c not in unpublished and part_of[c] & documents - unpublished
    }
    for a in analyses:
        if not (observed[a] & published_objects):
            unpublished.add(a)

    sets = {
        "documents": frozenset(documents),
        "components": frozenset(components),
        "analyses": frozenset(analyses),
        "projects": frozenset(projects),
        "samples": frozenset(samples),
        "characterizations": frozenset(evidence),
        "unpublished": frozenset(unpublished),
    }
    digest = hashlib.sha1(usedforsecurity=False)
    for name, ids in [
        *sets.items(),
        ("hidden", hidden),
        ("nodegroups", nodegroups),
        ("graphs", graphs),
    ]:
        digest.update(f"{name}:{','.join(sorted(map(str, ids)))};".encode())
    for c in sorted(evidence):
        digest.update(f"{c}>{','.join(evidence[c])};".encode())
    return VisibleSet(**sets, evidence=evidence, digest=digest.hexdigest())
