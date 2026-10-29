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
   material, or every canvas of the document with ``canvases=all``. The
   layers of an imaging entry follow the canvas of its analysis's first
   zone, else its document's canvases, else the end of the manifest.
"""

import functools
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlencode

from django.conf import settings

from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.facts import CharacterizationZones, listed_source, names_of
from manuspectrum.iiif.manifest import (
    Canvases,
    EmbeddedPages,
    ManifestTooLarge,
    canvas_annotations,
    drafts_summary,
    homepages,
    manifest_label,
    page_filter,
    unlocated_metadata,
)
from manuspectrum.iiif.pages import with_context
from manuspectrum.iiif.sources import (
    absolute_url,
    canvases_of,
    layer_canvas,
    manifest_json,
    v3_canvas,
)
from manuspectrum.iiif.zones import FeatureRows
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.utils.role_links import role_node
from manuspectrum.utils.roles import ROLES
from manuspectrum.views.explorer.scopes import kept_files
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


def _source_canvases(manifest):
    """``{canvas id: raw canvas}`` of a v2 or v3 manifest, in manifest order, ids with legacy hosts rewritten."""
    if not isinstance(manifest, dict):
        return {}
    if CanvasIIIF.detect_version(manifest) == 3:
        raw = manifest.get("items") or []
    else:
        raw = ((manifest.get("sequences") or [{}])[0] or {}).get("canvases") or []
    found = {}
    for canvas in raw:
        canvas_id = canvas.get("id") or canvas.get("@id")
        if canvas_id:
            found.setdefault(rewrite_legacy_url(canvas_id), canvas)
    return found


def _layers(entry, folio_label, mint_id, read=manifest_json):
    """Layer canvases of one kept imaging entry, labelled « <folio> — <layer> »; *read* reads its manifest."""
    url = entry.get("downloadUrl") or ""
    imaging = read(url) or {}
    part_of = absolute_url(url) or url
    layers = []
    for canvas, raw in zip(canvases_of(imaging), _source_canvases(imaging).values()):
        label = " — ".join(t for t in (folio_label, canvas["label"]) if t)
        layers.append(layer_canvas(raw, imaging, part_of, {"none": [label]}, mint_id))
    return layers


@dataclass(frozen=True)
class _Placement:
    """Where the elements of a scope fall on one document's manifest (``_placements``).

    ``url`` is the source manifest's absolute URL (a site path is prefixed
    with ``PUBLIC_SERVER_ADDRESS``). ``number`` gives each listed canvas its
    page number. ``analyses`` and ``materials`` map a canvas id to the kept
    analysis and material ids placed on it; ``whole`` says the scope keeps
    the whole document.
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
        for rid, _, canvas, _ in zones.features(analysis_ids, placing.dims):
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
        raw = _source_canvases(source)
        planned.update(c for c in kept if c in raw)
        if bounded and len(planned) > limit:
            raise ManifestTooLarge()
        yield _Placement(
            document=document,
            url=absolute_url(url) or url,
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


def _layer_ids(entry, read=manifest_json):
    """The canvas ids ``_layers`` gives one kept imaging entry; *read* reads its manifest."""
    imaging = read(entry.get("downloadUrl") or "") or {}
    return list(_source_canvases(imaging))[: len(canvases_of(imaging))]


@dataclass(frozen=True, eq=False)
class CanvasPlan:
    """The canvases a scope's manifest holds, decided before anything else is built (``canvas_plan``).

    ``placements`` are the ``_placements`` of the scope, ``imaging`` the kept
    imaging entries of each analysis, ``read_imaging`` the memoised reader of
    their manifests and ``canvases`` the ids of every folio and layer canvas.
    """

    placements: list
    imaging: dict
    read_imaging: object
    canvases: frozenset


def canvas_plan(scope):
    """``CanvasPlan`` of *scope*; ``ManifestTooLarge`` over ``EXPLORER_MANIFEST_MAX_CANVASES`` canvases.

    The folios are counted while the zones are placed (``_placements``),
    then the folios and layers once the imaging entries are read. Every
    manifest is read through ``scope.read_manifest``, once per scope.
    """
    plans = list(_placements(scope))
    planned = {c for plan in plans for c in plan.kept if c in plan.raw}
    imaging = _imaging(scope)
    read_imaging = scope.read_manifest
    layer_ids = {
        c
        for entries in imaging.values()
        for e in entries
        for c in _layer_ids(e, read_imaging)
    }
    if len(planned | layer_ids) > settings.EXPLORER_MANIFEST_MAX_CANVASES:
        raise ManifestTooLarge()
    return CanvasPlan(plans, imaging, read_imaging, frozenset(planned | layer_ids))


def manifest_offer(scope):
    """What the manifest of *scope* answers: ``"manifest"`` when it holds a canvas, ``"tooLarge"`` over
    ``EXPLORER_MANIFEST_MAX_CANVASES`` canvases (its route answers 413), None when it holds none.

    Every canvas is placed (``canvas_plan``): the bound needs the whole count.
    """
    try:
        plan = canvas_plan(scope)
    except ManifestTooLarge:
        return "tooLarge"
    return "manifest" if plan.canvases else None


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


def build_manifest(scope, embed=False):
    """The IIIF Presentation 3 manifest of *scope*, every label in every language.

    ``id`` is the manifest's own URL (``product_url``, no language),
    ``homepage`` the Explorer page of the scope in each language. The label
    names the project of a project scope, else the Selection (« Selection of
    n pages of <document> » or « … of k documents »). The manifest carries no
    ``rights``; ``summary`` says when the scope holds drafts.

    Per document, in ``scope.documents`` order, its manifest gives the
    canvases (``_placements``), each converted by ``v3_canvas``. A canvas's
    ``annotations`` reference the pages of its document
    (``iiif.manifest.canvas_annotations``); with *embed*, the visitor's pages
    are inlined and the manifest's ``@context`` lists the extensions they
    use. The layers of each kept imaging entry follow the canvas of the
    analysis's first zone, labelled « <folio> — <layer> »; the layers of an
    analysis without a zone follow the canvases of its document (or come
    last). ``structures`` holds one Range per document and one per analysis
    with imaging layers.

    An analysis without a zone on a canvas of its document's manifest is
    listed in the manifest's ``metadata`` with its permalink.

    A scope that places no canvas has no manifest: None. More than
    ``EXPLORER_MANIFEST_MAX_CANVASES`` canvases (folios and layers) raises
    ``ManifestTooLarge``; both are decided by ``canvas_plan`` before any
    name, page or canvas is built.
    """
    plan = canvas_plan(scope)
    if not plan.canvases:
        return None
    mint_id = functools.partial(ids.explorer_part, scope.digest)
    imaging, read_imaging = plan.imaging, plan.read_imaging
    named = set(scope.documents) | set(scope.analyses)
    if scope.kind == "project":
        named.add(scope.subject)
    name_of = names_of(named, scope.nodegroups)
    embedded = (
        EmbeddedPages(scope.read_manifest, _embedded_pages(plan.placements))
        if embed
        else None
    )
    canvases, structures, unlocated, placed = Canvases(), [], [], set()
    layer_ranges = {}

    def name(resource_id):
        return name_of.get(resource_id) or lang.none(resource_id)

    def add_layers(analysis_id, folio_label):
        placed.add(analysis_id)
        for entry in imaging[analysis_id]:
            for layer in _layers(entry, folio_label, mint_id, read_imaging):
                canvases.add(layer)
                layer_ranges.setdefault(analysis_id, []).append(layer["id"])

    folios = 0
    for placement in plan.placements:
        document, raw, position = placement.document, placement.raw, placement.position
        after = defaultdict(list)
        for analysis_id, canvas_id in placement.first.items():
            after[canvas_id].append(analysis_id)
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
            for analysis_id in after.get(canvas_id, ()):
                add_layers(analysis_id, position[canvas_id]["label"])
        for analysis_id in placement.scope_analyses:
            if analysis_id not in placement.first:
                unlocated.append(analysis_id)
                add_layers(analysis_id, lang.first_text(name(analysis_id)))
        if folio_ids:
            structures.append(
                {
                    "id": mint_id("range", document),
                    "type": "Range",
                    "label": name(document),
                    "items": [{"id": c, "type": "Canvas"} for c in folio_ids],
                }
            )
    for analysis_id in scope.analyses:
        if analysis_id not in placed:
            unlocated.append(analysis_id)
            add_layers(analysis_id, lang.first_text(name(analysis_id)))
    for analysis_id in scope.analyses:
        if analysis_id in layer_ranges:
            structures.append(
                {
                    "id": mint_id("range", analysis_id),
                    "type": "Range",
                    "label": name(analysis_id),
                    "items": [
                        {"id": c, "type": "Canvas"} for c in layer_ranges[analysis_id]
                    ],
                }
            )

    manifest = {
        "id": product_url("iiif-v3-explorer-manifest", scope.query, scope.language),
        "type": "Manifest",
        "label": manifest_label(
            scope.kind,
            folios,
            len(scope.documents),
            name(scope.subject) if scope.kind == "project" else {},
            name(scope.documents[0]) if len(scope.documents) == 1 else {},
        ),
    }
    if scope.drafts:
        manifest["summary"] = drafts_summary()
    if unlocated:
        manifest["metadata"] = [
            unlocated_metadata(
                [(name_of.get(a) or {}, permalink(a)) for a in unlocated]
            )
        ]
    manifest["homepage"] = homepages(_homepage_query(scope))
    manifest["items"] = canvases.items
    if structures:
        manifest["structures"] = structures
    return with_context(manifest)
