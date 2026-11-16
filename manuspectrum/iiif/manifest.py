"""The IIIF-shaped parts of the Presentation 3 manifests of the Explorer and of a Document.

The header shared by both (``Header``, ``manifest_header``, ``provider``,
``required_statement``) lives here.

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

from dataclasses import dataclass

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


def _counted(analyses, materials):
    """« 81 analyses and 3 identified materials »; a zero count is left out, None when both are zero."""
    parts = []
    if analyses:
        parts.append(
            lang.ngettext_map(
                "%(count)d analysis",
                "%(count)d analyses",
                analyses,
                count=analyses,
            )
        )
    if materials:
        parts.append(
            lang.ngettext_map(
                "%(count)d identified material",
                "%(count)d identified materials",
                materials,
                count=materials,
            )
        )
    if len(parts) == 2:
        return lang.gettext_map(
            "%(first)s and %(second)s", first=parts[0], second=parts[1]
        )
    return parts[0] if parts else None


def manifest_label(
    kind,
    folios,
    documents,
    subject_name,
    document_name,
    analyses=0,
    materials=0,
):
    """The project's name for a project scope, else « Selection of 2 analyses on 10 pages of <document> » or « … of k documents ».

    The counts are those of ``summary_counts``; without an analysis or an
    identified material the analyses count is written as zero.
    """
    if kind == "project":
        return subject_name
    what = _counted(analyses, materials) or lang.ngettext_map(
        "%(count)d analysis", "%(count)d analyses", 0, count=0
    )
    pages_map = lang.ngettext_map(
        "%(count)d page", "%(count)d pages", folios, count=folios
    )
    if documents == 1:
        return lang.gettext_map(
            "Selection of %(what)s on %(pages)s of %(document)s",
            what=what,
            pages=pages_map,
            document=document_name,
        )
    return lang.gettext_map(
        "Selection of %(what)s on %(pages)s of %(documents)s",
        what=what,
        pages=pages_map,
        documents=lang.ngettext_map(
            "%(count)d document", "%(count)d documents", documents, count=documents
        ),
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
    """The ``metadata`` entry listing ``(name, permalink)`` *entries*: one link per entry, joined by "; " in one ``span`` per language.

    An entry without a name shows its permalink as the link text.
    """
    maps = [
        lang.linked(name or lang.none(link), link, markup=True)
        for name, link in entries
    ]
    return {
        "label": lang.gettext_map("Without a position on the image"),
        "value": {
            code: [f"<span>{text}</span>" for text in texts]
            for code, texts in lang.joined(maps, sep="; ").items()
        },
    }


def drafts_summary():
    return lang.gettext_map("Contains drafts")


@dataclass(frozen=True)
class Header:
    """The descriptive head of a manifest; empty parts are left out of its output."""

    label: dict
    summary: dict | None
    metadata: tuple
    homepage: tuple
    rendering: tuple = ()
    thumbnail: list | None = None


def required_statement():
    """The ``requiredStatement``: who publishes the data, in every language."""
    return {
        "label": lang.gettext_map("Attribution"),
        "value": lang.gettext_map(
            "Data published by %(name)s; the rights of each image are stated on its canvas.",
            name=settings.APP_TITLE,
        ),
    }


def provider():
    """The ``provider``: the site, one Agent with its home page in each configured language."""
    homes = []
    for code in lang.languages():
        with translation.override(code):
            path = reverse("root").lstrip("/")
        homes.append(
            {
                "id": f"{settings.PUBLIC_SERVER_ADDRESS}{path}",
                "type": "Text",
                "format": "text/html",
                "label": lang.none(settings.APP_TITLE),
                "language": [code],
            }
        )
    return [
        {
            "id": settings.PUBLIC_SERVER_ADDRESS,
            "type": "Agent",
            "label": lang.none(settings.APP_TITLE),
            "homepage": homes,
        }
    ]


def manifest_header(header):
    """The head properties of *header* in manifest order, each left out when empty."""
    out = {"label": header.label}
    if header.summary:
        out["summary"] = header.summary
    if header.metadata:
        out["metadata"] = list(header.metadata)
    out["requiredStatement"] = required_statement()
    out["provider"] = provider()
    if header.homepage:
        out["homepage"] = list(header.homepage)
    if header.rendering:
        out["rendering"] = list(header.rendering)
    if header.thumbnail:
        out["thumbnail"] = header.thumbnail
    return out


def summary_counts(analyses, materials, pages_count, document_name, documents):
    """« 81 analyses and 3 identified materials on 10 pages of <document> »; a zero count is left out.

    *document_name* names the one document; with several, « k documents ».
    """
    what = _counted(analyses, materials)
    pages_map = lang.ngettext_map(
        "%(count)d page", "%(count)d pages", pages_count, count=pages_count
    )
    if documents == 1 and document_name:
        document = document_name
    else:
        document = lang.ngettext_map(
            "%(count)d document", "%(count)d documents", documents, count=documents
        )
    if not what:
        return pages_map
    return lang.gettext_map(
        "%(what)s on %(pages)s of %(document)s",
        what=what,
        pages=pages_map,
        document=document,
    )


def imaging_metadata(entries):
    """The « Chemical imaging » ``metadata`` entry: one link per ``(manifest id, label map)`` of *entries*, labelled by the stored label, else by the manifest id; None without a link."""
    maps = [
        lang.linked(label or lang.none(href), href, markup=True)
        for href, label in entries
    ]
    joined = lang.joined(maps, sep="; ")
    if not any(joined.values()):
        return None
    return {
        "label": lang.gettext_map("Chemical imaging"),
        "value": {
            code: [f"<span>{text}</span>" for text in texts]
            for code, texts in joined.items()
        },
    }
