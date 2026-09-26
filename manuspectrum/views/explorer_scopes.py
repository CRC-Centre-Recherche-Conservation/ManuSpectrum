"""The export scope every Explorer product is built from (spec §4, §11).

The share payload, the IIIF manifest, ``series.csv`` and the data package take
the same parameters, ``?ids=`` (Selection keys), ``?document=<uuid>`` or
``?project=<uuid>``, and resolve them here into one ``ExportScope``: the
visible analyses and identified materials in corpus order, the per-key
narrowing of the Selection, and whose rights build the products.

Nothing is memoised here: the scope reads the memoised corpus bundle of its
reader (``explorer_memo``) and the visibility memos.
"""

import hashlib
import uuid
from dataclasses import dataclass

from django.conf import settings

from manuspectrum.utils.public_visibility import (
    anonymous_user,
    is_connected,
    readable_nodegroup_ids,
    visible_set,
)
from manuspectrum.utils.role_links import role_node
from manuspectrum.views.explorer_memo import ticket
from manuspectrum.views.explorer_service import (
    ITEM_KEY,
    ROLES,
    corpus_bundle,
    document_characterizations,
    linkable,
    parse_keys,
)
from manuspectrum.views.spectrum_preview import file_record

SCOPE_KINDS = ("ids", "document", "project")
ROLE_OF_KIND = {"micro-imaging": "micro", "chemical-imaging": "imaging"}


class ScopeError(ValueError):
    """The scope parameters are malformed: the caller answers 400 without a body."""


@dataclass(frozen=True, eq=False)
class ExportScope:
    """One resolved export scope.

    ``key`` is the canonical query (``ids=<sorted keys>``, ``document=<uuid>``
    or ``project=<uuid>``, then ``&canvases=all`` and ``&restricted=1`` when
    they apply) and ``digest`` its 12-hex sha1, which names minted IIIF ids
    and file names. ``analyses`` follow the corpus order of the bundle,
    ``characterizations`` and ``documents`` are sorted (documents by name).
    ``narrowed`` maps an analysis id to the ``file:<id>`` / ``layer:<n>``
    parts its keys named; an analysis absent from it is whole. ``missing``
    lists the ``ids`` keys that resolved to nothing visible. ``drafts``
    counts the kept analyses and materials in a Draft state. ``restricted``
    says the products are built with a signed-in reader's own rights and hold
    items the visitor cannot see; ``restricted_available`` counts, for a
    signed-in reader's default build only, the items left out for that
    reason. ``reader`` is whose rights build the products, ``viewer`` the
    requesting user, ``bundle`` the reader's corpus bundle in ``language``.
    """

    kind: str
    key: str
    digest: str
    subject: str | None
    analyses: tuple
    characterizations: tuple
    documents: tuple
    narrowed: dict
    missing: tuple
    drafts: int
    restricted: bool
    restricted_available: int
    canvases_all: bool
    reader: object
    viewer: object
    bundle: object
    language: str

    def names_visible(self, resource_ids):
        """The ids among *resource_ids* a product may name: ``linkable`` for the reader and the viewer, sorted."""
        kept = set(linkable(resource_ids, self.reader))
        if self.viewer is not self.reader:
            kept &= set(linkable(resource_ids, self.viewer))
        return sorted(kept)


@dataclass(frozen=True)
class _Items:
    analyses: frozenset
    characterizations: frozenset
    narrowed: dict


def export_language(query):
    """The language of a machine route: ``lang``, else ``LANGUAGE_CODE``.

    A code outside ``settings.LANGUAGES`` raises ``ScopeError``.
    """
    if "lang" not in query:
        return settings.LANGUAGE_CODE
    language = query.get("lang")
    if language not in dict(settings.LANGUAGES):
        raise ScopeError("unknown language")
    return language


def _parameters(query):
    """``(kind, value, canvases_all, restricted)`` of *query*, or ``ScopeError``."""
    given = [kind for kind in SCOPE_KINDS if kind in query]
    if len(given) != 1:
        raise ScopeError("exactly one scope parameter is expected")
    kind = given[0]
    if kind == "ids":
        value = parse_keys(query)
        if not value or len(value) > settings.EXPLORER_ITEMS_MAX:
            raise ScopeError("ids holds no key or too many")
        if not all(ITEM_KEY.match(key) for key in value):
            raise ScopeError("malformed key")
    else:
        values = query.getlist(kind)
        if len(values) != 1:
            raise ScopeError("one subject is expected")
        try:
            value = str(uuid.UUID(values[0]))
        except ValueError as error:
            raise ScopeError("the subject is not a UUID") from error
    canvases = query.getlist("canvases")
    if canvases and (kind != "document" or canvases != ["all"]):
        raise ScopeError("canvases=all is for a document scope only")
    restricted = query.getlist("restricted")
    if restricted and restricted != ["1"]:
        raise ScopeError("restricted takes 1 only")
    return kind, value, bool(canvases), bool(restricted)


def _items(kind, value, bundle):
    """The items *bundle* holds for one scope, or None when its subject is not visible."""
    visible = bundle.visible
    if kind == "document":
        if value not in visible.documents:
            return None
        return _Items(
            frozenset(row["id"] for row in bundle.by_document.get(value, [])),
            frozenset(document_characterizations(bundle, value)),
            {},
        )
    if kind == "project":
        if value not in visible.projects:
            return None
        analyses = frozenset(
            row["id"] for row in bundle.rows if value in row["projects"]
        )
        return _Items(
            analyses,
            frozenset(
                c
                for c in visible.characterizations
                if set(visible.evidence.get(c, ())) & analyses
            ),
            {},
        )
    analyses, characterizations, parts, whole = set(), set(), {}, set()
    for key in value:
        prefix, rid, sub = ITEM_KEY.match(key).groups()
        if prefix == "ch":
            if sub == "-" and rid in visible.characterizations:
                characterizations.add(rid)
            continue
        if rid not in bundle.by_id or (prefix == "an" and sub != "-"):
            continue
        analyses.add(rid)
        if prefix == "an":
            whole.add(rid)
        else:
            part = f"file:{sub}" if prefix == "af" else f"layer:{sub}"
            parts.setdefault(rid, set()).add(part)
    return _Items(
        frozenset(analyses),
        frozenset(characterizations),
        {rid: frozenset(p) for rid, p in parts.items() if rid not in whole},
    )


def _missing(keys, items):
    kept = items.analyses | items.characterizations
    missing = []
    for key in keys:
        prefix, rid, sub = ITEM_KEY.match(key).groups()
        whole_only = prefix in ("an", "ch") and sub != "-"
        if whole_only or rid not in kept:
            missing.append(key)
    return tuple(missing)


def _documents(bundle, analyses, characterizations):
    """The visible documents of *analyses* and of the objects of *characterizations*, in name order."""
    found = {bundle.chains[a][0] for a in analyses if a in bundle.chains}
    part_of = bundle.links["part_of"]
    for c in characterizations:
        for target in bundle.links["objects"].get(c, ()):
            found.add(target)
            found.update(part_of.get(target, ()))
    return tuple(d for d in bundle.documents if d in found)


def resolve_scope(query, user, language):
    """The ``ExportScope`` of *query* for *user* in *language*; None when nothing in it is visible.

    Exactly one of ``ids``, ``document`` and ``project`` is given: ``ids``
    holds at most ``EXPLORER_ITEMS_MAX`` keys, each matching ``ITEM_KEY``;
    ``document`` and ``project`` a UUID. ``canvases=all`` goes with
    ``document`` only and ``restricted`` takes ``1`` only. Anything else
    raises ``ScopeError``.

    A visitor builds as themself and ``restricted`` is ignored. A signed-in
    reader builds as the visitor (``anonymous_user()``) and keeps only what
    their own ``visible_set`` also holds; with ``restricted=1`` they build
    with their own rights. A document or project outside the reader's (or the
    viewer's) visible set resolves to None, like an unknown one. A document
    holds its analyses and the materials observed on it or its parts; a
    project the analyses it runs and the materials citing one of them in
    evidence. ``an:<id>:-`` keys keep a whole analysis, ``af:`` and ``im:``
    keys narrow it to a file or to the imaging manifest of a layer (the
    file's existence is checked when the files are read), ``ch:<id>:-`` keys
    keep an identified material; keys resolving to nothing visible go to
    ``missing``, and an ``ids`` scope with nothing left is None.
    """
    kind, value, canvases_all, wants_restricted = _parameters(query)
    connected = is_connected(user)
    restricted_build = connected and wants_restricted
    reader = user if restricted_build or not connected else anonymous_user()
    held = ticket(reader, language)
    bundle = corpus_bundle(reader, language, held)
    items = _items(kind, value, bundle)
    if items is None:
        return None
    restricted_available, viewer_ids = 0, None
    if connected and reader is not user:
        viewer_ids = visible_set(user).ids
        if kind != "ids" and value not in viewer_ids:
            return None
        items = _Items(
            items.analyses & viewer_ids,
            items.characterizations & viewer_ids,
            {a: p for a, p in items.narrowed.items() if a in viewer_ids},
        )
        viewer_items = _items(
            kind, value, corpus_bundle(user, language, ticket(user, language))
        )
        if viewer_items is not None:
            restricted_available = len(
                (viewer_items.analyses | viewer_items.characterizations)
                - (items.analyses | items.characterizations)
            )
    kept = items.analyses | items.characterizations
    if kind == "ids" and not kept:
        return None
    restricted = restricted_build and bool(kept - visible_set(anonymous_user()).ids)

    key = f"{kind}={','.join(value) if kind == 'ids' else value}"
    if canvases_all:
        key += "&canvases=all"
    if restricted:
        key += "&restricted=1"
    analyses = tuple(sorted(items.analyses, key=bundle.order.__getitem__))
    characterizations = tuple(sorted(items.characterizations))
    return ExportScope(
        kind=kind,
        key=key,
        digest=hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12],
        subject=None if kind == "ids" else value,
        analyses=analyses,
        characterizations=characterizations,
        documents=tuple(
            d
            for d in _documents(bundle, analyses, characterizations)
            if viewer_ids is None or d in viewer_ids
        ),
        narrowed=items.narrowed,
        missing=_missing(value, items) if kind == "ids" else (),
        drafts=len(kept & held.visible.unpublished),
        restricted=restricted,
        restricted_available=restricted_available,
        canvases_all=canvases_all,
        reader=reader,
        viewer=user,
        bundle=bundle,
        language=language,
    )


def _role_nodegroup(entry):
    role = ROLE_OF_KIND.get(entry.get("dataKind"), "files")
    node = role_node(*ROLES[role])
    return node.nodegroup_id if node else None


def kept_files(scope, analysis_id, files):
    """The entries of *files* (``FileEntry``) of one analysis that *scope* exports.

    A whole analysis keeps every entry; ``file:<id>`` keeps that measurement
    or micro-imaging entry, ``layer:<n>`` the imaging entry holding layer
    ``n``. An entry whose role nodegroup the viewer cannot read is dropped.
    """
    narrowed = scope.narrowed.get(analysis_id)
    readable = readable_nodegroup_ids(scope.viewer)
    kept = []
    for entry in files:
        if _role_nodegroup(entry) not in readable:
            continue
        if narrowed is not None:
            if entry.get("dataKind") == "chemical-imaging":
                parts = {
                    f"layer:{layer['index']}" for layer in entry.get("layers") or ()
                }
            else:
                parts = {f"file:{entry.get('id')}"}
            if not parts & narrowed:
                continue
        kept.append(entry)
    return kept


def scope_file(scope, analysis_id, file_id):
    """The stored path of one file of *scope*, or None when a gate refuses it.

    The file is read through its ``File`` row: the tile holding it belongs
    to *analysis_id*, the analysis is in the scope (and, when narrowed, the
    file is one of its named parts), and the tile's nodegroup is readable by
    both the reader and the viewer. A file id found in tile data alone is
    never trusted.
    """
    if analysis_id not in scope.analyses:
        return None
    try:
        file_id = str(uuid.UUID(str(file_id)))
    except ValueError:
        return None
    narrowed = scope.narrowed.get(analysis_id)
    if narrowed is not None and f"file:{file_id}" not in narrowed:
        return None
    record = file_record(file_id)
    if record is None:
        return None
    path, resource_id, _, nodegroup_id = record
    if resource_id != analysis_id:
        return None
    if nodegroup_id not in readable_nodegroup_ids(scope.reader):
        return None
    if nodegroup_id not in readable_nodegroup_ids(scope.viewer):
        return None
    return path
