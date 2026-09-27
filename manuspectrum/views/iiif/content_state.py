"""``/iiif/v3/content-state/<resource>/<feature>``: the Content State of one analysis or identified-material zone.

The guard, the statuses and the memo are those of the per-zone annotation
(``views.iiif.annotations.AnnotationView``): an unknown id, a resource that
is neither, or a feature that is not one of its located zones is a bodyless
404; a resource the reader may not read is a 401 to the visitor and a
bodyless 403 to a signed-in or token reader. The body is ``application/ld+json``
under the Presentation 3 profile, with the IIIF CORS headers.
``?download=1`` adds ``Content-Disposition: attachment`` naming the file
``<name>.content-state.json``; the body is the same.
"""

from django.utils.http import content_disposition_header

from manuspectrum.iiif import facts, memo
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.constants import IIIF_MEDIA_TYPE
from manuspectrum.iiif.content_state import content_state
from manuspectrum.utils.data_version import data_version
from manuspectrum.utils.public_visibility import readable_nodegroup_ids
from manuspectrum.views.iiif.annotations import (
    IIIFView,
    Missing,
    gate_of,
    reader_of,
    refused,
)
from manuspectrum.views.iiif.data import safe_name


def _file_name(resource_id, reader):
    names = facts.names_of([resource_id], readable_nodegroup_ids(reader))
    name = lang.first_text(names.get(str(resource_id)) or {}) or str(resource_id)
    return f"{safe_name(name)}.content-state.json"


class ContentStateView(IIIFView):
    """The Content State of one zone of an analysis or an identified material."""

    def answer(self, request, resource_id, feature_id):
        reader = reader_of(request)
        version = data_version()
        access = facts.annotated_access(resource_id, reader, version)
        if access is None:
            raise Missing()
        if access is facts.REFUSED:
            return refused(request)

        def build():
            found = facts.annotated_fact(resource_id, reader, feature_id, version)
            if not isinstance(found, tuple):
                raise Missing()
            kind, _, fact = found
            zone = next((z for z in fact.zones if z.feature == str(feature_id)), None)
            if zone is None:
                raise Missing()
            return content_state(kind, fact.id, zone)

        response = memo.answer(
            request,
            gate_of(request, version),
            "content-state",
            (resource_id, feature_id),
            build,
            content_type=IIIF_MEDIA_TYPE,
        )
        if request.GET.get("download") == "1" and response.status_code == 200:
            response["Content-Disposition"] = content_disposition_header(
                True, _file_name(resource_id, reader)
            )
        return response
