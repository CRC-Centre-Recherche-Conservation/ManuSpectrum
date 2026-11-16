"""The Presentation 3 manifest of a Document or Component, built from the facts of its annotation collections.

- One ``ManifestReader`` serves the build (the caller's, else a new one): it is passed as ``read=`` to both
  ``document_facts(…, positions=frozenset())`` calls (kinds ``analysis`` and
  ``characterization``), so the source manifest is read once.
- The kept pages are the union of both ``page_counts``, ascending. None, or
  no ``source_url``, gives None; more than ``EXPLORER_MANIFEST_MAX_CANVASES``
  raises ``ManifestTooLarge`` before any canvas is built.
- Canvas *n* is ``v3_canvas`` of the source canvas of page *n* (a page whose
  canvas the source manifest does not hold is left out), ids of a v2
  source minted by ``ids.manifest_part``. Its ``annotations`` reference the
  canonical analyses page when *n* holds analyses, then the canonical
  identified materials page when it holds materials; embedded, the visitor's
  pages are inlined (``EmbeddedPages``). No ``structures``.
- ``label`` is « Analyses of <name> »; ``summary`` counts every kept analysis
  and material of the subject (« Contains drafts » added when an analysis or
  material is unpublished); ``metadata`` is a link to the Document,
  a link to the Component (a Component manifest), the record's summary fields,
  then the analyses' techniques, projects and dates, then the chemical imaging.
- ``homepage`` starts with the report of the subject. A Document the visitor
  sees also gets the Explorer page of the Document and a ``rendering`` of its
  data package; a Component, or a Document hidden from the visitor, none.
"""

import functools
from urllib.parse import urlencode

from django.conf import settings

from manuspectrum.iiif import facts, ids, pages, record
from manuspectrum.iiif import language as lang
from manuspectrum.iiif import manifest, sources, v2
from manuspectrum.iiif.manifest import ManifestTooLarge
from manuspectrum.utils import role_links
from manuspectrum.utils.public_visibility import (
    anonymous_user,
    readable_nodegroup_ids,
    visible_set,
)

KINDS = ("analysis", "characterization")


def _kept_pages(analysis_facts, material_facts):
    counts = {
        kind: set(doc.page_counts(kind))
        for kind, doc in zip(KINDS, (analysis_facts, material_facts))
    }
    return sorted(counts["analysis"] | counts["characterization"]), counts


def _summary(reader, version, analysis_facts, material_facts, kept, name):
    summary = manifest.summary_counts(
        len(analysis_facts.found),
        len(material_facts.found),
        len(kept),
        name,
        1,
    )
    unpublished = visible_set(reader, version).unpublished
    if any(
        str(found) in unpublished
        for found in (*analysis_facts.found, *material_facts.found)
    ):
        summary = lang.joined([summary, manifest.drafts_summary()], sep=". ")
    return summary


def _named_links(resource_id, subject, reader):
    """The « Document » entry, and the « Component » one on a Component manifest: links to their reports."""
    slug, document = subject
    targets = [("Document", document)]
    if slug == "component":
        targets.append(("Component", resource_id))
    names = facts.names_of({rid for _, rid in targets}, readable_nodegroup_ids(reader))

    def link(rid):
        return lang.linked(names.get(rid) or lang.none(rid), ids.report(rid))

    return [
        {
            "label": (
                lang.gettext_map("Document")
                if label == "Document"
                else lang.gettext_map("Component")
            ),
            "value": link(rid),
        }
        for label, rid in targets
    ]


def _metadata(resource_id, subject, reader, version, analysis_facts):
    metadata = _named_links(resource_id, subject, reader)
    metadata += record.record_metadata(
        resource_id, role_links.graph_id_of(subject[0]), reader
    )
    aggregate = facts.analysis_aggregate(analysis_facts.found, reader, version)
    metadata += facts.aggregate_metadata(aggregate)
    imaging = manifest.imaging_metadata(aggregate.imaging)
    if imaging:
        metadata.append(imaging)
    return metadata


def _explorer_links(resource_id, subject, version):
    """``(homepage, rendering)`` of the Explorer for a Document the visitor sees; empty otherwise."""
    if subject[0] != "document" or resource_id not in {
        str(d) for d in visible_set(anonymous_user(), version).documents
    }:
        return [], []
    homepage = manifest.homepages(urlencode({"doc": resource_id}))
    rendering = [
        {
            "id": ids.explorer_export(urlencode({"document": resource_id})),
            "type": "Dataset",
            "format": "application/zip",
            "label": lang.gettext_map("Data package (ZIP)"),
        }
    ]
    return homepage, rendering


def build(resource_id, reader, *, version, subject, embed=False, api=3, read=None):
    """The manifest of *resource_id* for *reader*; None without a readable source manifest or kept page.

    *api* 2 answers the same manifest as Presentation 2.1 (``v2.manifest``).
    *read* is the caller's ``ManifestReader``, else a new one for this build.
    Raises ``ManifestTooLarge`` over ``EXPLORER_MANIFEST_MAX_CANVASES`` pages.
    """
    resource_id = str(resource_id)
    read = read or sources.ManifestReader()
    built = {
        kind: facts.document_facts(
            resource_id,
            reader,
            kind=kind,
            read=read,
            version=version,
            positions=frozenset(),
            subject=subject,
        )
        for kind in KINDS
    }
    analysis_facts, material_facts = built["analysis"], built["characterization"]
    if analysis_facts is None or not analysis_facts.source_url:
        return None
    kept, counts = _kept_pages(analysis_facts, material_facts)
    if not kept:
        return None
    if len(kept) > settings.EXPLORER_MANIFEST_MAX_CANVASES:
        raise ManifestTooLarge()

    source = read(analysis_facts.source_url)
    raw = sources.raw_canvases(source)
    mint_id = functools.partial(ids.manifest_part, resource_id)
    name = analysis_facts.name or lang.none(resource_id)
    references = {n: [kind for kind in KINDS if n in counts[kind]] for n in kept}
    embedded = (
        manifest.EmbeddedPages(
            read, [(resource_id, kind, None, n) for n in kept for kind in references[n]]
        )
        if embed
        else None
    )
    canvases = []
    for n in kept:
        source_canvas = raw.get(analysis_facts.canvases[n - 1])
        if source_canvas is None:
            continue
        canvas = sources.v3_canvas(
            source_canvas,
            source,
            analysis_facts.manifest_url,
            mint_id,
        )
        canvas["annotations"] = manifest.canvas_annotations(
            resource_id,
            name,
            n,
            analysis_facts.canvas_labels[n - 1],
            [(kind, None) for kind in references[n]],
            embedded,
        )
        canvases.append(canvas)
    if not canvases:
        return None

    homepage, rendering = _explorer_links(resource_id, subject, version)
    header = manifest.Header(
        label=pages.named_collection_label(name),
        summary=_summary(reader, version, analysis_facts, material_facts, kept, name),
        metadata=tuple(
            _metadata(resource_id, subject, reader, version, analysis_facts)
        ),
        homepage=(
            {
                "id": ids.report(resource_id),
                "type": "Text",
                "format": "text/html",
                "label": name,
            },
            *homepage,
        ),
        rendering=tuple(rendering),
        thumbnail=sources.canvas_thumbnail(canvases[0]),
    )
    built = pages.with_context(
        {
            "id": ids.manifest(resource_id),
            "type": "Manifest",
            **manifest.manifest_header(header),
            "items": canvases,
        }
    )
    return v2.manifest(built, raw) if api == 2 else built
