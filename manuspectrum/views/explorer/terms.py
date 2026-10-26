"""Thesaurus closure of the Explorer's term facets: a selected term keeps its descendants.

One closure per controlled list, never across lists: two lists may hold the
same uri under different parents. A uri may occur several times in one list,
once per parent (``ListItem`` has one ``parent``); its ancestors are those of
every occurrence. Reads ``arches_controlled_lists_listitem`` and
``arches_controlled_lists_listitemvalue`` only, both watched by ``ms_data_change``.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from arches_controlled_lists.models import ListItem, ListItemValue
from django.db.models import F

from manuspectrum.utils.roles import ROLES
from manuspectrum.views.explorer.values import fold, label
from manuspectrum.views.summary_service import GraphIndex

TERM_FACETS = {
    "technique": "technique",
    "partType": "comp_type",
    "material": "material",
    "layer": "layer",
}
TERM_DEPTH = 16
LABEL_TYPES = ("prefLabel", "altLabel")


@dataclass(frozen=True)
class TermClosure:
    """``reach``: uri → frozenset of itself and its ancestors; ``parents``, ``labels``, ``terms``: by reached uri."""

    reach: dict = field(default_factory=dict)
    parents: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)
    terms: dict = field(default_factory=dict)

    def closed(self, uris):
        """The union of the reach of *uris*; a uri the list does not hold reaches itself."""
        return frozenset().union(
            *(self.reach.get(u, frozenset((u,))) for u in uris if u)
        )


def facet_list(key):
    """Id of the controlled list of the node of facet *key* (``TERM_FACETS``), or None."""
    slug, alias = ROLES[TERM_FACETS[key]]
    index = GraphIndex.for_slug(slug)
    return index.lists.get(alias) if index else None


def term_closures(lists, used, language):
    """``{key: TermClosure}`` of the uris *used* per facet key, each in its list ``lists[key]``.

    Two queries whatever the number of lists: their items, then the labels of
    the items reached. The occurrences of a uri are read root first, then by
    ``sortorder`` and id (Arches' label lookup order); a label is the
    prefLabel of *language*, English, the first language, then an altLabel,
    else the uri. ``terms`` holds every pref and alt label, folded. At most
    ``TERM_DEPTH`` levels are walked, each uri once. List ids are compared
    in their canonical form, whatever the case of the node config.
    """
    closures = {key: TermClosure() for key in used}
    wanted = {k: str(UUID(str(l))) for k, l in lists.items() if l and used.get(k)}
    if not wanted:
        return closures
    uri_of, occurrences = {}, defaultdict(lambda: defaultdict(list))
    for item_id, list_id, uri, parent_id in (
        ListItem.objects.filter(list_id__in=set(wanted.values()))
        .order_by(F("parent").asc(nulls_first=True), "sortorder", "id")
        .values_list("id", "list_id", "uri", "parent_id")
    ):
        uri_of[item_id] = uri
        occurrences[str(list_id)][uri].append((item_id, parent_id))
    parents_of = {
        list_id: {
            uri: {uri_of[p] for _, p in found if p in uri_of}
            for uri, found in by_uri.items()
        }
        for list_id, by_uri in occurrences.items()
    }
    reaches = {}
    for key, list_id in wanted.items():
        above, reach = parents_of.get(list_id, {}), {}
        for uri in sorted(u for u in used[key] if u):
            found, frontier = {uri}, {uri}
            for _ in range(TERM_DEPTH):
                frontier = {p for u in frontier for p in above.get(u, ())} - found
                if not frontier:
                    break
                found |= frontier
            reach[uri] = frozenset(found)
        reaches[key] = reach
    items = {
        item_id
        for key, reach in reaches.items()
        for uri in set().union(*reach.values())
        for item_id, _ in occurrences[wanted[key]].get(uri, ())
    }
    values = defaultdict(list)
    for item_id, valuetype, lang, text in ListItemValue.objects.filter(
        list_item_id__in=list(items), valuetype_id__in=LABEL_TYPES
    ).values_list("list_item_id", "valuetype_id", "language_id", "value"):
        values[item_id].append((valuetype, lang or "", text))
    for key, reach in reaches.items():
        list_id, reached = wanted[key], set().union(*reach.values())
        labels, texts = {}, {}
        for uri in reached:
            preferred, other, folded = {}, {}, set()
            for item_id, _ in occurrences[list_id].get(uri, ()):
                for valuetype, lang, text in values[item_id]:
                    (preferred if valuetype == "prefLabel" else other).setdefault(
                        lang, text
                    )
                    folded.add(fold(text))
            labels[uri] = (
                label(preferred, language)
                or label(other, language)
                or {"value": uri, "lang": language}
            )
            texts[uri] = frozenset(folded)
        closures[key] = TermClosure(
            reach=reach,
            parents={
                u: tuple(
                    sorted(p for p in parents_of[list_id].get(u, ()) if p in reached)
                )
                for u in reached
            },
            labels=labels,
            terms=texts,
        )
    return closures
