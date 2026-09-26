"""The export scope every Explorer product is built from (spec §4, §11).

The share payload, the IIIF manifest, ``series.csv`` and the data package take
the same parameters, ``?ids=`` (Selection keys), ``?document=<uuid>`` or
``?project=<uuid>``, and resolve them here into one ``ExportScope``: the
visible analyses and identified materials in corpus order and the per-key
narrowing of the Selection. Every product is built with the visitor's
rights (``anonymous_user()``), whoever asks (spec D59).

Nothing is memoised here: the scope reads the memoised corpus bundle of the
visitor (``explorer.memo``) and the visibility memos. ``share_payload`` is the
scope's summary for the « Share and export » panel, built per request.
"""

import functools
import hashlib
import os
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode

from arches.app.models.models import File
from django.conf import settings
from django.urls import reverse
from django.utils import translation

from manuspectrum.utils.public_visibility import anonymous_user, readable_nodegroup_ids
from manuspectrum.utils.role_links import role_node
from manuspectrum.views.explorer.citations import (
    Home,
    availability,
    citation_entries,
    shown_citation,
)
from manuspectrum.views.explorer.memo import ticket
from manuspectrum.views.explorer.service import (
    ITEM_KEY,
    ROLES,
    Values,
    analysis_files,
    cited_analysis,
    corpus_bundle,
    dataset_of,
    document_characterizations,
    licence_labels,
    linkable,
    manifest_json,
    names,
    parse_keys,
    permalink,
    product_link,
    renderer_configs,
)
from manuspectrum.views.summary_service import _date

SCOPE_KINDS = ("ids", "document", "project")
ROLE_OF_KIND = {"micro-imaging": "micro", "chemical-imaging": "imaging"}


class ScopeError(ValueError):
    """The scope parameters are malformed: the caller answers 400 without a body."""


@dataclass(frozen=True, eq=False)
class ExportScope:
    """One resolved export scope.

    ``key`` is the canonical query (``ids=<sorted keys that resolved>``,
    ``document=<uuid>``, ``project=<uuid>`` or
    ``project=<uuid>&document=<uuid>``, then ``&canvases=all`` when it
    applies) and ``digest`` its 12-hex sha1, which names minted IIIF ids
    and file names. ``params`` are the ``(name, value)`` pairs of ``key`` and
    ``query`` their URL-encoded form, which every link to a product carries. ``analyses`` follow the corpus order of the bundle,
    ``characterizations`` and ``documents`` are sorted (documents by name).
    ``narrowed`` maps an analysis id to the ``file:<id>`` / ``layer:<n>``
    parts its keys named; an analysis absent from it is whole. ``missing``
    lists the ``ids`` keys that resolved to nothing visible. ``drafts``
    counts the kept analyses and materials in a Draft state. ``reader`` is
    whose rights build the products (the visitor), ``bundle`` its corpus
    bundle in ``language``. ``nodegroups`` (the reader's readable
    nodegroups) and ``file_nodegroups`` are read once per scope.
    """

    kind: str
    key: str
    params: tuple
    digest: str
    subject: str | None
    analyses: tuple
    characterizations: tuple
    documents: tuple
    narrowed: dict
    missing: tuple
    drafts: int
    canvases_all: bool
    reader: object
    bundle: object
    language: str

    @property
    def query(self):
        """``params`` as a URL query; ``:`` and ``,`` stay readable."""
        return urlencode(self.params, safe=":,")

    @functools.cached_property
    def nodegroups(self):
        """The nodegroup ids the reader may read."""
        return readable_nodegroup_ids(self.reader)

    @functools.cached_property
    def read_manifest(self):
        """``manifest_json`` memoised for the products of this scope: each manifest is read once."""
        return functools.cache(manifest_json)

    @functools.cached_property
    def file_nodegroups(self):
        """``{file role: nodegroup id}`` of the roles ``kept_files`` reads."""
        return _role_nodegroups()

    def names_visible(self, resource_ids):
        """The ids among *resource_ids* a product may name: ``linkable`` for the reader, sorted."""
        return sorted(linkable(resource_ids, self.reader))


@dataclass(frozen=True)
class _Items:
    analyses: frozenset
    characterizations: frozenset
    narrowed: dict


def export_language(query):
    """The language of a machine route: ``lang``, else ``LANGUAGE_CODE``.

    Either way, a code outside ``settings.LANGUAGES`` raises ``ScopeError``.
    """
    language = query.get("lang") if "lang" in query else settings.LANGUAGE_CODE
    if language not in dict(settings.LANGUAGES):
        raise ScopeError("unknown language")
    return language


def _parameters(query):
    """``(kind, value, canvases_all, within)`` of *query*, or ``ScopeError``.

    *within* is the document a ``project`` scope is narrowed to by a
    ``document`` parameter given with it, else None.
    """
    given = [kind for kind in SCOPE_KINDS if kind in query]
    within = None
    if given == ["document", "project"]:
        within, given = _subject(query, "document"), ["project"]
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
        value = _subject(query, kind)
    canvases = query.getlist("canvases")
    if canvases and (kind != "document" or canvases != ["all"]):
        raise ScopeError("canvases=all is for a document scope only")
    return kind, value, bool(canvases), within


def _subject(query, kind):
    values = query.getlist(kind)
    if len(values) != 1:
        raise ScopeError("one subject is expected")
    try:
        return str(uuid.UUID(values[0]))
    except ValueError as error:
        raise ScopeError("the subject is not a UUID") from error


def _items(kind, value, bundle, within=None):
    """The items *bundle* holds for one scope, or None when its subject (or *within*) is not visible."""
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
        if value not in visible.projects or (
            within is not None and within not in visible.documents
        ):
            return None
        analyses = frozenset(
            row["id"]
            for row in bundle.rows
            if value in row["projects"]
            and (within is None or bundle.chains.get(row["id"], (None,))[0] == within)
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


def resolve_scope(query, language):
    """The ``ExportScope`` of *query* in *language*, built as the visitor; None when nothing in it is visible.

    Exactly one of ``ids``, ``document`` and ``project`` is given: ``ids``
    holds at most ``EXPLORER_ITEMS_MAX`` keys, each matching ``ITEM_KEY``;
    ``document`` and ``project`` a UUID. ``project`` may come with a
    ``document``, which narrows it to its items on that document.
    ``canvases=all`` goes with a ``document`` scope only. Anything else
    raises ``ScopeError``.

    Whoever asks, the scope is resolved with the visitor's rights
    (``anonymous_user()``). A document or project outside the visitor's
    visible set resolves to None, like an unknown one. A document
    holds its analyses and the materials observed on it or its parts; a
    project the analyses it runs and the materials citing one of them in
    evidence. ``an:<id>:-`` keys keep a whole analysis, ``af:`` and ``im:``
    keys narrow it to a file or to the imaging manifest of a layer (the
    file's existence is checked when the files are read), ``ch:<id>:-`` keys
    keep an identified material; keys resolving to nothing visible go to
    ``missing``, and an ``ids`` scope with nothing left is None.
    """
    kind, value, canvases_all, within = _parameters(query)
    reader = anonymous_user()
    bundle = corpus_bundle(reader, language, ticket(reader, language))
    items = _items(kind, value, bundle, within)
    if items is None:
        return None
    kept = items.analyses | items.characterizations
    if kind == "ids" and not kept:
        return None

    missing = _missing(value, items) if kind == "ids" else ()
    named = ",".join(k for k in value if k not in missing) if kind == "ids" else value
    params = [(kind, named)]
    if within:
        params.append(("document", within))
    if canvases_all:
        params.append(("canvases", "all"))
    key = "&".join(f"{name}={v}" for name, v in params)
    analyses = tuple(sorted(items.analyses, key=bundle.order.__getitem__))
    characterizations = tuple(sorted(items.characterizations))
    return ExportScope(
        kind=kind,
        key=key,
        params=tuple(params),
        digest=hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12],
        subject=None if kind == "ids" else value,
        analyses=analyses,
        characterizations=characterizations,
        documents=_documents(bundle, analyses, characterizations),
        narrowed=items.narrowed,
        missing=missing,
        drafts=len(kept & bundle.visible.unpublished),
        canvases_all=canvases_all,
        reader=reader,
        bundle=bundle,
        language=language,
    )


def _role_nodegroups():
    """``{role: nodegroup id}`` of the file roles ``kept_files`` reads."""
    found = {}
    for role in {*ROLE_OF_KIND.values(), "files"}:
        node = role_node(*ROLES[role])
        found[role] = node.nodegroup_id if node else None
    return found


def kept_files(scope, analysis_id, files):
    """The entries of *files* (``FileEntry``) of one analysis that *scope* exports.

    A whole analysis keeps every entry; ``file:<id>`` keeps that measurement
    or micro-imaging entry, ``layer:<n>`` the imaging entry holding layer
    ``n``. An entry whose role nodegroup the reader cannot read is dropped.
    """
    narrowed = scope.narrowed.get(analysis_id)
    readable = scope.nodegroups
    nodegroup_of = scope.file_nodegroups
    kept = []
    for entry in files:
        role = ROLE_OF_KIND.get(entry.get("dataKind"), "files")
        if nodegroup_of[role] not in readable:
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


def _file_uuid(file_id):
    try:
        return str(uuid.UUID(str(file_id)))
    except ValueError:
        return None


def scope_files(scope, wanted):
    """``{(analysis id, file id): stored path}`` of the pairs of *wanted* the gates of *scope* let through.

    Each file is read through its ``File`` row, all rows in one query: the
    tile holding it belongs to the analysis, the analysis is in the scope
    (and, when narrowed, the file is one of its named parts), and the tile's
    nodegroup is in ``scope.nodegroups``. A file id found in tile data alone
    is never trusted; a pair refused by a gate is absent from the answer.
    """
    asked = {}
    for analysis_id, file_id in wanted:
        normal = _file_uuid(file_id)
        if normal is None or analysis_id not in scope.analyses:
            continue
        narrowed = scope.narrowed.get(analysis_id)
        if narrowed is not None and f"file:{normal}" not in narrowed:
            continue
        asked[(analysis_id, file_id)] = normal
    if not asked:
        return {}
    storage = File._meta.get_field("path").storage
    rows = {
        str(fileid): (name, str(resource_id), str(nodegroup_id))
        for fileid, name, resource_id, nodegroup_id in File.objects.filter(
            pk__in=set(asked.values()), tile__isnull=False
        ).values_list(
            "fileid", "path", "tile__resourceinstance_id", "tile__nodegroup_id"
        )
    }
    found = {}
    for (analysis_id, file_id), normal in asked.items():
        name, resource_id, nodegroup_id = rows.get(normal, (None, None, None))
        if name and resource_id == analysis_id and nodegroup_id in scope.nodegroups:
            found[(analysis_id, file_id)] = storage.path(name)
    return found


def scope_file(scope, analysis_id, file_id):
    """The stored path of one file of *scope*, or None when a gate of ``scope_files`` refuses it."""
    return scope_files(scope, [(analysis_id, file_id)]).get((analysis_id, file_id))


def stored_sizes(scope, content):
    """``{(analysis id, file id): (path, size on disk)}`` of the data files of *content* that ``scope_files`` lets through.

    Imaging entries (manifests) and files missing on disk are left out.
    """
    paths = scope_files(
        scope,
        [
            (analysis_id, entry.get("id"))
            for analysis_id, entries in content.files.items()
            for entry in entries
            if entry.get("dataKind") != "chemical-imaging"
        ],
    )
    sizes = {}
    for pair, path in paths.items():
        try:
            sizes[pair] = (path, os.path.getsize(path))
        except OSError:
            continue
    return sizes


def export_size(stored):
    """``(files, bytes, over)`` of a data package holding the files of *stored* (``stored_sizes``).

    The one rule of the share estimate and of the export's 413: the data
    files ``scope_files`` lets through and that exist on disk, at their size
    on disk; *over* when they exceed ``EXPLORER_EXPORT_MAX_FILES`` or
    ``EXPLORER_EXPORT_MAX_BYTES``.
    """
    files = len(stored)
    size = sum(bytes_ for _, bytes_ in stored.values())
    over = (
        files > settings.EXPLORER_EXPORT_MAX_FILES
        or size > settings.EXPLORER_EXPORT_MAX_BYTES
    )
    return files, size, over


def share_link(scope):
    """Where the whole scope is available on the site: the report of its document or project, else the Explorer with the Selection."""
    if scope.subject:
        return permalink(scope.subject)
    with translation.override(scope.language):
        page = reverse("analysis-explorer").lstrip("/")
    selection = urlencode({"sel": scope.params[0][1]}, safe=":,")
    return f"{settings.PUBLIC_SERVER_ADDRESS}{page}?{selection}"


CONTENT_KEYS = ("dataset", "end", "files", "micro", "imaging")


@dataclass(frozen=True, eq=False)
class ScopeContent:
    """What the products of a scope read of its analyses, in one batched pass.

    ``rows`` are the corpus rows of ``scope.analyses`` in order, ``values``
    their tile values (``CONTENT_KEYS`` and any key asked for), ``files`` the
    kept ``FileEntry`` list of each analysis (``kept_files``), ``projects``
    the visible projects of each analysis, ``named`` the operators and
    projects the reader may name and ``label_of`` their names. ``groups`` are the ``citation_entries`` groups, one per analysis
    with its ``citation_home``, ``datasets`` and ``licences`` what
    ``availability`` reads.
    """

    rows: list
    values: object
    files: dict
    projects: dict
    named: frozenset
    label_of: dict
    groups: list
    datasets: list
    licences: list


def citation_home(scope, analysis_id, projects, label_of):
    """``Home`` an analysis without dataset is cited under: the scope's project, else its first named project by name, else its document.

    *projects* are the analysis's projects the reader may name. An analysis without project nor document has no home (None).
    """
    named = [p for p in projects if p in label_of]
    if scope.kind == "project" and scope.subject in named:
        home = scope.subject
    elif named:
        home = min(named, key=lambda p: (label_of[p]["value"].casefold(), p))
    else:
        chain = scope.bundle.chains.get(analysis_id)
        if not chain:
            return None
        document = chain[0]
        return Home(
            document, scope.bundle.label_of[document]["value"], permalink(document)
        )
    return Home(home, label_of[home]["value"], permalink(home))


def scope_content(scope, keys=()):
    """``ScopeContent`` of *scope*; *keys* are further ``ROLES`` read with the content keys."""
    bundle, language = scope.bundle, scope.language
    rows = [bundle.by_id[a] for a in scope.analyses]
    values = Values(
        list(scope.analyses),
        list(dict.fromkeys([*CONTENT_KEYS, *keys])),
        scope.reader,
    )
    configs = renderer_configs(values, scope.analyses)
    links = bundle.links
    projects_of = {
        row["id"]: [
            p
            for p in links["projects"].get(row["id"], ())
            if p in bundle.visible.projects
        ]
        for row in rows
    }
    named = frozenset(
        scope.names_visible(
            {o for row in rows for o in row["operators"]}
            | {p for ids in projects_of.values() for p in ids}
        )
    )
    label_of = names(named, language, scope.reader)
    files, groups, datasets, all_licences = {}, [], [], []
    for row in rows:
        analysis_id = row["id"]
        files[analysis_id] = kept_files(
            scope,
            analysis_id,
            analysis_files(
                analysis_id,
                scope.reader,
                language,
                values=values,
                configs=configs,
                read=scope.read_manifest,
            ),
        )
        end = values.first(analysis_id, "end")
        dataset = dataset_of(values.first(analysis_id, "dataset"))
        licences = licence_labels(files[analysis_id])
        all_licences += licences
        datasets.append(dataset)
        projects = [p for p in projects_of[analysis_id] if p in named]
        groups.append(
            (
                dataset,
                [
                    cited_analysis(
                        row,
                        _date(end) if isinstance(end, str) else None,
                        label_of,
                        [o for o in row["operators"] if o in named],
                        projects,
                    )
                ],
                licences,
                citation_home(scope, analysis_id, projects, label_of),
            )
        )
    return ScopeContent(
        rows=rows,
        values=values,
        files=files,
        projects=projects_of,
        named=named,
        label_of=label_of,
        groups=groups,
        datasets=datasets,
        licences=all_licences,
    )


def _per_document(scope):
    """``{document: query}``: the part of *scope* on each of its documents, in ``scope.documents`` order.

    A Selection keeps its keys whose analysis (or, for an identified
    material, one of whose objects) is on the document; a project becomes
    ``project=<uuid>&document=<uuid>``. A document scope has no split: ``{}``.
    """
    bundle = scope.bundle
    if scope.kind == "document":
        return {}
    if scope.kind == "project":
        return {
            d: urlencode([("project", scope.subject), ("document", d)])
            for d in scope.documents
        }
    keys_of = {d: [] for d in scope.documents}
    for key in scope.params[0][1].split(","):
        match = ITEM_KEY.match(key)
        if match is None:
            continue
        prefix, rid, _ = match.groups()
        if prefix == "ch":
            found = _documents(bundle, (), (rid,))
        else:
            found = bundle.chains.get(rid, (None,))[:1]
        for d in found:
            if d in keys_of:
                keys_of[d].append(key)
    return {
        d: urlencode([("ids", ",".join(keys))], safe=":,")
        for d, keys in keys_of.items()
        if keys
    }


def share_payload(scope, accessed):
    """``SharePayload`` of *scope*: counts, citations, availability, export estimate and product links.

    Citations follow ``citation_entries`` (one per dataset, then one per
    ``citation_home`` of the analyses without dataset), as their text and
    BibTeX (``shown_citation``); operators and projects are named only when
    the reader may name them. ``export`` counts the package as the export
    does (``export_size``); over the limits, a scope spanning several
    documents lists one export per document, holding the scope's items
    there (``_per_document``). ``manifest`` is given only when the scope's
    manifest holds a canvas (``has_canvases``), ``seriesCsv`` for a
    Selection holding spectra only. Each product is a ``product_link``: the
    panel follows its ``path`` and copies or hands external viewers its
    ``url``. *accessed* is the day of consultation.
    """
    from manuspectrum.views.explorer.manifest import has_canvases

    bundle, language = scope.bundle, scope.language
    content = scope_content(scope)
    rows = content.rows
    files_count, bytes_count, over = export_size(stored_sizes(scope, content))
    spectra = sum(
        1
        for row in rows
        for e in content.files[row["id"]]
        if e.get("dataKind") == "xy" and e.get("role") == "readable"
    )
    documents = []
    if over and scope.kind != "document" and len(scope.documents) > 1:
        documents = [
            {
                "id": d,
                "name": bundle.label_of[d],
                **product_link("explorer-export", query, language),
            }
            for d, query in _per_document(scope).items()
        ]
    return {
        "scope": {
            "kind": scope.kind,
            "key": scope.key,
            "analyses": len(scope.analyses),
            "characterizations": len(scope.characterizations),
            "spectra": spectra,
            "drafts": scope.drafts,
            "missing": list(scope.missing),
        },
        "citations": [
            shown_citation(entry)
            for entry in citation_entries(
                content.groups,
                language=language,
                accessed=accessed,
                link=share_link(scope),
            )
        ],
        "availability": availability(
            content.datasets,
            licences=content.licences,
            permalink=share_link(scope),
            language=language,
        ),
        "export": {
            "files": files_count,
            "bytes": bytes_count,
            "overLimit": over,
            "documents": documents,
        },
        "links": {
            "manifest": (
                product_link("iiif-v3-explorer-manifest", scope.query, language)
                if has_canvases(scope)
                else None
            ),
            "seriesCsv": (
                product_link("explorer-series-csv", scope.query, language)
                if scope.kind == "ids" and spectra
                else None
            ),
            "export": product_link("explorer-export", scope.query, language),
        },
    }
