"""The IIIF-shaped parts of the Explorer's Presentation 3 manifest (spec §11.1).

A canvas of the manifest does not carry its annotations: it references the
pages of its Document's collections (``pages.page_reference``), the analyses
page and, when the scope keeps an identified material there, the identified
materials page. A page keeps the analyses (or materials) the scope keeps on
that canvas: a Document scope references the canonical page, any other scope
the page filtered by ``?only=`` (the canonical page over
``IIIF_PAGE_FILTER_MAX`` ids). Embedded (the data package), the same
pages are built for the visitor (``anonymous_user()``) and inlined, without
``@context``.

Every label, summary and metadata value is a language map: names as stored,
interface strings in every configured language. ``homepage`` lists the
Explorer page of the scope once per configured language, each with its
``language``.
"""

from django.conf import settings
from django.urls import reverse
from django.utils import translation

from manuspectrum.iiif import facts, pages
from manuspectrum.iiif import language as lang
from manuspectrum.utils.public_visibility import anonymous_user


class ManifestTooLarge(Exception):
    """The manifest would hold more than ``EXPLORER_MANIFEST_MAX_CANVASES`` canvases."""


class Canvases:
    """The manifest's canvases in order, each id once, bounded by ``EXPLORER_MANIFEST_MAX_CANVASES``."""

    def __init__(self):
        self.items, self.ids = [], set()
        self.limit = settings.EXPLORER_MANIFEST_MAX_CANVASES

    def add(self, canvas):
        if canvas["id"] in self.ids:
            return
        if len(self.items) >= self.limit:
            raise ManifestTooLarge()
        self.items.append(canvas)
        self.ids.add(canvas["id"])


def page_filter(kept, whole=False):
    """The ``only`` of a page reference: *kept*, or None for the canonical page.

    The canonical page when the scope keeps the *whole* document, when
    nothing is kept, or over ``IIIF_PAGE_FILTER_MAX`` ids.
    """
    kept = frozenset(kept)
    if whole or not kept or len(kept) > settings.IIIF_PAGE_FILTER_MAX:
        return None
    return kept


class EmbeddedPages:
    """The visitor's pages of the scope's documents, each document's facts read once per kind.

    *wanted* lists the ``(document id, kind, only, page number)`` of every
    page the manifest embeds. A document is read restricted to its pages'
    numbers and to the union of their *only*, every resource of those pages
    when one of them is its canonical page; a document not listed is read
    whole. Each page keeps its own *only* at encoding
    (``pages.annotation_page``). *read* reads the source manifests by URL
    (the caller's memoised reader).
    """

    def __init__(self, read=None, wanted=()):
        self._facts = {}
        self._read = read
        self._reads = {}
        self._positions = {}
        for document_id, kind, only, n in wanted:
            key = (document_id, kind)
            known = self._reads.get(key, frozenset())
            self._reads[key] = None if only is None or known is None else known | only
            self._positions[key] = self._positions.get(key, frozenset()) | {n}

    def page(self, document_id, n, kind, only):
        key = (document_id, kind)
        if key not in self._facts:
            self._facts[key] = facts.document_facts(
                document_id,
                anonymous_user(),
                only=self._reads.get(key),
                kind=kind,
                read=self._read,
                positions=self._positions.get(key),
            )
        doc = self._facts[key]
        if doc is None:
            return None
        try:
            return pages.annotation_page(doc, n, kind, only=only, embed=True)
        except pages.InvalidPage:
            return None


def canvas_annotations(document_id, name, n, canvas_label, references, embedded=None):
    """The ``annotations`` of canvas *n* of *document_id*: one page per ``(kind, only)`` of *references*.

    With *embedded* (``EmbeddedPages``), each page is inlined; a page that
    cannot be built is left out.
    """
    found = []
    for kind, only in references:
        if embedded is not None:
            page = embedded.page(document_id, n, kind, only)
        else:
            page = pages.page_reference(
                document_id, name, n, canvas_label or str(n), kind, only
            )
        if page is not None:
            found.append(page)
    return found


def manifest_label(kind, folios, documents, subject_name, document_name):
    """The project's name for a project scope, else « Selection of n pages of <document> » or « … of k documents »."""
    if kind == "project":
        return subject_name
    if documents == 1:
        return lang.ngettext_map(
            "Selection of %(count)d page of %(document)s",
            "Selection of %(count)d pages of %(document)s",
            folios,
            count=folios,
            document=document_name,
        )
    return lang.ngettext_map(
        "Selection of %(count)d page of %(documents)d documents",
        "Selection of %(count)d pages of %(documents)d documents",
        folios,
        count=folios,
        documents=documents,
    )


def homepages(query):
    """The Explorer page of the scope (*query*, already URL-encoded) in each configured language."""
    found = []
    for code in lang.languages():
        with translation.override(code):
            page = reverse("analysis-explorer").lstrip("/")
        found.append(
            {
                "id": f"{settings.PUBLIC_SERVER_ADDRESS}{page}?{query}",
                "type": "Text",
                "format": "text/html",
                "label": lang.none(settings.APP_TITLE),
                "language": [code],
            }
        )
    return found


def unlocated_metadata(entries):
    """The ``metadata`` entry listing ``(name, permalink)`` *entries*, one joined « name — permalink » string per language."""
    maps = []
    for name, link in entries:
        if name:
            maps.append(
                {code: [f"{lang.text_in(name, code)} — {link}"] for code in name}
            )
        else:
            maps.append(lang.none(link))
    return {
        "label": lang.gettext_map("Without a position on the image"),
        "value": lang.joined(maps, sep="; "),
    }


def drafts_summary():
    return lang.gettext_map("Contains drafts")
