"""``/iiif/v3|v2/annotation-collection|characterization-collection/<id>[/page-<n>]`` and ``/iiif/v3|v2/annotation/<id>[/<feature>]``.

The annotation collections hold the analyses, the characterization
collections the identified materials.

Collections and pages: a Document or Component the reader may not see, or
an unknown id, is a bodyless 404; otherwise the answer is 200, filtered for
the reader. ``?only=<uuid,…>`` restricts a page to those analyses (at most
``IIIF_PAGE_FILTER_MAX``; malformed or over it: 400); the filtered page is
derived from the canonical page and keeps the ids of the filter that page
holds: a filter naming none of them is a bodyless 404. Single annotations: an
unknown id, a resource that is not an analysis, an analysis without a
located zone or a feature that is not one of its located zones is a 404; an
analysis or identified material the reader may not read is a 401 to the
visitor (the requested id described as an Annotation with the Auth 1.0
service) and a bodyless 403 to a signed-in or token reader. A Bearer
credential that is not a valid IIIF token is a 401 on every route. The
reader is ``iiif.tokens.iiif_reader``; the memo and cache headers are
``iiif.memo``'s, a token reader's answer ``private, no-store``.
"""

import logging
import uuid

import orjson
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.utils.decorators import method_decorator
from django.views import View

from manuspectrum.iiif import facts, ids, memo, pages, services, tokens, v2
from manuspectrum.iiif.annotations import analysis_annotation
from manuspectrum.iiif.characterizations import characterization_annotation
from manuspectrum.iiif.constants import IIIF_MEDIA_TYPE, IIIF_V2_MEDIA_TYPE
from manuspectrum.utils.public_visibility import is_connected
from manuspectrum.views.iiif.cors import iiif_cors

logger = logging.getLogger(__name__)


Missing = memo.Absent


class BadFilter(ValueError):
    """``?only=`` is malformed or names too many ids."""


def _private(response):
    response["Cache-Control"] = memo.PRIVATE
    return response


def not_found():
    return _private(HttpResponseNotFound())


def reader_of(request):
    """The reader of a IIIF read route (``tokens.iiif_reader``)."""
    return tokens.iiif_reader(request)


def gate_of(request):
    """The memo ``Gate`` of the request's reader; a token reader never shares the visitor's view."""
    return memo.gate(reader_of(request), tokens.by_token(request))


def unauthorized(request, kind="Annotation", file_id=None):
    """401 describing the requested resource as a *kind* with the services to sign in through."""
    url = f"{settings.PUBLIC_SERVER_ADDRESS}{request.path.lstrip('/')}"
    response = HttpResponse(
        orjson.dumps(services.description_401(url, kind, file_id)),
        status=401,
        content_type=IIIF_MEDIA_TYPE,
    )
    response["WWW-Authenticate"] = 'Bearer realm="ManuSpectrum IIIF"'
    return _private(response)


def refused(request, kind="Annotation", file_id=None):
    """401 (``unauthorized``) to the visitor, bodyless 403 to a signed-in or token reader."""
    if is_connected(reader_of(request)):
        return _private(HttpResponse(status=403))
    return unauthorized(request, kind, file_id)


def parse_only(request):
    """The analysis ids of ``?only=``, as a frozenset; None without the parameter."""
    raw = request.GET.get("only")
    if raw is None:
        return None
    parts = [p for p in raw.split(",") if p]
    if not parts or len(parts) > settings.IIIF_PAGE_FILTER_MAX:
        raise BadFilter(raw)
    try:
        return frozenset(str(uuid.UUID(p)) for p in parts)
    except ValueError as error:
        raise BadFilter(raw) from error


@method_decorator(iiif_cors, name="dispatch")
class IIIFView(View):
    """GET, HEAD and OPTIONS of one IIIF document, in API ``version`` 3 or 2."""

    http_method_names = ["get", "head", "options"]
    version = 3
    described_as = "Annotation"

    @property
    def content_type(self):
        return IIIF_MEDIA_TYPE if self.version == 3 else IIIF_V2_MEDIA_TYPE

    def get(self, request, **kwargs):
        try:
            if tokens.bearer_state(request) == tokens.INVALID:
                return unauthorized(request, self.described_as)
            return self.answer(request, **kwargs)
        except Missing:
            return not_found()
        except BadFilter:
            return _private(HttpResponseBadRequest())
        except Exception:
            logger.exception("IIIF document failed: %s", request.path)
            return _private(HttpResponse(status=500))

    def answer(self, request, **kwargs):
        raise NotImplementedError


class CollectionView(IIIFView):
    """The AnnotationCollection (v2: ``sc:Layer``) of the analyses (or identified materials, ``kind``) of a Document or Component."""

    kind = "analysis"
    described_as = "AnnotationCollection"

    def answer(self, request, resource_id):
        reader = reader_of(request)
        if facts.subject_of(resource_id, reader) is None:
            raise Missing()

        def build():
            doc = facts.document_facts(resource_id, reader, kind=self.kind)
            collection = pages.annotation_collection(doc, self.kind)
            if self.version == 3:
                return collection
            numbers = pages.page_numbers(doc, self.kind)
            return v2.layer(
                collection,
                [ids.page(doc.document_id, n, self.kind) for n in numbers],
            )

        return memo.answer(
            request,
            gate_of(request),
            f"collection-v{self.version}-{self.kind}",
            (resource_id,),
            build,
            content_type=self.content_type,
        )


class PageView(IIIFView):
    """Page *page_num* (canvas position) of a collection, optionally restricted by ``?only=``.

    A restricted page is derived from the reader's canonical v3 page
    (``pages.filtered_page``) and never stored: its ETag names the canonical
    entry, the API version and the ids kept.
    """

    kind = "analysis"
    described_as = "AnnotationPage"

    def answer(self, request, resource_id, page_num):
        only = parse_only(request)
        reader = reader_of(request)
        if facts.subject_of(resource_id, reader) is None:
            raise Missing()

        def build(version):
            def built():
                doc = facts.document_facts(resource_id, reader, kind=self.kind)
                try:
                    page = pages.annotation_page(doc, page_num, self.kind)
                except pages.InvalidPage as error:
                    raise Missing() from error
                return page if version == 3 else v2.page(page)

            return built

        if only is None:
            return memo.answer(
                request,
                gate_of(request),
                f"page-v{self.version}-{self.kind}",
                (resource_id, page_num),
                build(self.version),
                content_type=self.content_type,
            )

        def derive(canonical):
            try:
                page, kept = pages.filtered_page(canonical, only)
            except pages.InvalidPage as error:
                raise Missing() from error
            variant = f"v{self.version}:" + ",".join(sorted(kept))
            return (page if self.version == 3 else v2.page(page)), variant

        return memo.answer_derived(
            request,
            gate_of(request),
            f"page-v3-{self.kind}",
            (resource_id, page_num),
            build(3),
            derive,
            content_type=self.content_type,
        )


class AnnotationView(IIIFView):
    """One zone of an analysis or an identified material: *feature_id*, else its first located zone."""

    def answer(self, request, resource_id, feature_id=None):
        reader = reader_of(request)
        access = facts.annotated_access(resource_id, reader)
        if access is None:
            raise Missing()
        if access is facts.REFUSED:
            return refused(request)

        def build():
            found = facts.annotated_fact(resource_id, reader, feature_id)
            if not isinstance(found, tuple):
                raise Missing()
            kind, doc, fact = found
            encode = (
                characterization_annotation
                if kind == "characterization"
                else analysis_annotation
            )
            zones = [
                z
                for z in fact.zones
                if feature_id is None or z.feature == str(feature_id)
            ]
            if not zones:
                raise Missing()
            annotation = pages.with_context(encode(doc, fact, zones[0]))
            return annotation if self.version == 3 else v2.annotation(annotation)

        return memo.answer(
            request,
            gate_of(request),
            f"annotation-v{self.version}",
            (resource_id, feature_id or ""),
            build,
            content_type=self.content_type,
        )


class CollectionViewV2(CollectionView):
    version = 2


class PageViewV2(PageView):
    version = 2


class AnnotationViewV2(AnnotationView):
    version = 2


class CharacterizationCollectionView(CollectionView):
    kind = "characterization"


class CharacterizationCollectionViewV2(CollectionViewV2):
    kind = "characterization"


class CharacterizationPageView(PageView):
    kind = "characterization"


class CharacterizationPageViewV2(PageViewV2):
    kind = "characterization"
