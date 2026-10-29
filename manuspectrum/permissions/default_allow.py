"""Arches' default-allow permission framework, with a bounded restricted-ids search.

Subclass of ``arches.app.permissions.arches_default_allow.
ArchesDefaultAllowPermissionFramework`` (Arches 8.1.5, l.194-260), selected by
``PERMISSION_FRAMEWORK``. Only ``get_restricted_instances`` differs, and only
in its Elasticsearch branch (a non-superuser, ``allresources=False``): every
other path is the parent's.

The core method opens a scroll context (``scroll="1m"``) on every call and
never clears it. ``MVTTiler.createTile`` calls it once per map tile, so a map
being panned fills Elasticsearch's 500 scroll contexts, which then refuses
every search of the site (429) and makes the client put the node on a 30 s
timeout. This version asks for one plain page, which is the whole answer
whenever the total fits in ``SEARCH_RESULT_LIMIT``, and scrolls only beyond
it, clearing the context when it is done. The ids returned are the core's.

Remove this module, and ``PERMISSION_FRAMEWORK`` in the settings, once Arches
releases a ``get_restricted_instances`` that does not leave a scroll open.
"""

import logging

from arches.app.models.system_settings import settings
from arches.app.permissions.arches_default_allow import (
    ArchesDefaultAllowPermissionFramework,
)
from arches.app.search.elasticsearch_dsl_builder import Bool, Ids, Nested, Query, Terms
from arches.app.search.mappings import RESOURCES_INDEX

logger = logging.getLogger(__name__)

SCROLL_KEEP_ALIVE = "1m"


class ManuSpectrumDefaultAllowPermissionFramework(
    ArchesDefaultAllowPermissionFramework
):
    def get_restricted_instances(
        self, user, search_engine=None, allresources=False, resources=None
    ):
        if allresources is True or user.is_superuser is True:
            return super().get_restricted_instances(
                user, search_engine, allresources, resources
            )

        limit = settings.SEARCH_RESULT_LIMIT
        terms = Terms(field="permissions.users_with_no_access", terms=[str(user.id)])
        has_access = Bool()
        has_access.must(Nested(path="permissions", query=terms))
        if resources is not None:
            has_access.filter(Ids(ids=resources))
        query = Query(search_engine, start=0, limit=limit)
        query.add_query(has_access)

        results = query.search(index=RESOURCES_INDEX)
        total = results["hits"]["total"]
        if total["relation"] == "eq" and total["value"] <= limit:
            return [hit["_id"] for hit in results["hits"]["hits"]]
        return self._scrolled_ids(query)

    @staticmethod
    def _scrolled_ids(query):
        """Every id the query matches, the scroll context cleared on the way out.

        Pages are read until one is empty, so the count never depends on a
        total that Elasticsearch may report as a lower bound.
        """
        results = query.search(index=RESOURCES_INDEX, scroll=SCROLL_KEEP_ALIVE)
        scroll_id = results["_scroll_id"]
        try:
            ids = [hit["_id"] for hit in results["hits"]["hits"]]
            while results["hits"]["hits"]:
                results = query.se.es.scroll(
                    scroll_id=scroll_id, scroll=SCROLL_KEEP_ALIVE
                )
                scroll_id = results.get("_scroll_id", scroll_id)
                ids.extend(hit["_id"] for hit in results["hits"]["hits"])
            return ids
        finally:
            try:
                query.se.es.clear_scroll(scroll_id=scroll_id)
            except Exception:
                logger.warning("Could not clear a scroll context", exc_info=True)
