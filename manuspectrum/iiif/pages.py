"""AnnotationPages and AnnotationCollections of a Document or a Component (Presentation 3 §5.8).

Page *n* is canvas position *n* (1-based) of the Document's source manifest;
it exists for every canvas, empty or not, and an ``InvalidPage`` is raised out
of range. ``prev`` and ``next`` name the adjacent pages holding an annotation;
a page restricted by *only* carries neither. The collection has no ``items``:
``first`` and ``last`` reference its first and last non-empty pages and
``total`` counts its annotations (left out at zero). A top-level document
carries ``@context``; an embedded page (*embed*) carries none.

*kind* ``analysis`` pages hold the analyses (``supplementing``),
``characterization`` pages the identified materials (``classifying``); each
kind is its own collection.
"""

from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.annotations import analysis_annotation
from manuspectrum.iiif.characterizations import characterization_annotation
from manuspectrum.iiif.constants import PRESENTATION_3

LABELS = {
    "analysis": ("Analyses of %(name)s", "Analyses of %(name)s, %(canvas)s"),
    "characterization": (
        "Identified materials of %(name)s",
        "Identified materials of %(name)s, %(canvas)s",
    ),
}


class InvalidPage(Exception):
    """No canvas holds that position."""


def _name(doc):
    return doc.name or lang.none(doc.document_id)


def collection_label(doc, kind="analysis"):
    return lang.gettext_map(LABELS[kind][0], name=_name(doc))


def annotations_by_page(doc, kind="analysis"):
    """``{page number: [annotation, …]}`` of the located zones of *kind*, in resource then zone order."""
    if kind == "characterization":
        facts, encode = doc.characterizations, characterization_annotation
    else:
        facts, encode = doc.analyses, analysis_annotation
    pages = {}
    for fact in facts:
        for zone in fact.zones:
            pages.setdefault(zone.position, []).append(encode(doc, fact, zone))
    return pages


def annotation_page(doc, n, kind="analysis", *, only=None, embed=False):
    """AnnotationPage *n* of *doc*; *only* names the analysis ids it was restricted to."""
    if not 1 <= n <= len(doc.canvases):
        raise InvalidPage(n)
    pages = annotations_by_page(doc, kind)
    page = {"@context": PRESENTATION_3} if not embed else {}
    page.update(
        id=ids.page(doc.document_id, n, kind, only=only),
        type="AnnotationPage",
        label=lang.gettext_map(
            LABELS[kind][1],
            name=_name(doc),
            canvas=doc.canvas_labels[n - 1] or str(n),
        ),
        partOf=[
            {
                "id": ids.collection(doc.document_id, kind),
                "type": "AnnotationCollection",
                "label": collection_label(doc, kind),
            }
        ],
    )
    if not only:
        numbers = sorted(pages)
        before = [p for p in numbers if p < n]
        after = [p for p in numbers if p > n]
        if before:
            page["prev"] = {
                "id": ids.page(doc.document_id, before[-1], kind),
                "type": "AnnotationPage",
            }
        if after:
            page["next"] = {
                "id": ids.page(doc.document_id, after[0], kind),
                "type": "AnnotationPage",
            }
    page["items"] = pages.get(n, [])
    return page


def page_numbers(doc, kind="analysis"):
    """The numbers of the pages holding an annotation of *kind*, in order."""
    return sorted(annotations_by_page(doc, kind))


def annotation_collection(doc, kind="analysis"):
    """The AnnotationCollection of *doc*: label, ``total``, ``first`` and ``last``; no ``items``."""
    pages = annotations_by_page(doc, kind)
    collection = {
        "@context": PRESENTATION_3,
        "id": ids.collection(doc.document_id, kind),
        "type": "AnnotationCollection",
        "label": collection_label(doc, kind),
    }
    total = sum(len(items) for items in pages.values())
    if total:
        numbers = sorted(pages)
        collection["total"] = total
        collection["first"] = {
            "id": ids.page(doc.document_id, numbers[0], kind),
            "type": "AnnotationPage",
        }
        collection["last"] = {
            "id": ids.page(doc.document_id, numbers[-1], kind),
            "type": "AnnotationPage",
        }
    return collection
