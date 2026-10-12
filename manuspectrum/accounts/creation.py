"""Who created a resource, and which resources a transaction created.

One rule, used by the activity report (SQL), the embargo notices and the
abandoned-workflow cleanup (ORM): a resource is created by an ``edit_log`` row
``create`` (Arches writes one per ``Resource.save()``, and the Biblissima write
path writes its own) or by a ``tile create`` noted ``resource creation`` (what
Arches writes next to a ``create``, and the only mark of Biblissima resources
written before that path wrote a ``create`` row). Its creator is the ``userid``
of its earliest such row.
"""

import contextlib

from arches.app.models.models import EditLog
from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from django.utils import translation
from django.utils.translation import get_language

CREATION_NOTE = "resource creation"

#: The same rule as ``creation_q`` for a raw query on ``edit_log``.
CREATION_SQL = (
    "(edittype = 'create' OR (edittype = 'tile create' "
    f"AND note = '{CREATION_NOTE}'))"
)


def creation_q():
    return Q(edittype="create") | Q(edittype="tile create", note=CREATION_NOTE)


def _user_id(value):
    with contextlib.suppress(TypeError, ValueError):
        return int(value)
    return None


def creators_of(resource_ids):
    """``{resource id: user id}`` of the first creation row in the edit log."""
    ids = [str(pk) for pk in resource_ids]
    rows = (
        EditLog.objects.filter(resourceinstanceid__in=ids)
        .filter(creation_q())
        .order_by("timestamp")
        .values_list("resourceinstanceid", "userid")
    )
    found = {}
    for resource_id, user_id in rows:
        if resource_id in found:
            continue
        user_id = _user_id(user_id)
        if user_id is not None:
            found[resource_id] = user_id
    return found


def created_in_transaction(transaction_id):
    """``{resource id: user id or None}`` of the resources a transaction created.

    A resource whose edit log shows a row of another transaction older than
    its first row here existed before the transaction: it was reused, not
    created, and is left out.
    """
    rows = list(
        EditLog.objects.filter(transactionid=transaction_id)
        .filter(creation_q())
        .order_by("timestamp")
        .values_list("resourceinstanceid", "userid", "timestamp")
    )
    created = {}
    for resource_id, user_id, timestamp in rows:
        if resource_id not in created:
            created[resource_id] = (_user_id(user_id), timestamp)
    if not created:
        return {}
    earlier = (
        EditLog.objects.filter(resourceinstanceid__in=list(created))
        .exclude(transactionid=transaction_id)
        .values_list("resourceinstanceid", "timestamp")
    )
    reused = {
        resource_id
        for resource_id, timestamp in earlier
        if timestamp <= created[resource_id][1]
    }
    return {
        resource_id: user_id
        for resource_id, (user_id, _timestamp) in created.items()
        if resource_id not in reused
    }


def resource_label(resourceinstance):
    """The resource's display name in the active language, else any language."""
    descriptors = resourceinstance.descriptors or {}
    for language in (get_language(), *descriptors):
        name = (descriptors.get(language) or {}).get("name")
        if name:
            return name
    return str(resourceinstance.pk)


def resource_items(resources):
    """``[{"name", "url"}]`` for account mail: display name and absolute report link."""
    base = settings.PUBLIC_SERVER_ADDRESS.rstrip("/")
    items = []
    with translation.override(settings.LANGUAGE_CODE):
        for resource in resources:
            path = reverse("resource_report", kwargs={"resourceid": resource.pk})
            items.append({"name": resource_label(resource), "url": base + path})
    return items
