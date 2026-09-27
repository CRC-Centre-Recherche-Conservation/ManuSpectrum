"""AnnotationPages and AnnotationCollections of a Document or a Component (Presentation 3 §5.8).

Page *n* is canvas position *n* (1-based) of the Document's source manifest;
it exists for every canvas, empty or not, and an ``InvalidPage`` is raised out
of range. ``prev`` and ``next`` name the adjacent pages holding an annotation;
a page restricted by *only* carries neither. The collection has no ``items``:
``first`` and ``last`` reference its first and last non-empty pages and
``total`` counts its annotations (left out at zero). A top-level document
carries ``@context`` (``with_context``); an embedded page (*embed*) carries
none. Every page and collection declares the Auth 1.0 service
(``services.auth1_block``), the same for every reader.

*kind* ``analysis`` pages hold the analyses (``supplementing``),
``characterization`` pages the identified materials (``classifying``); each
kind is its own collection. ``page_reference`` names a page without its
items, as a manifest's canvas lists it.
"""

from manuspectrum.iiif import ids, services
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


def _mentions(node, key):
    if isinstance(node, dict):
        return key in node or any(_mentions(v, key) for v in node.values())
    if isinstance(node, list):
        return any(_mentions(v, key) for v in node)
    return False


def _typed(node, type_):
    if isinstance(node, dict):
        return node.get("type") == type_ or any(_typed(v, type_) for v in node.values())
    if isinstance(node, list):
        return any(_typed(v, type_) for v in node)
    return False


def with_context(document):
    """*document* opened by its ``@context``: extension contexts first, Presentation 3 last (P3 §4.6).

    The xy-reading context is listed when an ``xyReading`` appears in the
    document, the Auth 2.0 context when an ``AuthProbeService2`` does; alone,
    Presentation 3 is a plain string.
    """
    contexts = [ids.xy_context()] if _mentions(document, "xyReading") else []
    if _typed(document, "AuthProbeService2"):
        contexts.append(services.AUTH2_CONTEXT)
    body = {k: v for k, v in document.items() if k != "@context"}
    return {
        "@context": [*contexts, PRESENTATION_3] if contexts else PRESENTATION_3,
        **body,
    }


class InvalidPage(Exception):
    """No canvas holds that position."""


def _name(doc):
    return doc.name or lang.none(doc.document_id)


def collection_label(doc, kind="analysis"):
    return named_collection_label(_name(doc), kind)


def named_collection_label(name, kind="analysis"):
    """« Analyses of <name> » (or « Identified materials of <name> ») in every language."""
    return lang.gettext_map(LABELS[kind][0], name=name)


def page_label(name, canvas_label, kind="analysis"):
    """« Analyses of <name>, <canvas> » (or « Identified materials of … ») in every language."""
    return lang.gettext_map(LABELS[kind][1], name=name, canvas=canvas_label)


def page_reference(document_id, name, n, canvas_label, kind="analysis", only=None):
    """Page *n* of the collection of *kind* of *document_id* (named *name*), by reference: id, label and ``partOf``."""
    return {
        "id": ids.page(document_id, n, kind, only=only),
        "type": "AnnotationPage",
        "label": page_label(name or lang.none(document_id), canvas_label, kind),
        "partOf": [
            {
                "id": ids.collection(document_id, kind),
                "type": "AnnotationCollection",
                "label": named_collection_label(name or lang.none(document_id), kind),
            }
        ],
    }


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
    page = {}
    page.update(
        id=ids.page(doc.document_id, n, kind, only=only),
        type="AnnotationPage",
        label=page_label(_name(doc), doc.canvas_labels[n - 1] or str(n), kind),
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
    page["service"] = [services.auth1_block()]
    page["items"] = pages.get(n, [])
    return page if embed else with_context(page)


def page_numbers(doc, kind="analysis"):
    """The numbers of the pages holding an annotation of *kind*, in order."""
    return sorted(annotations_by_page(doc, kind))


def annotation_collection(doc, kind="analysis"):
    """The AnnotationCollection of *doc*: label, ``total``, ``first`` and ``last``; no ``items``."""
    pages = annotations_by_page(doc, kind)
    collection = {
        "id": ids.collection(doc.document_id, kind),
        "type": "AnnotationCollection",
        "label": collection_label(doc, kind),
    }
    collection["service"] = [services.auth1_block()]
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
    return with_context(collection)
