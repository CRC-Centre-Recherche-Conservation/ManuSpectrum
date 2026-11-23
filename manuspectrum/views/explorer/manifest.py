"""The Explorer's IIIF Presentation 3 manifest of a scope (spec §11.1), assembled from an ``ExportScope``.

The IIIF shapes (page references, labels, homepages, metadata) are those of
``iiif.manifest``; this module decides, from the scope, which canvases the
manifest holds and which pages each references. Nothing is memoised.

Canvases resolve in this order:

1. Each document of the scope gives its source manifest (the
   ``doc_manifest`` role, legacy host rewritten, read by ``manifest_json``);
   a document without one, or whose manifest cannot be read, gives no
   canvas.
2. A zone is stored under a canvas id or under the image service Arches'
   viewer drew (``canvas_index`` maps both to the canvas id). A zone on a
   canvas the source manifest does not list is ignored.
3. An analysis is placed by its zones on the canvases of its own document.
   An analysis with no placed zone is listed in ``metadata`` with its
   permalink.
4. An identified material is placed on the canvas of its first zone by
   the rule of its IIIF pages (``iiif.facts.CharacterizationZones``): its
   own zones, else those of the visible Components it observes. A zone
   whose nodegroup the reader cannot read counts as absent, for analyses
   and materials alike.
5. The canvases kept are those carrying a zone of a kept analysis or
   material, or every canvas of the document with ``canvases=all``. Only
   folios are canvases: the imaging manifests of the kept analyses are
   referenced by their IIIF id in the « Chemical imaging » metadata, never
   copied.
"""

import functools
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlencode

from django.conf import settings

from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.facts import (
    CharacterizationZones,
    aggregate_metadata,
    analysis_aggregate,
    document_facts,
    listed_source,
    names_of,
    subject_of,
)
from manuspectrum.iiif.manifest import (
    Canvases,
    EmbeddedPages,
    Header,
    ManifestTooLarge,
    canvas_annotations,
    drafts_summary,
    homepages,
    imaging_metadata,
    manifest_header,
    manifest_label,
    page_filter,
    summary_counts,
    unlocated_metadata,
)
from manuspectrum.iiif.pages import with_context
from manuspectrum.iiif.sources import (
    canvas_thumbnail,
    canvases_of,
    manifest_id,
    raw_canvases,
    v3_canvas,
)
from manuspectrum.iiif.zones import FeatureRows
from manuspectrum.utils.data_version import data_version
from manuspectrum.utils.role_links import role_node
from manuspectrum.utils.public_visibility import anonymous_user
from manuspectrum.utils.roles import ROLES
from manuspectrum.views.explorer.scopes import (
    kept_files,
    scope_content,
    spectra_count,
)
from manuspectrum.views.explorer.service import (
    Values,
    document_characterizations,
    imaging_entries,
    permalink,
    product_url,
)
from manuspectrum.views.explorer.values import rewrite_legacy_url

__all__ = [
    "ManifestTooLarge",
    "build_manifest",
    "canvas_plan",
    "manifest_offer",
]


@dataclass(frozen=True)
class _Placement:
    """Where the elements of a scope fall on one document's manifest (``_placements``).

    ``url`` is the source manifest's id (``sources.manifest_id``: a stored
    manifest's IIIF route, else its absolute URL). ``number`` gives each
    listed canvas its page number. ``analyses`` and ``materials`` map a
    canvas id to the kept analysis and material ids placed on it; ``whole``
    says the scope keeps the whole document.
    """

    document: str
    url: str
    source: object
    raw: dict
    position: dict
    number: dict
    scope_analyses: list
    analyses: dict
    first: dict
    materials: dict
    kept: list
    whole: bool


def _placements(scope, bounded=True):
    """One ``_Placement`` per document of *scope*, in order, each built when it is reached.

    The local source manifests, the analysis zones and the material zones
    of the whole scope are read before the first document is placed, a
    fixed number of queries; a remote source manifest is read when its
    document is reached. Zones are read from ``scope.nodegroups``.
    When *bounded*, ``ManifestTooLarge`` is raised as soon as the kept
    canvases of the documents placed so far exceed
    ``EXPLORER_MANIFEST_MAX_CANVASES``.
    """
    bundle, reader = scope.bundle, scope.reader
    readable = scope.nodegroups
    doc_values = Values(list(scope.documents), ["doc_manifest"], reader)
    urls = {
        d: rewrite_legacy_url(doc_values.first(d, "doc_manifest") or "")
        for d in scope.documents
    }
    scope.read_manifest.prime(u for u in urls.values() if u)
    chosen_analyses = set(scope.analyses)
    chosen_characterizations = set(scope.characterizations)
    located, materials_of = {}, {}
    for document in scope.documents:
        scope_analyses = [
            a for a in scope.analyses if bundle.chains.get(a, (None,))[0] == document
        ]
        visible = {row["id"] for row in bundle.by_document.get(document, [])}
        located[document] = (
            scope_analyses,
            sorted(visible & chosen_analyses | set(scope_analyses)),
        )
        materials_of[document] = sorted(
            c
            for c in document_characterizations(bundle, document)
            if c in chosen_characterizations and c in bundle.visible.characterizations
        )
    zones = FeatureRows(
        role_node(*ROLES["zone"]),
        sorted({a for _, ids in located.values() for a in ids}),
        readable,
    )
    all_materials = sorted({c for ids in materials_of.values() for c in ids})
    material_zones = (
        CharacterizationZones(all_materials, bundle.visible, readable)
        if all_materials
        else None
    )
    limit = settings.EXPLORER_MANIFEST_MAX_CANVASES
    planned = set()
    for document in scope.documents:
        url = urls[document]
        source = scope.read_manifest(url) if url else None
        listed = canvases_of(source)
        position = {c["id"]: c for c in listed}
        number = {c["id"]: n for n, c in enumerate(listed, start=1)}
        placing = listed_source(url, listed)
        scope_analyses, analysis_ids = located[document]
        analyses, first = defaultdict(list), {}
        for rid, _, canvas, _ in zones.located(analysis_ids, placing.dims):
            if canvas not in position:
                continue
            if rid not in analyses[canvas]:
                analyses[canvas].append(rid)
            first.setdefault(rid, canvas)
        materials = defaultdict(list)
        if materials_of[document]:
            placed = material_zones.on(materials_of[document], placing)
            for c in materials_of[document]:
                if c in placed:
                    materials[placed[c][0].canvas].append(c)
        if scope.canvases_all:
            kept = [c["id"] for c in listed]
        else:
            kept = [
                c["id"] for c in listed if c["id"] in analyses or c["id"] in materials
            ]
        raw = raw_canvases(source)
        planned.update(c for c in kept if c in raw)
        if bounded and len(planned) > limit:
            raise ManifestTooLarge()
        yield _Placement(
            document=document,
            url=manifest_id(url),
            source=source,
            raw=raw,
            position=position,
            number=number,
            scope_analyses=scope_analyses,
            analyses=analyses,
            first=first,
            materials=materials,
            kept=kept,
            whole=scope.kind == "document",
        )


@dataclass(frozen=True, eq=False)
class CanvasPlan:
    """The canvases a scope's manifest holds, decided before anything else is built (``canvas_plan``).

    ``placements`` are the ``_placements`` of the scope and ``canvases`` the
    ids of every folio canvas.
    """

    placements: list
    canvases: frozenset


def canvas_plan(scope):
    """``CanvasPlan`` of *scope*; ``ManifestTooLarge`` over ``EXPLORER_MANIFEST_MAX_CANVASES`` folios.

    The folios are counted while the zones are placed (``_placements``);
    every manifest is read through ``scope.read_manifest``, once per scope.
    """
    plans = list(_placements(scope))
    planned = frozenset(c for plan in plans for c in plan.kept if c in plan.raw)
    return CanvasPlan(plans, planned)


def manifest_offer(scope):
    """What the manifest of *scope* answers: ``"manifest"`` when it holds a folio, ``"tooLarge"`` over
    ``EXPLORER_MANIFEST_MAX_CANVASES`` folios (its route answers 413), None when it holds none.

    A document scope without ``canvases=all`` is the document's own manifest
    (``iiif.document_manifest``): its pages are the union of the pages that
    carry a visible analysis zone or identified-material zone, counted from
    the visitor's facts without building them. Any other scope places every
    folio (``canvas_plan``): the bound needs the whole count.
    """
    if scope.kind == "document" and not scope.canvases_all:
        return _document_offer(scope)
    try:
        plan = canvas_plan(scope)
    except ManifestTooLarge:
        return "tooLarge"
    return "manifest" if plan.canvases else None


def _document_offer(scope):
    reader, version = anonymous_user(), data_version()
    subject = subject_of(scope.subject, reader, version)
    if subject is None:
        return None
    pages = set()
    for kind in ("analysis", "characterization"):
        found = document_facts(
            scope.subject,
            reader,
            kind=kind,
            read=scope.read_manifest,
            version=version,
            positions=frozenset(),
            subject=subject,
        )
        if found is None:
            return None
        pages |= set(found.page_counts(kind))
    if not pages:
        return None
    if len(pages) > settings.EXPLORER_MANIFEST_MAX_CANVASES:
        return "tooLarge"
    return "manifest"


def _imaging(scope):
    """The imaging entries *scope* keeps of each of its analyses."""
    values = Values(list(scope.analyses), ["imaging"], scope.reader)
    return {
        a: kept_files(
            scope,
            a,
            imaging_entries(
                a, values.get(a, "imaging"), scope.language, scope.read_manifest
            ),
        )
        for a in scope.analyses
    }


def _homepage_query(scope):
    if scope.kind == "document":
        return urlencode({"doc": scope.subject})
    if scope.kind == "project":
        return urlencode({"project": scope.subject})
    return urlencode({"sel": scope.params[0][1]}, safe=":,")


def _references(plan, canvas_id):
    """``(kind, only)`` of each page canvas *canvas_id* references."""
    references = []
    if plan.analyses.get(canvas_id):
        references.append(
            (
                "analysis",
                page_filter(plan.analyses[canvas_id], plan.whole),
            )
        )
    if plan.materials.get(canvas_id):
        references.append(
            (
                "characterization",
                page_filter(plan.materials[canvas_id], plan.whole),
            )
        )
    return references


def _embedded_pages(placements):
    """``(document id, kind, only, page number)`` of each page the canvases of *placements* reference."""
    for placement in placements:
        for canvas_id in placement.kept:
            if canvas_id in placement.raw:
                for kind, only in _references(placement, canvas_id):
                    yield placement.document, kind, only, placement.number[canvas_id]


def _header(scope, folios, unlocated, name, name_of, canvases):
    """The ``Header`` of the manifest of *scope* (``iiif.manifest.manifest_header``)."""
    documents = len(scope.documents)
    summary = summary_counts(
        len(scope.analyses),
        len(scope.characterizations),
        folios,
        name(scope.documents[0]) if documents == 1 else {},
        documents,
    )
    if scope.drafts:
        summary = lang.joined([summary, drafts_summary()], sep=". ")
    metadata = [
        {
            "label": (
                lang.gettext_map("Document")
                if documents == 1
                else lang.gettext_map("Documents")
            ),
            "value": lang.listed(
                lang.linked(name(d), ids.report(d)) for d in scope.documents
            ),
        }
    ]
    metadata += aggregate_metadata(analysis_aggregate(scope.analyses, anonymous_user()))
    imaging = {}
    kept_imaging = _imaging(scope)
    for analysis_id in scope.analyses:
        for entry in kept_imaging[analysis_id]:
            imaging.setdefault(
                manifest_id(entry["downloadUrl"]), lang.none(entry["name"])
            )
    imaged = imaging_metadata(list(imaging.items()))
    if imaged:
        metadata.append(imaged)
    if unlocated:
        metadata.append(
            unlocated_metadata(
                [(name_of.get(a) or {}, permalink(a)) for a in unlocated]
            )
        )
    rendering = [
        {
            "id": ids.explorer_export(scope.query),
            "type": "Dataset",
            "format": "application/zip",
            "label": lang.gettext_map("Data package (ZIP)"),
        }
    ]
    if scope.kind == "ids" and spectra_count(scope_content(scope)):
        rendering.append(
            {
                "id": ids.explorer_series(scope.query),
                "type": "Dataset",
                "format": "text/csv",
                "label": lang.gettext_map("Series (CSV)"),
            }
        )
    return Header(
        label=manifest_label(
            scope.kind,
            folios,
            documents,
            name(scope.subject) if scope.kind == "project" else {},
            name(scope.documents[0]) if documents == 1 else {},
            len(scope.analyses),
            len(scope.characterizations),
        ),
        summary=summary,
        metadata=tuple(metadata),
        homepage=tuple(homepages(_homepage_query(scope))),
        rendering=tuple(rendering),
        thumbnail=canvas_thumbnail(canvases.items[0]) if canvases.items else None,
    )


def build_manifest(scope, embed=False):
    """The IIIF Presentation 3 manifest of *scope*, every label in every language.

    ``id`` is the manifest's own URL (``product_url``, no language). The head
    is ``manifest_header``: the label names the project of a project scope,
    else the Selection (« Selection of 2 analyses on 10 pages of <document> »
    or « … of k documents »); ``summary`` counts the analyses, identified
    materials and pages and says when the scope holds drafts; ``metadata``
    lists the documents, the techniques, projects and dates of the analyses
    (the visitor's view), the imaging manifests of the kept analyses (by their
    IIIF id, narrowed to the layers a Selection keeps) and the analyses
    without a located zone (with their permalink); ``homepage`` is the
    Explorer page of the scope in each language; ``rendering`` is the scope's
    data package and, for a Selection holding spectra, its series CSV;
    ``thumbnail`` is the first canvas's. The manifest carries no ``rights``.

    Per document, in ``scope.documents`` order, its manifest gives the
    canvases (``_placements``), each converted by ``v3_canvas``. A canvas's
    ``annotations`` reference the pages of its document
    (``iiif.manifest.canvas_annotations``); with *embed*, the visitor's pages
    are inlined and the manifest's ``@context`` lists the extensions they
    use. The canvases are folios only: no imaging layer is copied.
    ``structures`` holds one Range per document.

    A scope that places no canvas has no manifest: None. More than
    ``EXPLORER_MANIFEST_MAX_CANVASES`` folios raises ``ManifestTooLarge``;
    both are decided by ``canvas_plan`` before any name, page or canvas is
    built.
    """
    plan = canvas_plan(scope)
    if not plan.canvases:
        return None
    mint_id = functools.partial(ids.explorer_part, scope.digest)
    named = set(scope.documents) | set(scope.analyses)
    if scope.kind == "project":
        named.add(scope.subject)
    name_of = names_of(named, scope.nodegroups)
    embedded = (
        EmbeddedPages(scope.read_manifest, _embedded_pages(plan.placements))
        if embed
        else None
    )
    canvases, structures, unlocated, located = Canvases(), [], [], set()

    def name(resource_id):
        return name_of.get(resource_id) or lang.none(resource_id)

    folios = 0
    for placement in plan.placements:
        document, raw, position = placement.document, placement.raw, placement.position
        located.update(placement.first)
        folio_ids = []
        for canvas_id in placement.kept:
            if canvas_id not in raw:
                continue
            canvas = v3_canvas(raw[canvas_id], placement.source, placement.url, mint_id)
            annotations = canvas_annotations(
                document,
                name_of.get(document),
                placement.number[canvas_id],
                position[canvas_id]["label"],
                _references(placement, canvas_id),
                embedded,
            )
            if annotations:
                canvas["annotations"] = annotations
            canvases.add(canvas)
            folio_ids.append(canvas_id)
            folios += 1
        unlocated += [a for a in placement.scope_analyses if a not in placement.first]
        if folio_ids:
            structures.append(
                {
                    "id": mint_id("range", document),
                    "type": "Range",
                    "label": name(document),
                    "items": [{"id": c, "type": "Canvas"} for c in folio_ids],
                }
            )
    placed = located.union(unlocated)
    unlocated += [a for a in scope.analyses if a not in placed]

    manifest = {
        "id": product_url("iiif-v3-explorer-manifest", scope.query, scope.language),
        "type": "Manifest",
        **manifest_header(_header(scope, folios, unlocated, name, name_of, canvases)),
    }
    manifest["items"] = canvases.items
    if structures:
        manifest["structures"] = structures
    return with_context(manifest)
